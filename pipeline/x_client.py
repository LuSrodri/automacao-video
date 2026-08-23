"""Coleta dos posts da LISTA do X e sumarização das trends via GPT.

A PAUTA VEM DE UMA LISTA DO X (X_LIST_ID), e de mais nada (2026-08-22, pedido
do usuário). O pipeline lê `/2/lists/{id}/tweets`: uma chamada paginada,
cronológica, com todos os membros da lista. Pôr ou tirar alguém da lista no X é
a forma de mexer na pauta do canal — sem commit e sem deploy.

CAMINHO ÚNICO. Até 2026-08-22 existia embaixo dele a arquitetura anterior
inteira, como fallback: as CONTAS SEGUIDAS (`/2/users/:id/following`) lidas por
`search/recent` com `from:` em lotes de 512 caracteres, mais a TIMELINE de um
subconjunto rotativo das contas. Ela saiu porque escondia defeito — o token
vencido derrubava a lista em 4 das 12 execuções diárias e o vídeo saía assim
mesmo, com a pauta ordenada por RELEVÂNCIA, que é exatamente o viés que a lista
existe para eliminar (medido em 2026-08-17: uma conta com 12 posts em 24h
apareceu ZERO vezes na coleta por lotes). Falha de leitura agora ABORTA.

Usa a X API oficial v2 em modo pay-per-use (a mesma credencial do download de
mídias em midia_x.py). A lista PRIVADA exige contexto de usuário: o access
token OAuth 2.0 é distribuído pelo cron renovador (ver `renovar_token_do_x`).
Sobra da arquitetura antiga uma única busca por `search/recent`,
`buscar_posts_com_video`, que é do formato LONGO e não procura pauta: procura
CLIPE de um assunto já escolhido, fora das contas do canal.

Como a leitura é cobrada por post (~US$ 0,005 cada), X_MAX_POSTS limita a
coleta e X_MAX_POSTS_BUSCA limita a busca aberta por clipes.

Os posts coletados vão para o GPT, que os agrupa nas N trends mais quentes,
ordenadas pelo VALOR DA INFORMAÇÃO (vazamento, exclusivo, urgência, número
inédito) antes do engajamento, no formato que o resto do pipeline consome
(trend, resumo, num_posts, valor_informativo, urgencia, engajamento,
sentimento, apelo_visual, posts, data).
"""

import json
from datetime import datetime, timedelta, timezone

import requests
from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, RAIZ, Config

TOKEN_ENDPOINT = "https://api.x.com/oauth2/token"
SEARCH_ENDPOINT = "https://api.x.com/2/tweets/search/recent"
# Posts dos membros de uma LISTA, em ordem cronológica reversa. Aceita o mesmo
# bearer app-only (conferido contra a API real em 2026-08-17: id inexistente
# devolve "Not Found", não 401/403). É o caminho que dispensa toda a mecânica
# de `from:` — sem limite de 512 caracteres, sem lotes, sem rateio de cota entre
# contas e sem o viés de relevância que enterrava conta pequena. NÃO aceita
# `start_time`: a janela é aplicada no cliente, e a ordem cronológica permite
# parar de paginar assim que os posts ficam mais velhos que ela.
LIST_TWEETS_ENDPOINT = "https://api.x.com/2/lists/{id}/tweets"

MAX_TEXTO_POST = 300  # caracteres do texto de cada post enviados ao GPT

# Fallback de janela de coleta (2026-08-17). A janela curta existe para
# execuções seguidas não pegarem os mesmos posts, mas em hora morta ela devolve
# pouco ou nada — e aí abortar é a resposta errada: o problema não é defeito, é
# um período sem notícia, e o certo é olhar mais para trás. As etapas dobram
# até dois dias; alargar NÃO custa mais na X API (o teto de leitura é o
# X_MAX_POSTS, a janela só decide de que intervalo saem esses posts).
JANELAS_FALLBACK = (8, 12, 24, 48)
# Posts abaixo disto não sustentam uma seleção: o GPT precisa de candidatas
# para comparar contra a régua do canal, e escolher entre duas não é escolher.
MIN_POSTS_JANELA = 20
# Janela da BUSCA ABERTA por clipes (2026-08-17). Independente da janela de
# coleta: lá se procura pauta que ainda não foi usada, aqui se procura imagem de
# um assunto já escolhido — e imagem de um fato do dia continua sendo publicada
# horas depois. Nunca encurta a janela vigente, só alarga.
JANELA_BUSCA_HORAS = 24


def obter_bearer(cfg: Config) -> str | None:
    """Token OAuth2 app-only a partir do consumer key/secret."""
    try:
        resp = requests.post(
            TOKEN_ENDPOINT,
            auth=(cfg.x_consumer_key, cfg.x_consumer_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except (requests.RequestException, KeyError, ValueError) as erro:
        print(f"[aviso] X API: falha ao obter token ({erro})")
        return None


def _get(token: str, url: str, params: dict) -> dict:
    resp = requests.get(
        url, params=params, headers={"Authorization": f"Bearer {token}"}, timeout=30
    )
    resp.raise_for_status()
    return resp.json()


def _normalizar_posts(dados: dict) -> list[dict]:
    """Converte a resposta da X API (lista ou busca) em posts do pipeline.

    Os dois caminhos vivos trazem a expansão de autor, então o @ sai sempre do
    envelope. O parâmetro `usuario_padrao` que existia aqui era da leitura de
    timeline, onde todos os posts eram da mesma conta; saiu com ela em
    2026-08-22.
    """
    includes = dados.get("includes") or {}
    autores = {u["id"]: u["username"] for u in includes.get("users") or []}
    # Tipo de cada mídia anexada: o formato do vídeo é montado SÓ com clipes
    # dos posts, então saber quem tem vídeo nativo orienta a curadoria e a
    # seleção (mesma chamada, nenhum custo extra).
    tipo_midia = {
        m.get("media_key"): m.get("type") for m in includes.get("media") or []
    }

    # Posts ORIGINAIS de reposts, que a expansão referenced_tweets.id devolve
    # junto. É neles que mora a mídia: o repost em si não tem `attachments`, e
    # sem esta resolução todo repost passaria batido como post sem vídeo.
    originais = {t.get("id"): t for t in includes.get("tweets") or []}

    posts = []
    for post in dados.get("data") or []:
        metricas = post.get("public_metrics") or {}
        usuario = autores.get(post.get("author_id"), "")
        # REPOST vira o post ORIGINAL (2026-08-17): a mídia, o texto íntegro (o
        # do repost vem truncado em "RT @fulano: …") e o crédito de reprodução
        # pertencem a quem publicou. Baixar pelo id do repost não traria clipe
        # nenhum — /2/tweets do repost devolve o mesmo envelope vazio.
        id_post = post["id"]
        for ref in post.get("referenced_tweets") or []:
            if ref.get("type") != "retweeted":
                continue
            original = originais.get(ref.get("id"))
            if not original:
                continue
            id_post = original.get("id", id_post)
            usuario = autores.get(original.get("author_id"), "") or usuario
            post = {**post, "text": original.get("text", post.get("text", ""))}
            chaves_orig = (original.get("attachments") or {}).get("media_keys")
            if chaves_orig:
                post["attachments"] = {"media_keys": chaves_orig}
            break
        chaves = (post.get("attachments") or {}).get("media_keys") or []
        tem_video = any(
            tipo_midia.get(c) in ("video", "animated_gif") for c in chaves
        )
        posts.append(
            {
                "url": f"https://x.com/{usuario}/status/{id_post}",
                "usuario": usuario,
                "texto": post.get("text", ""),
                "data": (post.get("created_at") or "")[:16].replace("T", " "),
                "likes": metricas.get("like_count", 0),
                "reposts": metricas.get("retweet_count", 0)
                + metricas.get("quote_count", 0),
                "respostas": metricas.get("reply_count", 0),
                "video": tem_video,
            }
        )
    return posts


def _consultar(
    token: str, query: str, inicio: datetime, max_results: int
) -> list[dict]:
    """Uma consulta à busca do X, já normalizada em posts do pipeline.

    Devolve lista vazia quando a chamada falha: um lote perdido não justifica
    derrubar a coleta inteira (quem chama avisa no log).
    """
    try:
        dados = _get(
            token,
            SEARCH_ENDPOINT,
            {
                "query": query,
                "max_results": max_results,
                "start_time": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "sort_order": "relevancy",
                "tweet.fields": "created_at,public_metrics,text,referenced_tweets",
                # As duas últimas expansões existem para o REPOST: sem elas o
                # post original não vem no envelope e a mídia dele fica
                # invisível (o repost não carrega `attachments` próprio).
                "expansions": (
                    "author_id,attachments.media_keys,referenced_tweets.id,"
                    "referenced_tweets.id.attachments.media_keys,"
                    "referenced_tweets.id.author_id"
                ),
                "user.fields": "username",
                "media.fields": "type",
            },
        )
    except requests.RequestException as erro:
        print(f"[aviso] X API: consulta de posts falhou ({erro}); lote pulado")
        return []
    return _normalizar_posts(dados)


def _por_engajamento(post: dict) -> int:
    return post["likes"] + 3 * post["reposts"] + post["respostas"]


OAUTH2_TOKEN_ENDPOINT = "https://api.x.com/2/oauth2/token"
RENDER_ENV_ENDPOINT = "https://api.render.com/v1/services/{sid}/env-vars/{chave}"
# Vencimento do access token vigente, gravado pelo renovador junto com ele. É o
# que permite trocar o token por IDADE em vez de esperar ele morrer — ver
# `renovar_token_do_x`.
CHAVE_EXPIRA = "X_OAUTH_ACCESS_TOKEN_EXPIRA"


def _minutos_restantes(vencimento: str) -> int | None:
    """Minutos até `vencimento` (ISO-8601 UTC); None quando não dá para ler.

    None e um número negativo dizem coisas diferentes: None é "não sei quando
    vence" (env var ausente ou ilegível), e quem chama renova por precaução;
    negativo é "venceu faz tanto tempo", que é o caso a evitar.
    """
    if not vencimento:
        return None
    try:
        quando = datetime.fromisoformat(vencimento.strip())
    except ValueError:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=timezone.utc)
    return int((quando - datetime.now(timezone.utc)).total_seconds() // 60)


def _ler_do_render(cfg: Config, chave: str) -> str:
    """Valor ATUAL de uma env var no Render; "" quando não dá para ler.

    Existe porque env var do Render só entra no container no DEPLOY seguinte —
    e o token do X muda a cada renovação, várias vezes por dia. Ler de
    `os.environ` (via cfg) devolve o valor congelado no último deploy, que no
    caso do refresh token de USO ÚNICO significa tentar renovar para sempre com
    um token já queimado.

    Foi exatamente o que aconteceu em 2026-08-18: o renovador funcionou uma vez
    às 03:23, gravou o token novo na env var e depois falhou NOVE HORAS seguidas
    relendo o token morto do deploy. A API do Render é a fonte da verdade.
    """
    if not (cfg.render_api_key and cfg.render_token_service_id):
        return ""
    try:
        resp = requests.get(
            "https://api.render.com/v1/services/"
            f"{cfg.render_token_service_id}/env-vars",
            headers={"Authorization": f"Bearer {cfg.render_api_key}"},
            timeout=30,
        )
        if resp.status_code != 200:
            return ""
        for item in resp.json():
            env = item.get("envVar") or {}
            if env.get("key") == chave:
                return (env.get("value") or "").strip()
    except (requests.RequestException, ValueError) as erro:
        print(f"[aviso] não deu para ler {chave} no Render: {erro}")
    return ""


def _gravar_no_render(cfg: Config, chave: str, valor: str) -> bool:
    """Grava uma env var no serviço do renovador; True se gravou.

    O container do cron é descartado ao fim da execução, então a env var do
    Render é o único lugar que os cinco serviços compartilham — e, lida pela
    API (ver `_ler_do_render`), a única que não envelhece junto com o deploy.
    """
    if not (cfg.render_api_key and cfg.render_token_service_id):
        return False
    try:
        resp = requests.put(
            RENDER_ENV_ENDPOINT.format(sid=cfg.render_token_service_id, chave=chave),
            headers={
                "Authorization": f"Bearer {cfg.render_api_key}",
                "Content-Type": "application/json",
            },
            json={"value": valor},
            timeout=30,
        )
        return resp.status_code in (200, 201)
    except requests.RequestException as erro:
        print(f"[aviso] não deu para gravar {chave} no Render: {erro}")
        return False


def _gravar_refresh_no_render(cfg: Config, token: str) -> bool:
    """Persiste o refresh token novo; True se gravou.

    Existe porque o refresh token do X é de USO ÚNICO: cada renovação emite
    outro e mata o anterior na hora (medido em 2026-08-17 — reusar o antigo
    devolve HTTP 400). Sem regravar, a execução seguinte tentaria renovar com um
    valor morto.
    """
    return _gravar_no_render(cfg, "X_OAUTH_REFRESH_TOKEN", token)


CACHE_TOKEN_USUARIO: dict[str, str] = {}
ARQUIVO_REFRESH = RAIZ / ".x_refresh_token"


def renovar_token_do_x(cfg: Config) -> bool:
    """Renova o token do X e distribui o resultado para os crons; True se deu.

    É o modo `--renovar-x-token`, de um cron DEDICADO que não gera vídeo. Existe
    porque o refresh token do X é de uso único: com os quatro crons de vídeo
    renovando por conta própria, quem renovasse por último invalidava o token
    dos outros — a corrida chegou a acontecer entre a máquina local e a produção
    durante os testes de 2026-08-17.

    Com este cron, existe UM escritor. Ele grava duas coisas nos serviços:

    - ``X_OAUTH_ACCESS_TOKEN``: o token de acesso, válido por 2h. É o que os
      crons de vídeo consomem, sem nunca renovar nada.
    - ``X_OAUTH_REFRESH_TOKEN``: a semente da próxima renovação, que só este
      cron usa.
    - ``X_OAUTH_ACCESS_TOKEN_EXPIRA``: quando esse access token vence, para a
      troca acontecer ANTES disso (ver o bloco da margem, abaixo).

    Por isso ele precisa rodar com folga dentro das 2h de validade — de hora em
    hora, na prática. Falhar aqui DERRUBA os vídeos do ciclo seguinte: desde
    2026-08-22 a leitura da lista é o caminho único da pauta, e sem token de
    usuário ela aborta em vez de cair para as contas seguidas.
    """
    if not (cfg.x_oauth_client_id and cfg.x_oauth_client_secret):
        print("[x-token] Sem X_OAUTH_CLIENT_ID/SECRET; nada a renovar.")
        return False

    # RENOVAR POR IDADE, NÃO POR MORTE (2026-08-22). Até aqui o renovador só
    # trocava o token DEPOIS que ele morria: testava /2/users/me e, com 200, não
    # fazia nada. Como o token vale 2h e este cron roda de hora em hora, a troca
    # saía de 3 em 3 horas e sobrava uma JANELA MORTA de até uma hora em cada
    # ciclo — o token vencido parado na env var que os crons de vídeo leem.
    # Medido em 22/08: renovações às 00:20, 03:20, 06:20, 09:20... e 401 na
    # leitura da lista em exatamente as quatro execuções de vídeo que caíam
    # dentro dessas janelas (US 03:02, BR 06:03, US 15:04, BR 18:04) — 4 das 12
    # do dia, todas mascaradas pelo antigo fallback das contas seguidas.
    #
    # Agora o vencimento é gravado junto com o token e a troca acontece enquanto
    # ele ainda vale. Para não sobrar janela morta, a margem tem que ser MAIOR
    # que o intervalo entre execuções deste cron: com 75 minutos e cron de hora
    # em hora, o token é trocado com ~1h de vida pela frente e nunca chega ao
    # fim. Encurtar a margem (menos rotações do refresh) exige encurtar o cron
    # na mesma medida — ver X_TOKEN_MARGEM_MIN em config.py.
    restam = _minutos_restantes(_ler_do_render(cfg, CHAVE_EXPIRA))
    vigente = _ler_do_render(cfg, "X_OAUTH_ACCESS_TOKEN")
    if vigente and restam is not None and restam > cfg.x_token_margem_min:
        # O vencimento é o que se sabe no papel; /2/users/me é o que o X diz de
        # fato. Token revogado antes da hora (senha trocada, app removido) tem
        # data no futuro e responde 401 — sem esta conferência o renovador
        # dormiria em cima dele até uma validade que não vale mais.
        try:
            teste = requests.get(
                "https://api.x.com/2/users/me",
                headers={"Authorization": f"Bearer {vigente}"},
                timeout=30,
            )
            if teste.status_code == 200:
                print(
                    f"[x-token] Access token ainda vale {restam} min (margem de "
                    f"{cfg.x_token_margem_min}); nada a renovar."
                )
                return True
            print(
                f"[x-token] O vencimento gravado diz {restam} min, mas o X "
                f"respondeu {teste.status_code}; renovando assim mesmo."
            )
        except requests.RequestException:
            pass  # sem resposta do X, renova por precaução
    elif restam is None:
        # Primeira execução com esta mudança, ou env var apagada: sem vencimento
        # gravado não há como decidir por idade, e é esta renovação que passa a
        # existir a data.
        print("[x-token] Sem vencimento gravado; renovando para registrá-lo.")
    else:
        print(
            f"[x-token] Access token com {restam} min de vida (margem de "
            f"{cfg.x_token_margem_min}); renovando antes que ele vença."
        )

    access = _token_de_usuario(cfg, renovando=True)
    if not access:
        print(
            "[x-token] Renovação falhou. Se o refresh foi queimado, reautorize "
            "no navegador e regrave X_OAUTH_REFRESH_TOKEN."
        )
        return False
    if not (cfg.render_api_key and cfg.render_token_service_id):
        print("[x-token] Sem RENDER_API_KEY/RENDER_TOKEN_SERVICE_ID; token não salvo.")
        return False
    if not _gravar_no_render(cfg, "X_OAUTH_ACCESS_TOKEN", access):
        print("[x-token] falha ao salvar o access token.")
        return False
    # O vencimento vai DEPOIS do token, nunca antes: gravado primeiro, uma falha
    # na gravação do token deixaria uma data nova apontando para o token velho —
    # e é exatamente essa mentira que reabre a janela morta.
    expira = CACHE_TOKEN_USUARIO.get("expira_em") or ""
    if expira and not _gravar_no_render(cfg, CHAVE_EXPIRA, expira):
        print(
            "[aviso] O access token foi salvo, mas o vencimento não: o ciclo "
            "seguinte renova por precaução (custa uma rotação a mais do "
            "refresh, não uma janela de token morto)."
        )
    vida = _minutos_restantes(expira)
    print(
        "[x-token] Access token renovado e salvo; vale "
        + (f"~{vida} min." if vida is not None else "~2h.")
    )
    return True


def _token_de_usuario(cfg: Config, renovando: bool = False) -> str | None:
    """Access token OAuth 2.0 do USUÁRIO, renovado pelo refresh token.

    Serve só para ler LISTA PRIVADA: todo o resto do pipeline continua no bearer
    app-only, que não expira nem rotaciona. Devolve None quando não há
    credenciais ou quando a renovação falha, e quem chama cai para o app-only —
    que lê lista pública e falha de forma visível na privada.
    """
    # UMA renovação por execução. Sem este cache, cada chamada queimava o
    # refresh anterior — e a segunda já falhava com 400 dentro da MESMA
    # execução, porque o token é de uso único (visto em teste real).
    if "access" in CACHE_TOKEN_USUARIO:
        return CACHE_TOKEN_USUARIO["access"] or None

    # CRON DE VÍDEO: consome o access token que o cron renovador distribuiu e
    # NÃO renova nada. É isto que elimina a corrida — só o renovador escreve.
    # Token vencido aqui não é problema a resolver renovando por conta própria
    # (voltaria a corrida): a execução aborta na leitura da lista e o renovador
    # conserta no ciclo seguinte — que, com a renovação por idade, passou a
    # acontecer ANTES de o token vencer.
    #
    # Lê do RENDER primeiro: o valor em cfg vem do último deploy e envelhece
    # junto com ele — o access token dura 2h, e o deploy pode ter semanas.
    if not renovando:
        access = _ler_do_render(cfg, "X_OAUTH_ACCESS_TOKEN") or cfg.x_oauth_access_token
        if access:
            CACHE_TOKEN_USUARIO["access"] = access
            return access

    # Ordem de confiança do refresh: Render (valor vivo) > env var do container
    # (congelada no deploy) > arquivo local (uso fora do Render). O token é de
    # uso único e muda a cada renovação, então ler do lugar errado significa
    # queimar a cadeia e exigir reautorização manual.
    refresh = (
        _ler_do_render(cfg, "X_OAUTH_REFRESH_TOKEN")
        or cfg.x_oauth_refresh_token
        or (
            ARQUIVO_REFRESH.read_text(encoding="utf-8").strip()
            if ARQUIVO_REFRESH.exists()
            else ""
        )
    )

    if not (cfg.x_oauth_client_id and cfg.x_oauth_client_secret and refresh):
        CACHE_TOKEN_USUARIO["access"] = ""
        return None
    try:
        resp = requests.post(
            OAUTH2_TOKEN_ENDPOINT,
            auth=(cfg.x_oauth_client_id, cfg.x_oauth_client_secret),
            data={"grant_type": "refresh_token", "refresh_token": refresh},
            timeout=30,
        )
    except requests.RequestException as erro:
        print(f"[aviso] X OAuth: renovação falhou ({erro})")
        CACHE_TOKEN_USUARIO["access"] = ""
        return None
    if resp.status_code != 200:
        print(
            f"[aviso] X OAuth: renovação recusada ({resp.status_code}). O "
            "refresh token do X é de uso único — se a execução anterior o "
            "renovou sem gravar o novo, é preciso reautorizar no navegador."
        )
        CACHE_TOKEN_USUARIO["access"] = ""
        return None
    dados = resp.json()
    novo = dados.get("refresh_token")
    if novo and novo != refresh:
        # Grava SEMPRE em disco antes de qualquer outra coisa: o token velho já
        # morreu neste ponto, e perder o novo custa uma reautorização manual no
        # navegador. Localmente o arquivo resolve; no Render ele não sobrevive
        # ao fim do container, e é aí que entra a persistência remota.
        try:
            ARQUIVO_REFRESH.write_text(novo, encoding="utf-8")
        except OSError as erro:
            print(f"[aviso] não deu para gravar o refresh em disco: {erro}")
        if _gravar_refresh_no_render(cfg, novo):
            print("[x] Refresh token do X renovado e gravado no Render.")
        else:
            print(
                "[aviso] O refresh token do X ROTACIONOU e não foi persistido "
                "fora deste container: a próxima renovação no Render vai "
                "falhar, e com ela a leitura da lista — que é o caminho único "
                "da pauta. Reautorize no navegador se isso acontecer."
            )
    # Vencimento do token novo, para o renovador trocar por IDADE em vez de
    # esperar o 401. `expires_in` vem em segundos (7200 na prática); o desconto
    # de um minuto absorve o caminho entre a resposta do X e a gravação.
    segundos = int(dados.get("expires_in") or 0)
    if segundos > 60:
        vence = datetime.now(timezone.utc) + timedelta(seconds=segundos - 60)
        CACHE_TOKEN_USUARIO["expira_em"] = vence.isoformat(timespec="seconds")
    CACHE_TOKEN_USUARIO["access"] = dados.get("access_token") or ""
    return CACHE_TOKEN_USUARIO["access"] or None


def _coletar_da_lista(cfg: Config, token: str) -> list[dict]:
    """Posts dos membros da LISTA (X_LIST_ID), cronológicos, numa chamada só.

    Substitui inteira a mecânica de `search/recent` com `from:`: lá as 162
    contas não cabiam numa query de 512 caracteres, viravam 7 lotes, e o teto de
    leitura era repartido entre eles — 28 posts para 25 contas, escolhidos por
    RELEVÂNCIA. O efeito medido em 2026-08-17 foi conta ativa sumir da coleta
    (@sentdefender publicou 12 vezes em 24h e apareceu zero vez). A lista não
    tem nada disso: é a timeline dos membros, em ordem de publicação.

    Pagina de 100 em 100 até `x_max_posts` e PARA no primeiro post mais velho
    que a janela — como a ordem é cronológica reversa, o resto também será.
    """
    posts: list[dict] = []
    # Lista PRIVADA exige contexto de usuário; na pública o app-only basta.
    token = _token_de_usuario(cfg) or token
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)
    vetadas = {c.lower() for c in (cfg.contas_vetadas or [])}
    pagina = None
    while len(posts) < cfg.x_max_posts:
        params = {
            "max_results": min(100, max(cfg.x_max_posts - len(posts), 10)),
            "tweet.fields": "created_at,public_metrics,text",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username",
            "media.fields": "type",
        }
        if pagina:
            params["pagination_token"] = pagina
        try:
            dados = _get(token, LIST_TWEETS_ENDPOINT.format(id=cfg.x_list_id), params)
        except requests.RequestException as erro:
            # SEM REDE DEBAIXO desde 2026-08-22: a lista é o caminho único, e
            # falhar aqui é falhar a execução. Página que quebra no MEIO da
            # paginação ainda aproveita o que já veio; o que não pode é seguir
            # de mãos vazias e o vídeo sair de uma pauta pior sem ninguém ver.
            if posts:
                print(f"[aviso] X API: paginação da lista parou ({erro})")
                break
            raise SystemExit(
                f"Leitura da lista {cfg.x_list_id} falhou: {erro}\n"
                "401 aqui é access token do X vencido — confira o cron "
                "x-token-refresher e X_OAUTH_ACCESS_TOKEN no serviço dele. "
                "404 é lista inexistente ou fora do alcance deste token."
            ) from erro
        lote = _normalizar_posts(dados)
        if not lote:
            break
        antigos = False
        for post in lote:
            # `data` chega como "YYYY-MM-DD HH:MM" (ver _normalizar_posts)
            try:
                quando = datetime.strptime(post["data"], "%Y-%m-%d %H:%M").replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                quando = None
            if quando and quando < inicio:
                antigos = True
                continue
            if post["usuario"].lower() in vetadas:
                continue
            posts.append(post)
        pagina = (dados.get("meta") or {}).get("next_token")
        if antigos or not pagina:
            break
    return posts


def buscar_posts_com_video(cfg: Config, consulta: str) -> list[str]:
    """URLs de posts com clipe sobre o assunto, de QUALQUER conta do X.

    A coleta só enxerga os membros da LISTA, então o material fica limitado ao
    que eles publicaram sobre ESTE fato — que é o gargalo real do formato longo
    (vídeo não falta no X; falta vídeo concentrado num mesmo acontecimento).
    Esta busca é aberta.

    Em troca, as fontes NÃO são curadas: entra conta desconhecida, telejornal
    reempacotado e, eventualmente, material enganoso. Quem filtra depois é a
    auditoria de visão, que julga PERTINÊNCIA, não veracidade — por isso o
    orçamento aqui é modesto de propósito, e X_MAX_POSTS_BUSCA=0 desliga.

    Falha da API não aborta: devolve lista vazia e a execução segue com o
    material da lista. É a única coleta que ainda falha em silêncio, e pode:
    ela ACRESCENTA clipe a um assunto já escolhido, não decide pauta.
    """
    orcamento = getattr(cfg, "x_max_posts_busca", 0) or 0
    consulta = (consulta or "").strip()
    if not (orcamento and consulta):
        return []

    token = obter_bearer(cfg)
    if token is None:
        print("[aviso] Sem token da X API; busca aberta por clipes pulada.")
        return []

    # SEM filtro de língua, de propósito. Tentar `lang:pt` no canal BR zerou a
    # busca numa execução real: a consulta de assunto que o pipeline gera vem
    # em INGLÊS mesmo no BR ("Iran US ceasefire talks"), então palavra inglesa
    # com filtro de português não casa com quase nada. E o filtro é discutível
    # de todo modo — num clipe o que importa é o que aparece NA TELA, não o
    # idioma do post, e disso a auditoria de visão já cuida.
    query = f"({consulta}) has:videos -is:retweet -is:reply"
    # JANELA PRÓPRIA (2026-08-17). A da coleta existe para execuções seguidas
    # não repetirem PAUTA, e com JANELA_HORAS=4 ela é curta de propósito. Aqui
    # não se procura pauta: o assunto já está escolhido, e o que se procura é
    # imagem DELE. Um fato das 9h da manhã tem clipe publicado ao longo do dia
    # inteiro, e herdar as 4h jogava fora justamente esse material.
    horas = max(cfg.janela_horas, JANELA_BUSCA_HORAS)
    inicio = datetime.now(timezone.utc) - timedelta(hours=horas)

    print(f"[midia-x] Busca aberta por clipes sobre: {consulta}")
    posts = _consultar(token, query, inicio, min(max(orcamento, 10), 100))
    posts = [p for p in posts if p.get("video")]
    posts.sort(key=_por_engajamento, reverse=True)
    posts = posts[:orcamento]
    print(
        f"[midia-x] Busca aberta achou {len(posts)} post(s) com clipe fora da "
        "lista (fontes não curadas; a auditoria decide o que entra)."
    )
    return [p["url"] for p in posts]


def _listar_posts(posts: list[dict]) -> str:
    linhas = []
    for p in posts:
        texto = " ".join(p["texto"].split())[:MAX_TEXTO_POST]
        video = " | COM VÍDEO" if p.get("video") else ""
        linhas.append(
            f"- @{p['usuario']} | {p['data']} UTC | {p['likes']} likes, "
            f"{p['reposts']} reposts, {p['respostas']} respostas{video}\n"
            f"  {p['url']}\n"
            f"  \"{texto}\""
        )
    return "\n".join(linhas)


INSTRUCOES_RESUMO = """\
Você é curador de um canal de vídeos de ANÁLISE. O canal trata cada pauta em
formato EXPLICATIVO — análise ou educacional: o vídeo explica o que aconteceu,
como funciona e por que importa.

TODOS OS TEMAS SÃO ELEGÍVEIS (2026-08-16, pedido do usuário). O canal não tem
mais recorte temático: tecnologia, IA, negócios, trabalho, mercado financeiro,
ciência, saúde, política, mundo, esporte, cultura, entretenimento, crime,
clima, educação, consumo — o que estiver acontecendo e render explicação entra.
Não existe assunto vetado por tema, e não existe assunto obrigatório: o que
decide é o VALOR DA INFORMAÇÃO abaixo e, depois dele, o que a audiência do
canal assiste.

Você recebe os posts publicados nas últimas {horas} horas pelas contas que o
usuário SEGUE no X, com autor, data, métricas de engajamento e texto. Agrupe-os
nas ATÉ {n} TRENDS mais quentes: anúncios e lançamentos, resultados, números
divulgados, mudanças de preço, demissões e contratações, aquisições, decisões e
julgamentos, regulação, quedas de serviço, descobertas, pesquisas, acidentes e
desastres, competições, rumores e disputas.

ORDENE PELO VALOR DA INFORMAÇÃO, não pelo barulho. Sobem para o topo:
1. VAZAMENTO, documento interno, memorando, print de comunicado, benchmark ou
   número que ainda não estava público;
2. EXCLUSIVO ou primeira mão — a conta é a FONTE do fato, não quem comenta o
   fato dos outros;
3. URGÊNCIA: acabou de acontecer, está acontecendo agora ou tem prazo curto
   (corte que começa amanhã, decisão marcada, oferta que expira);
4. NÚMERO CONCRETO E VERIFICÁVEL: dinheiro, vagas, preço, porcentagem, prazo;
5. CONSEQUÊNCIA DIRETA para quem trabalha ou investe.
Descem para o fim: opinião sem fato novo, previsão genérica, thread
motivacional, recorte de notícia velha e "alguém disse que acha que".
Engajamento (likes, reposts, respostas) e volume de posts continuam pesando —
mas como desempate, DEPOIS do valor da informação.

Cada trend deve ser um ACONTECIMENTO específico e datado — quem fez o quê, com
número quando houver — NUNCA um tema guarda-chuva. "Oracle corta 21.000 vagas e
cita IA no comunicado" é trend; "demissões em tech por causa da IA" não é.
{foco_usa}
Regras dos campos:
- "trend": o acontecimento específico, com nome próprio e número exato quando
  houver (ex.: "Oracle corta 21.000 vagas citando IA", nunca "demissões em tech").
- "resumo": 2 a 4 frases com os fatos, nomes, empresas e números concretos que
  apareceram nos posts. Reproduza com fidelidade, sem inventar nada.
- "num_posts": quantos dos posts listados acima falam deste assunto (conte
  TODOS os que pertencem à trend, mesmo os que não entrarem em "posts").
- "valor_informativo": UMA frase dizendo o que esta trend entrega de
  informação que ainda não é conhecimento comum — o vazamento, o documento, o
  exclusivo, o número inédito, o prazo que aperta. Se o assunto for só
  repercussão de algo que todo mundo já sabe, diga isso com essas palavras
  ("apenas repercussão, sem fato novo").
- "urgencia": "agora" (está acontecendo ou saiu nas últimas horas), "hoje"
  (fato do dia, ainda quente) ou "morno" (já circulou, sem prazo apertando).
- "engajamento": uma frase sobre o quão quente está (some as métricas dos posts
  do assunto e cite quem está falando).
- "sentimento": a EMOÇÃO dominante nos posts (indignação, medo, deboche,
  euforia, ceticismo, fascínio...) e por quê — o que está movendo a conversa.
- "apelo_visual": uma frase sobre o quanto o assunto rende boas imagens reais
  (pessoas conhecidas, produtos, eventos, lugares) — alto/médio/baixo e por quê.
- "posts": até {max_urls} URLs escolhidas SOMENTE entre as listadas acima, dos
  posts mais centrais da trend (os que originaram ou melhor documentam o
  assunto). O vídeo do canal é montado com os CLIPES anexados a esses posts:
  entre posts igualmente centrais, PRIORIZE os marcados com "COM VÍDEO" — uma
  trend sem nenhum post com vídeo não vira vídeo do canal, e quanto mais posts
  com vídeo, melhor. Nunca invente URL.
- "posts_video": as URLs de TODOS os posts marcados com "COM VÍDEO" que
  pertencem a esta trend, mesmo os que você não colocou em "posts" por não
  serem os mais centrais — e mesmo que já estejam lá. Este campo NÃO é
  ranqueado por importância: é o inventário do material de vídeo disponível
  sobre o assunto, e é ele que decide se a trend tem imagem suficiente para
  virar vídeo. Deixar de fora um post com vídeo do assunto elimina a pauta
  injustamente. Lista vazia se nenhum post da trend tem vídeo. Nunca invente
  URL.
- "data": YYYY-MM-DD do acontecimento.\
"""

ESQUEMA_TRENDS = {
    "name": "trends_do_x",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "trends": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "trend": {"type": "string"},
                        "resumo": {"type": "string"},
                        "num_posts": {"type": "integer"},
                        "valor_informativo": {
                            "type": "string",
                            "description": (
                                "O que esta trend entrega que ainda não é "
                                "conhecimento comum (vazamento, documento, "
                                "exclusivo, número inédito, prazo curto)."
                            ),
                        },
                        "urgencia": {
                            "type": "string",
                            "enum": ["agora", "hoje", "morno"],
                        },
                        "engajamento": {"type": "string"},
                        "sentimento": {"type": "string"},
                        "apelo_visual": {"type": "string"},
                        "posts": {"type": "array", "items": {"type": "string"}},
                        "posts_video": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "URLs de TODOS os posts da trend marcados com "
                                "COM VÍDEO, inclusive os fora de 'posts'."
                            ),
                        },
                        "data": {"type": "string"},
                    },
                    "required": [
                        "trend",
                        "resumo",
                        "num_posts",
                        "valor_informativo",
                        "urgencia",
                        "engajamento",
                        "sentimento",
                        "apelo_visual",
                        "posts",
                        "posts_video",
                        "data",
                    ],
                },
            }
        },
        "required": ["trends"],
    },
}


def _resumir_trends(cfg: Config, posts: list[dict]) -> list[dict]:
    """GPT agrupa os posts coletados nas N trends mais quentes."""
    cliente = OpenAI(api_key=cfg.openai_api_key)

    foco_usa = (
        "\nPriorize o que está dominando a conversa NOS ESTADOS UNIDOS: contas e "
        "empresas americanas e notícias com impacto nos EUA.\n"
        if cfg.publico == "usa"
        else ""
    )
    instrucoes = INSTRUCOES_RESUMO.format(
        horas=cfg.janela_horas,
        n=cfg.num_trends,
        foco_usa=foco_usa,
        max_urls=cfg.max_urls_trend,
    )

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {
                "role": "user",
                "content": AVISO_DADOS_EXTERNOS
                + "\n\nPosts coletados:\n"
                + _listar_posts(posts),
            },
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_TRENDS},
    )
    return json.loads(resposta.choices[0].message.content)["trends"]


def coletar_trends(cfg: Config) -> list[dict]:
    """Posts da LISTA do X (X_LIST_ID), resumidos em trends pelo GPT.

    Caminho único desde 2026-08-22: não há mais fallback para as contas
    seguidas — ver o cabeçalho do módulo. Falta de lista, token vencido ou
    janela sem material param a execução com SystemExit, que o agendador
    transforma em e-mail.
    """
    if not cfg.x_list_id:
        raise SystemExit(
            "Sem X_LIST_ID não há pauta: a coleta lê a LISTA do X e o caminho "
            "pelas contas seguidas não existe mais. Preencha X_LIST_ID no .env "
            "(ou no Render) com o id da lista."
        )

    token = obter_bearer(cfg)
    if token is None:
        raise SystemExit(
            "Sem token da X API não há coleta de posts. Confira X_CONSUMER_KEY "
            "e X_CONSUMER_SECRET no .env."
        )

    print(
        f"[x] Lendo a lista {cfg.x_list_id} (até {cfg.x_max_posts} posts "
        f"das últimas {cfg.janela_horas}h, ordem cronológica)..."
    )
    posts = _coletar_da_lista(cfg, token)

    # FALLBACK DE JANELA (2026-08-17) — este fica: não é um caminho alternativo
    # de coleta, é a MESMA lista lida mais para trás. A janela de 4h existe para
    # execuções seguidas não repetirem pauta, não para desistir quando o poço
    # está seco (a primeira execução real, às 03:03 UTC, trouxe 5 candidatas e
    # nenhuma com clipe).
    #
    # O gatilho olha DUAS coisas, e a segunda foi aprendida na marra: o vídeo é
    # montado só com clipe, então uma janela cheia de posts sem vídeo nenhum é
    # tão inútil quanto uma janela vazia. Contando só o total, a execução das
    # 03:10 UTC passou direto pelo fallback com 20+ posts e morreu logo depois
    # em "5 candidatas sem post com vídeo".
    def _insuficiente(lote: list[dict]) -> bool:
        return len(lote) < MIN_POSTS_JANELA or not any(p["video"] for p in lote)

    if posts and _insuficiente(posts):
        original = cfg.janela_horas
        for janela in JANELAS_FALLBACK:
            if janela <= cfg.janela_horas:
                continue
            print(
                f"[x] {len(posts)} post(s) na lista em {cfg.janela_horas}h, "
                f"{sum(1 for p in posts if p['video'])} com clipe; "
                f"reabrindo a janela para {janela}h..."
            )
            cfg.janela_horas = janela
            posts = _coletar_da_lista(cfg, token)
            if not _insuficiente(posts):
                break
        cfg.janela_horas = original

    if not posts:
        raise SystemExit(
            f"A lista {cfg.x_list_id} não devolveu post nenhum nem alargando a "
            f"janela até {JANELAS_FALLBACK[-1]}h. Confira se ela ainda tem "
            "membros e se o token do X está válido."
        )

    # Quantos posts trazem clipe é O número que decide se há material: o vídeo é
    # montado só com clipes. Sem esta contagem a escassez só aparecia lá na
    # frente, como "pool de 2 clipes".
    com_video = sum(1 for p in posts if p.get("video"))
    print(
        f"[x] {len(posts)} posts na lista ({com_video} com clipe de vídeo "
        "nativo); resumindo as trends com o GPT..."
    )
    return _montar_trends(cfg, posts)


def _montar_trends(cfg: Config, posts: list[dict]) -> list[dict]:
    """Agrupa os posts em trends e devolve o formato que o resto consome.

    Mora numa função própria desde 2026-08-18, quando havia dois caminhos de
    coleta e a leitura por lista retornava direto de `_resumir_trends`, pulando
    tudo isto: as trends saíam sem `posts_com_video` e a seleção derrubava
    todas com "sem nenhum post com vídeo nativo" mesmo havendo 10 clipes na
    coleta. Sobrou um caminho só, mas a separação segue útil — é aqui que a
    contagem de clipe e o filtro de URLs realmente coletadas acontecem.
    """
    brutos = _resumir_trends(cfg, posts)
    urls_reais = {p["url"] for p in posts}
    urls_com_video = {p["url"] for p in posts if p.get("video")}

    trends = []
    for t in brutos:
        if not (t.get("trend") and t.get("resumo")):
            continue
        # "posts" é ranqueado por centralidade e truncado em max_urls_trend;
        # "posts_video" é o inventário completo do material de vídeo da trend.
        # Contar o vídeo só no primeiro vetava pauta que TINHA clipe, mas cujo
        # clipe não estava entre os posts mais centrais — falso negativo que
        # matava o assunto em definitivo. A união das duas listas é a contagem
        # honesta. Garante também que só URLs realmente coletadas seguem.
        brutas = [u for u in (t.get("posts_video") or []) if u in urls_com_video]
        brutas += [u for u in (t.get("posts") or []) if u in urls_reais]

        vistos: set[str] = set()
        com_video: list[str] = []
        sem_video: list[str] = []
        for u in brutas:
            if u in vistos:
                continue
            vistos.add(u)
            (com_video if u in urls_com_video else sem_video).append(u)

        # Posts com vídeo primeiro: o lookup de mídias corta esta lista no teto
        # de max_posts_midia, e é dela que sai o pool de clipes.
        urls = com_video + sem_video
        trends.append(
            {
                "trend": t.get("trend", "").strip(),
                "resumo": t.get("resumo", "").strip(),
                "num_posts": max(int(t.get("num_posts") or 0), len(urls)),
                "valor_informativo": t.get("valor_informativo", "").strip(),
                "urgencia": (t.get("urgencia") or "morno").strip().lower(),
                "engajamento": t.get("engajamento", "").strip(),
                "sentimento": t.get("sentimento", "").strip(),
                "apelo_visual": t.get("apelo_visual", "").strip(),
                "posts": urls,
                # Quantos posts da trend têm vídeo nativo: o formato do canal é
                # montado só com clipes do X, então trend sem nenhum post com
                # vídeo sai da disputa na seleção.
                "posts_com_video": len(com_video),
                "data": t.get("data", ""),
            }
        )

    if not trends:
        raise SystemExit(
            f"Nenhuma trend identificada nos {len(posts)} posts coletados. "
            "Aumente JANELA_HORAS ou X_MAX_POSTS no .env."
        )

    print(f"[x] {len(trends)} trends identificadas")
    return trends
