"""Coleta dos posts do X que viram pauta, e sumarização das trends via GPT.

DUAS FONTES, EM ORDEM (2026-08-28, desenho do usuário: "vídeos curtidos
--fallback--> lista do X"), e as MESMAS para os dois formatos — Short e longo
entram por `coletar_trends` e recebem a mesma pauta elegível:

1. AS CURTIDAS DO USUÁRIO (`/2/users/:id/liked_tweets`), as X_MAX_POSTS mais
   recentes, SEM RECORTE DE DATA (2026-08-29). É a fonte primária: curtir um
   post é curadoria a mão que já acontece de graça, e o mesmo orçamento de
   leitura passa a comprar material escolhido em vez de timeline bruta. Exige
   contexto de usuário COM O ESCOPO `like.read` — um a mais do que a lista
   privada precisa. Ver `_coletar_curtidos` para as três coisas que a API NÃO
   entrega aqui (quando a curtida aconteceu, `start_time`, ordem por data do
   post) e o que se faz na falta delas.
2. A LISTA DO X (X_LIST_ID, `/2/lists/{id}/tweets`): uma chamada paginada,
   cronológica, com todos os membros da lista. Foi o caminho único entre
   2026-08-22 e 2026-08-28 e continua inteira aqui, agora como FALLBACK. Pôr ou
   tirar alguém da lista no X segue sendo a forma de mexer nela — sem commit e
   sem deploy.

O fallback dispara por ESCASSEZ (menos de X_CURTIDOS_MIN posts aproveitáveis
nas curtidas), não por exceção: o modo de falha real da fonte nova é semana sem
curtir, curtida em post de texto ou escopo ausente, e todos chegam como
"veio pouco". Ver `coletar_trends`.

E SÓ SOBE POST COM CLIPE (2026-08-25, pedido do usuário): repost e post sem
mídia nativa são descartados na coleta. A v2 não filtra mídia no servidor — não
existe parâmetro de tipo nem no endpoint de lista nem no de curtidas —, então o
corte é feito aqui, sobre `expansions=attachments.media_keys` +
`media.fields=type,duration_ms`, que já vêm no mesmo envelope e não custam
chamada extra. Os filtros das duas fontes moram num lugar só (`_filtrar_posts`)
justamente para não divergirem.

NO SHORT ENTRA UM TETO DE DURAÇÃO (2026-08-28): post cujo menor clipe passa de
CURTO_MAX_DUR_CLIPE segundos não vira pauta. Ele é a contrapartida do fim do
loop na montagem — sem repetir clipe, o material é o teto do vídeo, e clipe
comprido demais é clipe do qual só se usaria o começo. A duração vem de
`duration_ms`, no mesmo envelope, e é ela também que dimensiona o roteiro (o
campo `segundos_video` de cada trend; ver `_montar_trends`).

O QUE NÃO É FILTRADO AQUI, de propósito: TIPO DE MATERIAL e MACROTEMA. Os dois
já existem no pipeline e custam o que esta camada não pode pagar — o tipo do
material (slide, screenshot, gravação de tela) é visão do GPT sobre frames do
clipe (triagem.py antes da escolha da pauta, auditoria.py como palavra final) e
macrotema é uma chamada de LLM sobre a trend já formada (classificacao.py, com
o corte em main.py). Ver `_filtrar_posts`.

A LISTA FOI CAMINHO ÚNICO ENTRE 2026-08-22 E 2026-08-28. Antes de 22/08
existia embaixo dela a arquitetura anterior inteira, como fallback: as CONTAS
SEGUIDAS (`/2/users/:id/following`) lidas por
`search/recent` com `from:` em lotes de 512 caracteres, mais a TIMELINE de um
subconjunto rotativo das contas. Ela saiu porque escondia defeito — o token
vencido derrubava a lista em 4 das 12 execuções diárias e o vídeo saía assim
mesmo, com a pauta ordenada por RELEVÂNCIA, que é exatamente o viés que a lista
existe para eliminar (medido em 2026-08-17: uma conta com 12 posts em 24h
apareceu ZERO vezes na coleta por lotes). Falha de leitura agora ABORTA.

Usa a X API oficial v2 em modo pay-per-use (a mesma credencial do download de
mídias em midia_x.py). As CURTIDAS e a lista PRIVADA exigem contexto de
usuário: o access token OAuth 2.0 é distribuído pelo cron renovador (ver
`renovar_token_do_x`).
Sobra da arquitetura antiga uma única busca por `search/recent`,
`buscar_posts_com_video`, que é do formato LONGO e não procura pauta: procura
CLIPE de um assunto já escolhido, fora das contas do canal.

Como a leitura é cobrada por post (~US$ 0,005 cada), X_MAX_POSTS limita a
coleta e X_MAX_POSTS_BUSCA limita a busca aberta por clipes. Desde 2026-08-25
são 100 posts por vídeo — o máximo que a X API entrega numa chamada, e por isso
o teto virou UMA leitura só, de US$ 0,50, sem paginação.

NENHUMA JANELA DE TEMPO SE APLICA ÀS DUAS FONTES DE PAUTA: nem à LISTA
(2026-08-25) nem às CURTIDAS, que perderam a janela própria de dias em
2026-08-29, a pedido do usuário e pelo mesmo motivo das duas vezes anteriores —
recortar por data DEPOIS da leitura joga fora post já pago sem economizar um
centavo, e a ordem da fonte já faz o papel de janela (a lista vem cronológica,
as curtidas vêm da mais recente para a mais antiga). Medido nas quatro
execuções BR de 28-29/08: a janela de 7 dias descartava 16 a 17 dos 100 posts
lidos, ~17% do orçamento comprado e jogado fora. A v2
não filtra data no endpoint de lista (confirmado no OpenAPI: `getListsPosts`
aceita só `id`, `max_results` e `pagination_token`), então a janela era um corte
DEPOIS de pagar — jogava fora post já comprado. Como a timeline vem em ordem
cronológica reversa, ler os 100 mais recentes já É a janela, e ela se ajusta
sozinha ao movimento da lista. JANELA_HORAS segue valendo onde o filtro é do
SERVIDOR e não custa leitura à toa: `start_time` da busca aberta por clipes e a
janela do panorama do YouTube em seo.py.

Os posts coletados vão para o GPT, que os agrupa nas N trends mais quentes,
ordenadas pelo VALOR DA INFORMAÇÃO (vazamento, exclusivo, urgência, número
inédito) antes do engajamento, no formato que o resto do pipeline consome
(trend, resumo, num_posts, valor_informativo, urgencia, engajamento,
sentimento, apelo_visual, posts, data).
"""

import base64
import hashlib
import http.server
import json
import os
import re
import threading
import urllib.parse
import webbrowser
from copy import copy
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
# Posts que o DONO DA CONTA curtiu, do mais recente para o mais antigo. É a
# fonte PRIMÁRIA da pauta desde 2026-08-28: curtir um post no X é o gesto de
# curadoria mais barato que existe, e ele já acontece — a lista continua
# embaixo, como fallback.
#
# Três limitações da v2, todas conferidas no OpenAPI antes de desenhar em cima:
#   - exige CONTEXTO DE USUÁRIO com o escopo `like.read` (o bearer app-only não
#     enxerga curtida de ninguém). Sem o escopo o X responde 403 e a coleta cai
#     para a lista, que é exatamente o desenho pedido;
#   - NÃO aceita `start_time`/`end_time`. A janela de dias é aplicada aqui, na
#     data do POST;
#   - NÃO devolve QUANDO a curtida aconteceu. O que se sabe é a ORDEM: o
#     endpoint entrega da curtida mais recente para a mais antiga. Ver
#     `_coletar_curtidos` para o que isso significa na prática.
LIKED_TWEETS_ENDPOINT = "https://api.x.com/2/users/{id}/liked_tweets"
ME_ENDPOINT = "https://api.x.com/2/users/me"

MAX_TEXTO_POST = 300  # caracteres do texto de cada post enviados ao GPT

# FALLBACK DE JANELA (2026-08-17) REMOVIDO em 2026-08-24, junto com
# MIN_POSTS_JANELA, que era o gatilho dele. Ele relia a mesma lista mais para
# trás — 8h, 12h, 24h, 48h — quando a janela vinha pobre de posts ou de clipes.
#
# Saiu porque JANELA_HORAS virou TETO DURO de quanto conteúdo do X entra em cada
# vídeo (8h no Short, 48h no longo, pedido do usuário), e porque a premissa que
# o justificava era falsa: "alargar não custa mais na X API" ignorava que cada
# etapa REFAZ a leitura inteira, e a leitura é paga por post — com
# X_MAX_POSTS=50, uma execução azarada gastava 200. Ver `coletar_trends`.
#
# E a JANELA DA LISTA saiu inteira em 2026-08-25: ver o topo do módulo. O que
# restou aqui como teto é X_MAX_POSTS, que é o que o X de fato cobra.
#
# JANELA PRÓPRIA DA BUSCA ABERTA (2026-08-17) REMOVIDA no mesmo dia. Ela
# alargava a busca por clipes para no mínimo 24h, argumentando que ali não se
# procura pauta e sim imagem de um assunto já escolhido. JANELA_HORAS passou a
# ser teto duro de conteúdo do X por vídeo, e a busca não é exceção. Na prática
# nada muda: ela só roda no formato longo, que usa 48h.


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
    # DURAÇÃO de cada clipe, em segundos (2026-08-28). Vem de
    # `media.fields=duration_ms` no MESMO envelope da coleta, sem chamada nem
    # custo extra — e é o que permite ao Short escolher a pauta já sabendo se o
    # clipe cabe no teto de CURTO_MAX_DUR_CLIPE e se sobra material para a
    # narração inteira. `animated_gif` costuma vir SEM o campo: duração
    # desconhecida é None, e None nunca veta (só não conta como material).
    dur_midia = {
        m.get("media_key"): (
            float(m["duration_ms"]) / 1000.0
            if isinstance(m.get("duration_ms"), (int, float))
            else None
        )
        for m in includes.get("media") or []
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
        repost = False
        for ref in post.get("referenced_tweets") or []:
            if ref.get("type") != "retweeted":
                continue
            repost = True
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
        chaves_video = [
            c for c in chaves if tipo_midia.get(c) in ("video", "animated_gif")
        ]
        tem_video = bool(chaves_video)
        # Durações dos clipes DESTE post, sem os desconhecidos. Quem filtra por
        # teto olha a mais CURTA (basta um clipe caber) e quem soma material
        # para a narração usa a mais LONGA — as duas leituras saem daqui.
        durs = [d for c in chaves_video if (d := dur_midia.get(c)) is not None]
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
                # Duração dos clipes do post, em segundos. Lista vazia quando o
                # X não informou (GIF animado, em geral).
                "dur_videos_s": durs,
                # Repost. A LISTA DESCARTA (2026-08-25, pedido do usuário): a
                # casca do repost gastava uma das 50 vagas do teto sem entregar
                # nada — não traz `attachments` (o clipe fica invisível) e o
                # texto vem truncado em "RT @fulano: …". A BUSCA não usa esta
                # marca: lá o repost já virou o post original logo acima, com
                # texto íntegro e mídia, que é o material que ela existe para
                # achar.
                "repost": repost,
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
                "media.fields": "type,duration_ms",
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


AUTHORIZE_URL = "https://x.com/i/oauth2/authorize"
# Escopos que o pipeline precisa, e por quê cada um:
#   tweet.read     — ler os posts (lista, curtidas, busca)
#   users.read     — /2/users/me e a expansão de autor (o @ do crédito na tela)
#   list.read      — /2/lists/{id}/tweets, o fallback da pauta
#   like.read      — /2/users/:id/liked_tweets, a fonte primária desde 2026-08-28
#   offline.access — sem ele o X NÃO devolve refresh token, e a autorização
#                    valeria 2 horas em vez de indefinidamente
ESCOPOS_X = "tweet.read users.read list.read like.read offline.access"
# O callback JÁ CADASTRADO no app (conferido no painel em 2026-08-28, na aba
# Settings > Authentication settings do app 33042480). Lá existem dois:
# `https://localhost:8080/callback` e `http://localhost:8080/callback`. Este
# código usa o **http**, que é o que um servidor local serve sem certificado —
# o https exigiria um certificado autoassinado e um aviso do navegador no meio
# da autorização, sem ganho nenhum para um redirect que não sai da máquina.
#
# A porta é FIXA, ao contrário do fluxo do YouTube, que sorteia uma. O X faz
# EXACT MATCH do redirect_uri contra os Callback URLs cadastrados (conferido na
# doc oficial), então porta sorteada seria rejeitada em toda tentativa. O
# caminho `/callback` também faz parte da correspondência — o handler aceita
# qualquer path, mas o X só redireciona para este.
REDIRECT_PADRAO = "http://localhost:8080/callback"
# Espera pelo redirect do navegador, em segundos. Passado isso o comando
# devolve o terminal em vez de ficar pendurado segurando a porta.
ESPERA_AUTORIZACAO_S = 300


def autorizar_x(cfg: Config) -> None:
    """Autoriza o app do X no navegador e distribui os tokens; modo `--auth-x`.

    Existe desde 2026-08-28. Até aqui a autorização do X era feita À MÃO — o
    README dizia "reautorize no navegador" e não havia nada que fizesse isso,
    ao contrário do YouTube, que tem `--auth-youtube` desde sempre. A conta
    dessa falta veio junto com as CURTIDAS: elas exigem o escopo `like.read`,
    que o token em produção não tinha, e o caminho para consertar era montar o
    PKCE do X na unha.

    E ESCOPO NÃO SE CONSERTA NO PAINEL. Ligar `like.read` nas configurações do
    app não altera token JÁ EMITIDO: os escopos são gravados no token no
    momento da autorização. Foi exatamente o que se mediu em 28/08 — com
    `like.read` ativado no app, `/2/users/me` respondia 200 e
    `/2/users/:id/liked_tweets` respondia 403 com o mesmo token. Só uma
    autorização NOVA carrega o escopo novo, e é isto aqui.

    O que este modo faz, em ordem:

    1. sobe um servidor local no `redirect_uri` (porta FIXA — o X faz exact
       match contra os Callback URLs do app) e abre o navegador;
    2. troca o código por access + refresh, com PKCE S256;
    3. IMPRIME OS ESCOPOS CONCEDIDOS. É a única forma de ver o que o token de
       fato carrega — o token do X é opaco e não há endpoint de introspecção;
    4. grava refresh, access e vencimento no serviço do cron renovador, que é
       de onde todos os crons leem em tempo de execução (ver `_ler_do_render`).

    Roda LOCALMENTE, não em cron: ele depende de um navegador.
    """
    # AS CREDENCIAIS PODEM VIR DO RENDER, e não só do .env local (2026-08-28).
    # Este comando roda na MÁQUINA, mas o pipeline mora no Render: o .env local
    # de quem opera pelos crons envelhece sem que isso atrapalhe nada — o do
    # usuário estava parado numa versão que ainda tinha Firecrawl e Zernio,
    # removidos em 16/08. Exigir que ele fosse atualizado à mão para autorizar
    # seria pedir que os segredos fossem copiados para o disco sem necessidade.
    #
    # É a mesma fonte da verdade que `_ler_do_render` já usa para o token: o
    # serviço do cron renovador. Com RENDER_API_KEY e RENDER_TOKEN_SERVICE_ID
    # em mãos, o resto se resolve sozinho.
    cliente_id = cfg.x_oauth_client_id or _ler_do_render(cfg, "X_OAUTH_CLIENT_ID")
    cliente_secret = cfg.x_oauth_client_secret or _ler_do_render(
        cfg, "X_OAUTH_CLIENT_SECRET"
    )
    if cliente_id and not cfg.x_oauth_client_id:
        print("[x-auth] Credenciais OAuth lidas do serviço do renovador no Render.")
    if not (cliente_id and cliente_secret):
        raise SystemExit(
            "Sem X_OAUTH_CLIENT_ID/X_OAUTH_CLIENT_SECRET não dá para "
            "autorizar, e não deu para lê-los no Render.\n"
            "Ou preencha os dois no .env (developer.x.com > seu app > Keys and "
            "tokens > OAuth 2.0 Client ID and Client Secret), ou passe "
            "RENDER_API_KEY e RENDER_TOKEN_SERVICE_ID para este comando ler as "
            "credenciais do serviço do cron renovador."
        )
    cfg = copy(cfg)
    cfg.x_oauth_client_id = cliente_id
    cfg.x_oauth_client_secret = cliente_secret

    redirect_uri = (
        os.getenv("X_OAUTH_REDIRECT_URI", "").strip() or REDIRECT_PADRAO
    )
    partes = urllib.parse.urlparse(redirect_uri)
    porta = partes.port or (443 if partes.scheme == "https" else 80)

    # PKCE: o verifier é o segredo, o challenge é o hash dele que vai na URL.
    verifier = base64.urlsafe_b64encode(os.urandom(64)).decode().rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    estado = base64.urlsafe_b64encode(os.urandom(24)).decode().rstrip("=")

    recebido: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 — assinatura da stdlib
            consulta = urllib.parse.urlparse(self.path).query
            for chave, valor in urllib.parse.parse_qsl(consulta):
                recebido[chave] = valor
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            ok = "code" in recebido
            self.wfile.write(
                (
                    "<h2>Autorização concluída.</h2><p>Pode fechar esta aba e "
                    "voltar ao terminal.</p>"
                    if ok
                    else "<h2>Autorização recusada.</h2><p>Volte ao terminal.</p>"
                ).encode("utf-8")
            )

        def log_message(self, *_args) -> None:  # silencia o log do servidor
            pass

    try:
        servidor = http.server.HTTPServer((partes.hostname or "localhost", porta), Handler)
    except OSError as erro:
        raise SystemExit(
            f"Não deu para escutar em {redirect_uri} ({erro}). A porta precisa "
            "estar livre e o endereço tem que ser EXATAMENTE um dos Callback "
            "URLs do app no developer.x.com — o X não aceita porta diferente."
        ) from erro

    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": cfg.x_oauth_client_id,
            "redirect_uri": redirect_uri,
            "scope": ESCOPOS_X,
            "state": estado,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    print(
        f"[x-auth] Callback: {redirect_uri} (precisa estar entre os Callback "
        "URIs do app no developer.x.com — o X exige correspondência exata).\n"
        f"[x-auth] Escopos pedidos: {ESCOPOS_X}\n"
        "[x-auth] Abrindo o navegador para autorização..."
    )
    print(f"  Se não abrir, acesse manualmente:\n  {url}\n")
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    # TIMEOUT (2026-08-28): sem ele `handle_request` espera para SEMPRE. Fechar
    # a aba sem autorizar não devolve o terminal e o processo fica pendurado
    # segurando a porta — foi o que aconteceu na primeira execução deste
    # código. O fluxo do YouTube tem o mesmo defeito; aqui ele não se repete.
    servidor.timeout = ESPERA_AUTORIZACAO_S
    servidor.handle_request()  # aguarda o redirect com o código
    servidor.server_close()
    if not recebido:
        raise SystemExit(
            f"Ninguém voltou do navegador em {ESPERA_AUTORIZACAO_S // 60} "
            "minutos. Se a página do X nem chegou a abrir, confira se "
            f"{redirect_uri} está cadastrado como Callback URI do app: o X "
            "recusa a autorização ANTES de redirecionar quando ele não bate, "
            "e aí nada volta para cá."
        )

    if recebido.get("error"):
        raise SystemExit(
            f"O X recusou a autorização: {recebido['error']} "
            f"({recebido.get('error_description', 'sem detalhe')})."
        )
    if recebido.get("state") != estado or not recebido.get("code"):
        raise SystemExit("Autorização inválida (state divergente ou código ausente).")

    resp = requests.post(
        OAUTH2_TOKEN_ENDPOINT,
        auth=(cfg.x_oauth_client_id, cfg.x_oauth_client_secret),
        data={
            "grant_type": "authorization_code",
            "code": recebido["code"],
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": cfg.x_oauth_client_id,
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise SystemExit(
            f"Troca do código pelo token falhou ({resp.status_code}): "
            f"{resp.text[:300]}"
        )
    dados = resp.json()
    refresh = dados.get("refresh_token")
    access = dados.get("access_token")
    if not (refresh and access):
        raise SystemExit(
            "O X não devolveu refresh_token. Confira se `offline.access` está "
            "entre os escopos do app — sem ele a autorização vale 2 horas."
        )

    # OS ESCOPOS CONCEDIDOS, que é a informação que não existia em lugar nenhum
    # e cuja falta custou a rodada de depuração de 28/08. Ele vem do X, não do
    # que pedimos: se o app não tiver um escopo habilitado, ele some daqui.
    concedidos = (dados.get("scope") or "").split()
    print(f"[x-auth] Escopos CONCEDIDOS pelo X: {' '.join(concedidos) or '(nenhum)'}")
    faltando = [e for e in ESCOPOS_X.split() if e not in concedidos]
    if faltando:
        print(
            f"[x-auth] ATENÇÃO: faltou {', '.join(faltando)}. Habilite no app "
            "(developer.x.com > User authentication settings) e rode de novo — "
            "sem `like.read` a pauta continua saindo da lista, e sem "
            "`list.read` o fallback morre."
        )

    # Ordem igual à do renovador: o refresh primeiro (é o que custa uma
    # reautorização manual se perder), depois o access, e o vencimento por
    # último — data nova apontando para token velho é a mentira que reabre a
    # janela morta (ver `renovar_token_do_x`).
    try:
        ARQUIVO_REFRESH.write_text(refresh, encoding="utf-8")
    except OSError as erro:
        print(f"[aviso] não deu para gravar o refresh em disco: {erro}")

    if not (cfg.render_api_key and cfg.render_token_service_id):
        print(
            "\n[x-auth] Sem RENDER_API_KEY/RENDER_TOKEN_SERVICE_ID no .env: os "
            "tokens NÃO foram enviados ao Render. Grave à mão no serviço do "
            "cron renovador:\n"
            "  X_OAUTH_REFRESH_TOKEN, X_OAUTH_ACCESS_TOKEN e "
            "X_OAUTH_ACCESS_TOKEN_EXPIRA\n"
            f"  (o refresh ficou salvo em {ARQUIVO_REFRESH})"
        )
        return

    ok_refresh = _gravar_no_render(cfg, "X_OAUTH_REFRESH_TOKEN", refresh)
    ok_access = _gravar_no_render(cfg, "X_OAUTH_ACCESS_TOKEN", access)
    segundos = int(dados.get("expires_in") or 0)
    ok_expira = True
    if segundos > 60:
        vence = datetime.now(timezone.utc) + timedelta(seconds=segundos - 60)
        ok_expira = _gravar_no_render(
            cfg, CHAVE_EXPIRA, vence.isoformat(timespec="seconds")
        )
    if ok_refresh and ok_access and ok_expira:
        print(
            "[x-auth] Tokens gravados no serviço do cron renovador. Os crons "
            "de vídeo leem de lá em tempo de execução — nada a deployar."
        )
    else:
        print(
            "[aviso] Nem tudo foi gravado no Render (refresh="
            f"{ok_refresh}, access={ok_access}, vencimento={ok_expira}). "
            "Confira as env vars do serviço do renovador à mão."
        )


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
    # ESCOPOS CONCEDIDOS no log (2026-08-28). O token do X é opaco e não há
    # endpoint de introspecção: a renovação é o ÚNICO lugar em que dá para ver
    # o que ele carrega. A falta disso custou uma rodada inteira de depuração —
    # `like.read` estava ativado no app, o token emitido antes não o tinha, e o
    # sintoma era um 403 mudo só nas curtidas, com /2/users/me respondendo 200.
    # Escopo não se conserta no painel: só uma autorização nova (`--auth-x`).
    escopos = (dados.get("scope") or "").split()
    if escopos:
        falta = "" if "like.read" in escopos else "  (SEM like.read: a pauta sai da lista, não das curtidas)"
        print(f"[x] Escopos do token: {' '.join(escopos)}{falta}")
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


def _teto_de_clipe(cfg: Config) -> float | None:
    """Duração máxima do clipe da pauta, em segundos; None quando não há teto.

    SÓ O SHORT tem teto (2026-08-28, pedido do usuário: "para vídeos curtos, só
    escolha vídeos que tenham até 30 segundos no máximo"). Ele anda de par com
    o fim do loop na montagem: sem repetir clipe, quem decide o tamanho do
    vídeo é o material, e um clipe de 4 minutos não é material melhor que um de
    25 segundos — é um clipe do qual só se usa o começo. O formato longo segue
    sem teto: lá cada pauta ocupa uma parte inteira e clipe comprido é ganho.
    """
    return float(cfg.curto_max_dur_clipe_s) if cfg.formato == "curto" else None


# Id numérico de um post do X dentro de uma URL. Mesmo desenho do padrão de
# midia_x.py (que não é importado aqui: midia_x importa ESTE módulo, e a volta
# fecharia o ciclo). Casa tanto x.com quanto twitter.com porque a descrição
# publicada guarda o link como ele foi montado na época.
PADRAO_ID_POST = re.compile(r"(?:x|twitter)\.com/[^/\s]+/status/(\d+)")


def posts_ja_usados(videos_publicados: list[dict] | None) -> set[str]:
    """Ids dos posts do X que JÁ viraram vídeo, lidos das descrições publicadas.

    É a metade que faltava do desenho das curtidas (2026-08-28): a coleta lê as
    `x_max_posts` curtidas mais recentes e nada as consumia, então o mesmo post
    disputava a pauta em toda execução até sair de novo. Em 2026-08-30 o laser
    de matar mosquito saiu duas vezes no canal BR — as duas execuções estavam
    fora da janela de JANELA_REPETICAO_HORAS, que é o único veto que existia, e
    ele julga SEMÂNTICA (o mesmo fato contado de outro jeito) por LLM, não
    identidade do material.

    O registro é a DESCRIÇÃO PUBLICADA, pelo desenho do usuário ("esgotar os
    vídeos curtidos pela descrição dos nossos vídeos"), e não um arquivo: o
    disco do Render é efêmero, `videos.txt` morre com o contêiner e não há
    banco. A descrição, ao contrário, é escrita pelo próprio pipeline
    (`seo.montar_descricao`), fica no YouTube e volta de graça em
    `youtube.ultimos_publicados`, que TODA execução já lê antes de gastar um
    centavo com o X.

    O alcance da memória é o dessa leitura — os 100 últimos vídeos do canal
    dentro de DIAS_REFERENCIA. Ele é maior que o pool de curtidas (as 100 mais
    recentes), então um post só escapa se tiver sido usado antes disso e
    continuar entre as 100 curtidas mais novas — caso em que o post é velho e a
    curtida também.

    Compara por ID e não por URL porque o @ do autor pode mudar (e muda quando
    um repost é resolvido para o post original na coleta).
    """
    ids: set[str] = set()
    for video in videos_publicados or []:
        ids.update(PADRAO_ID_POST.findall(video.get("descricao") or ""))
    return ids


def _filtrar_posts(
    cfg: Config,
    lote: list[dict],
    contas_vetadas: set[str],
    contagem: dict[str, int],
    ja_usados: set[str] | None = None,
) -> list[dict]:
    """Aplica a TODA fonte de pauta os mesmos cortes; muta `contagem` com os motivos.

    Existe desde 2026-08-28, quando a coleta ganhou uma segunda fonte (as
    CURTIDAS). Duplicar o filtro em cada uma delas seria escrever duas vezes a
    regra do canal e descobrir a divergência num vídeo publicado — as curtidas
    e a lista precisam produzir a MESMA pauta elegível, que é o que o pedido
    diz ("o mesmo módulo e modelo de pautas" para os dois formatos).

    Os cortes, na ordem:

    0. JÁ USADO: o post já aparece nas fontes de um vídeo publicado. É o
       primeiro porque é o único corte que não depende de nada do post — ver
       `posts_ja_usados`. Sem ele a curtida nunca era CONSUMIDA e voltava à
       disputa em toda execução.
    1. CONTA VETADA (CONTAS_VETADAS): quem só publica recorte de emissora.
    2. REPOST: casca sem `attachments` e com o texto truncado em "RT @fulano:".
    3. SEM CLIPE: o vídeo do canal é montado só com clipe do X.
    4. CLIPE LONGO DEMAIS: só no Short, ver `_teto_de_clipe`.

    O que NÃO está aqui, de propósito: TIPO DE MATERIAL e MACROTEMA, os outros
    dois filtros pedidos junto com este. Os dois já existem no pipeline e custam
    o que não se pode pagar nesta camada — o tipo (slide, screenshot, gravação
    de tela) é a visão do GPT sobre frames do clipe (triagem.py roda ANTES da
    escolha da pauta, auditoria.py dá a palavra final), e macrotema é uma chamada de LLM sobre a trend já formada
    (classificacao.py, com o corte em main.py). Rodar visão sobre os 100 posts
    lidos aqui custaria mais que o vídeo inteiro para decidir a mesma coisa que
    já se decide adiante, de graça.
    """
    teto = _teto_de_clipe(cfg)
    usados = ja_usados or set()
    aprovados = []
    for post in lote:
        id_post = PADRAO_ID_POST.search(post["url"])
        if id_post and id_post.group(1) in usados:
            contagem["ja_usado"] = contagem.get("ja_usado", 0) + 1
            continue
        if post["usuario"].lower() in contas_vetadas:
            contagem["conta_vetada"] = contagem.get("conta_vetada", 0) + 1
            continue
        if post.get("repost"):
            contagem["repost"] = contagem.get("repost", 0) + 1
            continue
        if not post.get("video"):
            contagem["sem_clipe"] = contagem.get("sem_clipe", 0) + 1
            continue
        if teto is not None:
            durs = post.get("dur_videos_s") or []
            # Basta UM clipe do post caber: o post pode trazer o corte de 20s e
            # a íntegra de 6 minutos, e é o de 20s que o Short vai usar.
            # Duração desconhecida (GIF animado) não veta — ver `_normalizar_posts`.
            if durs and min(durs) > teto:
                contagem["clipe_longo"] = contagem.get("clipe_longo", 0) + 1
                continue
        aprovados.append(post)
    return aprovados


def _id_do_usuario(cfg: Config, token: str) -> str:
    """Id numérico do dono do token; "" quando não dá para descobrir.

    `/2/users/:id/liked_tweets` não aceita "me" no lugar do id (ao contrário de
    `/2/users/me`), então esta chamada é obrigatória antes de ler as curtidas.
    Ela não pesa no orçamento: o X cobra por POST lido, e aqui não vem nenhum.
    """
    if CACHE_TOKEN_USUARIO.get("user_id"):
        return CACHE_TOKEN_USUARIO["user_id"]
    try:
        dados = _get(token, ME_ENDPOINT, {})
    except requests.RequestException as erro:
        print(f"[aviso] X API: não deu para identificar o dono do token ({erro})")
        return ""
    uid = ((dados.get("data") or {}).get("id") or "").strip()
    CACHE_TOKEN_USUARIO["user_id"] = uid
    return uid


def _coletar_curtidos(
    cfg: Config, ja_usados: set[str] | None = None
) -> tuple[list[dict], bool]:
    """(posts curtidos já filtrados, houve falha de leitura).

    A segunda posição é o que faz a lista assumir mesmo quando a contagem
    passaria pelo piso: QUALQUER erro na leitura das curtidas manda a execução
    para o fallback (2026-08-29, pedido do usuário: "qualquer erro ou filtro
    nos likedposts, fallback para a lista"). Antes, um 403 depois de 60 posts
    lidos devolvia esses 60 e a execução seguia como se a fonte estivesse
    inteira.

    FONTE PRIMÁRIA DA PAUTA desde 2026-08-28. A lista do X continua atrás,
    como fallback — ver `coletar_trends`.

    SEM RECORTE DE DATA desde 2026-08-29 (pedido do usuário: "remover o limite
    de 1 semana"). O que entra são as `x_max_posts` curtidas mais recentes,
    quaisquer que sejam as datas dos posts. Só quando ELAS acabarem — o
    histórico inteiro cabe abaixo do teto de leitura e a paginação termina sem
    `next_token` — é que a lista assume, que é o desenho pedido: "esgotar todos
    os posts que eu dei like, e então passar para a lista".

    E ESGOTAR AGORA ESGOTA MESMO (2026-08-30): `ja_usados` tira daqui a curtida
    que já virou vídeo, lida das descrições publicadas. Até então "acabar" só
    podia significar acabar a PAGINAÇÃO — o X devolve sempre as 100 curtidas
    mais recentes, a leitura não guarda nada entre execuções e o disco do
    Render é efêmero, então o mesmo post curtido voltava à disputa três vezes
    por dia, todo dia, até ser escolhido de novo. Ver `posts_ja_usados`.

    A troca tem uma razão de qualidade e uma de custo. A lista entrega o que os
    membros publicaram, e o filtro de clipe descarta a maior parte disso depois
    de PAGO (a linha "[x] lista:" costuma mostrar 100 lidos para uma dúzia com
    vídeo). A curtida é um sinal que o usuário já emite de graça, e emite
    justamente sobre o post que quis guardar: o mesmo orçamento de leitura
    passa a comprar material escolhido a mão em vez de timeline bruta.

    O QUE A API NÃO DÁ, e como isto lida com a falta:

    - QUANDO a curtida aconteceu. O endpoint devolve só o post curtido. O que
      sobra é a ORDEM — o X entrega da curtida mais recente para a mais antiga
      —, e é ela que faz aqui o papel de recorte: ler as `x_max_posts`
      primeiras É "o que curti por último". Foi essa propriedade que aposentou
      a janela de dias em 2026-08-29: com a ordem sendo de curtida, filtrar
      pela DATA DO POST não recortava o que o usuário quis dizer (post antigo
      curtido hoje é curadoria de hoje) e ainda descartava ~17% do que já fora
      pago.
    - `start_time`. Confirmado no OpenAPI: o endpoint aceita `max_results` e
      `pagination_token` e nada de tempo. Qualquer recorte por data seria
      DEPOIS da leitura, sem economizar um centavo — quem limita o gasto aqui é
      `x_max_posts`, igual à lista.
    - Ordem por DATA DO POST. Como a ordem é de CURTIDA, as datas vêm
      embaralhadas. Sem janela isso deixou de importar: o laço para no
      orçamento ou quando as curtidas acabam.

    Falhar aqui NÃO aborta, ao contrário da lista: este é o caminho com
    fallback, por desenho do usuário. 403 é o caso mais provável na estreia — o
    escopo `like.read` precisa estar no token, e token autorizado antes desta
    mudança não o tem.
    """
    if not cfg.x_curtidos:
        return [], False
    token = _token_de_usuario(cfg)
    if not token:
        print(
            "[aviso] Sem access token de USUÁRIO do X; as curtidas exigem "
            "contexto de usuário (escopo like.read). Caindo para a lista."
        )
        return [], True
    uid = _id_do_usuario(cfg, token)
    if not uid:
        return [], True

    posts: list[dict] = []
    lidos = 0
    contagem: dict[str, int] = {}
    vetadas = {c.lower() for c in (cfg.contas_vetadas or [])}
    falhou = False
    pagina = None
    while lidos < cfg.x_max_posts:
        params = {
            "max_results": min(100, max(cfg.x_max_posts - lidos, 5)),
            "tweet.fields": "created_at,public_metrics,text,referenced_tweets",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username",
            "media.fields": "type,duration_ms",
        }
        if pagina:
            params["pagination_token"] = pagina
        try:
            dados = _get(token, LIKED_TWEETS_ENDPOINT.format(id=uid), params)
        except requests.RequestException as erro:
            # SEM SystemExit: esta fonte tem fallback. O que já veio é aproveitado.
            print(
                f"[aviso] X API: leitura das curtidas parou ({erro}). 403 aqui "
                "é o escopo `like.read` faltando no token — reautorize no "
                "navegador pedindo `like.read` junto dos escopos atuais. "
                "Seguindo para a lista com o que já veio."
            )
            falhou = True
            break
        lote = _normalizar_posts(dados)
        if not lote:
            break
        lidos += len(lote)
        posts.extend(_filtrar_posts(cfg, lote, vetadas, contagem, ja_usados))
        pagina = (dados.get("meta") or {}).get("next_token")
        if not pagina:
            break

    if lidos:
        detalhe = ", ".join(
            f"{n} {rotulo}"
            for rotulo, n in (
                ("já publicados por nós", contagem.get("ja_usado", 0)),
                ("repost", contagem.get("repost", 0)),
                ("sem mídia nativa", contagem.get("sem_clipe", 0)),
                (
                    f"clipe acima de {cfg.curto_max_dur_clipe_s}s",
                    contagem.get("clipe_longo", 0),
                ),
                ("de conta vetada", contagem.get("conta_vetada", 0)),
            )
            if n
        )
        print(
            f"[x] curtidas: {lidos} posts lidos na X API, {len(posts)} "
            "aproveitáveis" + (f" (descartados: {detalhe})" if detalhe else "")
        )
    return posts, falhou


def _coletar_da_lista(
    cfg: Config, token: str, ja_usados: set[str] | None = None
) -> list[dict]:
    """Posts dos membros da LISTA (X_LIST_ID), cronológicos, numa chamada só.

    Substitui inteira a mecânica de `search/recent` com `from:`: lá as 162
    contas não cabiam numa query de 512 caracteres, viravam 7 lotes, e o teto de
    leitura era repartido entre eles — 28 posts para 25 contas, escolhidos por
    RELEVÂNCIA. O efeito medido em 2026-08-17 foi conta ativa sumir da coleta
    (@sentdefender publicou 12 vezes em 24h e apareceu zero vez). A lista não
    tem nada disso: é a timeline dos membros, em ordem de publicação.

    UMA CHAMADA, os `x_max_posts` posts MAIS RECENTES da lista (100 é o teto
    da X API por chamada e é o valor em produção desde 2026-08-25). Não há
    filtro de data: a v2 não oferece um no endpoint de lista, e recortar por
    janela depois da resposta seria descartar post já pago. A recência sai de
    graça da ordem cronológica reversa — os 100 primeiros SÃO os 100 mais
    novos. Se a lista estiver parada, entra post mais velho; é material, não
    defeito, e a data de cada post vai no prompt do curador.

    SÓ POST COM CLIPE SOBE (2026-08-25, pedido do usuário). O endpoint de lista
    NÃO filtra mídia no servidor: a v2 não tem parâmetro para isso, então o
    filtro é aqui, no envelope que já veio — `expansions=attachments.media_keys`
    + `media.fields=type`, e fica quem tem `video` ou `animated_gif`. Junto sai
    o REPOST, que é casca: a X API não manda `attachments` nele (o clipe mora no
    post original) nem o texto inteiro, só "RT @fulano: …".

    O TETO `x_max_posts` CONTA POST LIDO, não post aprovado — é assim que o X
    cobra (US$ 0,005 cada). Filtrar por vídeo e continuar paginando até somar
    100 APROVADOS seria ler 400-1000 posts por vídeo, porque clipe nativo é
    minoria na timeline; o custo do Short iria a US$ 2-5. Com o teto na
    leitura, a conta é fixa: 100 posts lidos, US$ 0,50, e o que vier de clipe
    dentro deles é o material do vídeo.
    """
    posts: list[dict] = []
    lidos = 0  # posts que a X API devolveu — é por eles que o X cobra
    contagem: dict[str, int] = {}
    # Lista PRIVADA exige contexto de usuário; na pública o app-only basta.
    token = _token_de_usuario(cfg) or token
    vetadas = {c.lower() for c in (cfg.contas_vetadas or [])}
    pagina = None
    while lidos < cfg.x_max_posts:
        params = {
            "max_results": min(100, max(cfg.x_max_posts - lidos, 10)),
            # `referenced_tweets` é o que revela o REPOST, para descartá-lo
            # abaixo. As expansões do post ORIGINAL (que a busca pede) ficam
            # de fora de propósito: aqui o repost não é resolvido, é jogado
            # fora, então trazer o original só engordaria o envelope.
            "tweet.fields": "created_at,public_metrics,text,referenced_tweets",
            "expansions": "author_id,attachments.media_keys",
            "user.fields": "username",
            "media.fields": "type,duration_ms",
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
        lidos += len(lote)
        # Os cortes (conta vetada, repost, sem clipe, clipe longo demais no
        # Short) moram em `_filtrar_posts` desde 2026-08-28: as CURTIDAS
        # passaram a ser a fonte primária da pauta, e as duas fontes precisam
        # produzir a mesma pauta elegível.
        posts.extend(_filtrar_posts(cfg, lote, vetadas, contagem, ja_usados))
        pagina = (dados.get("meta") or {}).get("next_token")
        if not pagina:
            break
    detalhe = ", ".join(
        f"{n} {rotulo}"
        for rotulo, n in (
            ("já publicados por nós", contagem.get("ja_usado", 0)),
            ("repost", contagem.get("repost", 0)),
            ("sem mídia nativa", contagem.get("sem_clipe", 0)),
            (
                f"clipe acima de {cfg.curto_max_dur_clipe_s}s",
                contagem.get("clipe_longo", 0),
            ),
            ("de conta vetada", contagem.get("conta_vetada", 0)),
        )
        if n
    )
    print(
        f"[x] lista: {lidos} posts lidos na X API, {len(posts)} aproveitáveis"
        + (f" (descartados: {detalhe})" if detalhe else "")
    )
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
    # A janela é a MESMA da coleta desde 2026-08-24: JANELA_HORAS é teto duro
    # de conteúdo do X por vídeo, e a busca não é exceção (ver o topo do
    # módulo). Como ela só roda no formato longo, isto significa 48h — mais que
    # as 24h da janela própria que ela tinha.
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)

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


def _listar_posts(posts: list[dict], teto: float | None = None) -> str:
    linhas = []
    for p in posts:
        texto = " ".join(p["texto"].split())[:MAX_TEXTO_POST]
        # A DURAÇÃO do clipe entra na linha desde 2026-08-28: o Short deixou de
        # repetir clipe em loop, então o tamanho do material é o tamanho do
        # vídeo, e o curador precisa enxergar isso para não concentrar a trend
        # em posts de clipe curto.
        #
        # A duração anunciada respeita o TETO do formato: um post com um corte
        # de 20s e a íntegra de 6 minutos vale 20 segundos para o Short, não
        # 360 — a íntegra nem chega a ser baixada (ver `_baixar_midias` em
        # midia_x.py), e anunciá-la faria o curador achar que a trend tem
        # material que ela não vai ter.
        cabem = [
            d for d in (p.get("dur_videos_s") or [])
            if teto is None or d <= teto
        ]
        video = " | COM VÍDEO" if p.get("video") else ""
        if video and cabem:
            video += f" ({max(cabem):.0f}s)"
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

Você recebe os posts do X que o usuário curou — todos com clipe de vídeo
nativo —, com autor, data, métricas de engajamento, duração do clipe e texto.
Eles vêm dos posts que ele CURTIU ou de uma lista que ele mantém; nos dois
casos é curadoria dele, não uma amostra da rede.

A DATA DE CADA POST ESTÁ NA LINHA DELE: use-a. O recorte de janela aqui é
frouxo ou inexistente, então pauta velha pode aparecer, e o que decide o quão
quente ela está é a data que você está lendo, não a suposição de que tudo
chegou agora. Agrupe-os
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
  com vídeo, melhor. A DURAÇÃO de cada clipe está entre parênteses depois de
  "COM VÍDEO", e ela importa: o vídeo do canal NÃO repete clipe, então a soma
  dos clipes da trend é o tempo de tela que ela consegue sustentar. Entre dois
  posts igualmente centrais, prefira o de clipe mais LONGO. Nunca invente URL.
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
                + _listar_posts(posts, _teto_de_clipe(cfg)),
            },
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_TRENDS},
    )
    return json.loads(resposta.choices[0].message.content)["trends"]


def coletar_trends(
    cfg: Config,
    so_lista: bool = False,
    videos_publicados: list[dict] | None = None,
) -> tuple[list[dict], bool]:
    """(trends da pauta, a LISTA foi lida).

    DUAS FONTES, EM ORDEM (2026-08-28, desenho do usuário: "vídeos curtidos
    --fallback--> lista do X"), e as mesmas para os DOIS FORMATOS — o Short e o
    longo entram por aqui e recebem a mesma pauta elegível, com um único ajuste
    de formato (o teto de duração do clipe, que só o Short tem).

    1. `_coletar_curtidos`: as `x_max_posts` curtidas mais recentes do dono da
       conta, sem recorte de data (2026-08-29). É curadoria a mão, feita de
       graça e antes de o pipeline rodar.
    2. `_coletar_da_lista`: a lista do X (X_LIST_ID), que foi o caminho único
       entre 2026-08-22 e 2026-08-28 e continua inteira aqui embaixo.

    QUANDO O FALLBACK DISPARA (2026-08-29, pedido do usuário: "qualquer erro ou
    filtro nos likedposts, fallback para a lista"), em três gatilhos:

    - ERRO de leitura das curtidas — 403 por falta de `like.read`, rede,
      token de usuário ausente. Antes isto só derrubava a fonte quando zerava a
      contagem; agora força o fallback sozinho, mesmo com posts na mão.
    - FILTRO: as curtidas não chegam a `x_curtidos_min` posts aproveitáveis
      depois dos cortes de `_filtrar_posts` (repost, sem clipe, clipe longo
      demais, conta vetada). Um punhado de posts não forma trend, e mandar o
      GPT tirar dez trends de três posts produz pauta inventada.
    - VETO, lá na frente: quando a auditoria reprova o material de TODAS as
      candidatas tentadas, `main.py` chama esta função de novo com
      `so_lista=True` em vez de abortar. É o gatilho que faltava — o que
      derrubou as 10 execuções de 27 a 29/08 não foi escassez de post, foi
      material que não passava nos vetos, e a lista nunca chegava a ser lida.

    O piso é de posts APROVEITÁVEIS, não de posts lidos: é o material que
    chegaria ao curador. Com as duas fontes vazias a execução aborta, como
    abortava antes — o fallback é da FONTE, não da falta de pauta.

    POST QUE JÁ VIROU VÍDEO NÃO DISPUTA (2026-08-30). `videos_publicados` são
    os vídeos que `main.py` já leu do canal para a régua de audiência, e as
    descrições deles trazem os links dos posts que cada vídeo consumiu
    (`seo.montar_descricao`). `posts_ja_usados` os transforma em ids e
    `_filtrar_posts` os corta nas DUAS fontes — é isto que "esgotar as
    curtidas" queria dizer, e é o corte que faltava: a leitura das curtidas não
    tem memória nenhuma (o X devolve sempre as 100 mais recentes) e o único
    veto de repetição que existia era o semântico de 36h de
    `escritor._video_repetido`, que não alcança um post reaproveitado uma
    semana depois. Sem `videos_publicados` nada é cortado, e a coleta se
    comporta como antes.

    Com `so_lista=True` as curtidas são puladas de uma vez: é a segunda rodada
    chamada pelo laço de fallback, e reler as mesmas curtidas ali seria pagar
    de novo pelo material que acabou de ser reprovado.

    O que NÃO muda: quem paga é `x_max_posts` (o X cobra por post lido, ~US$
    0,005). Quando o fallback dispara, a execução lê as duas fontes e paga as
    duas — é o preço, conhecido, de a curadoria a mão ter a primeira palavra.
    """
    # POST QUE JÁ VIROU VÍDEO SAI DAS DUAS FONTES (2026-08-30). `ja_usados` sai
    # das descrições dos vídeos publicados, que `main.py` já leu para a régua de
    # audiência — nenhuma chamada nova, nenhum custo. É o que faz "esgotar as
    # curtidas" acontecer de verdade: sem isto a mesma curtida disputava a
    # pauta em toda execução, e o único veto de repetição era semântico e de
    # 36h (ver `escritor._video_repetido`).
    ja_usados = posts_ja_usados(videos_publicados)
    if ja_usados:
        print(
            f"[x] {len(ja_usados)} post(s) do X já usados em vídeos publicados "
            "saem da disputa nas duas fontes."
        )

    if so_lista:
        posts, falhou, precisa_lista = [], False, True
    else:
        posts, falhou = _coletar_curtidos(cfg, ja_usados)
        precisa_lista = falhou or len(posts) < cfg.x_curtidos_min

    usou_lista = False
    if precisa_lista:
        if cfg.x_curtidos and not so_lista:
            print(
                f"[x] As curtidas renderam {len(posts)} post(s) aproveitável "
                + (
                    "e a leitura falhou"
                    if falhou
                    else f"(mínimo de {cfg.x_curtidos_min})"
                )
                + "; caindo para a lista do X."
            )
        if not cfg.x_list_id:
            raise SystemExit(
                "As curtidas não deram pauta e não há X_LIST_ID para o "
                "fallback. Ou o escopo `like.read` falta no token do X (a "
                "linha de aviso acima diz se a leitura foi recusada), ou não "
                "há curtida com clipe no histórico. Preencha X_LIST_ID no "
                ".env (ou no Render) para a lista voltar a servir de fallback."
            )

        token = obter_bearer(cfg)
        if token is None:
            raise SystemExit(
                "Sem token da X API não há coleta de posts. Confira "
                "X_CONSUMER_KEY e X_CONSUMER_SECRET no .env."
            )

        print(
            f"[x] Lendo a lista {cfg.x_list_id} (os {cfg.x_max_posts} posts "
            "mais recentes, só os que têm clipe)..."
        )
        # A lista é o ÚLTIMO recurso: falhar aqui aborta, como desde
        # 2026-08-22 (ver `_coletar_da_lista`). Não há terceira fonte, e um
        # vídeo saindo de uma pauta pior sem ninguém ver é o que aquela
        # decisão existe para impedir.
        da_lista = _coletar_da_lista(cfg, token, ja_usados)
        usou_lista = True
        # As curtidas que vieram NÃO são jogadas fora: elas foram pagas e são
        # material curado. Entram na frente, e a deduplicação por URL evita que
        # um post curtido que também está na lista conte duas vezes.
        vistos = {p["url"] for p in posts}
        posts = posts + [p for p in da_lista if p["url"] not in vistos]

    if not posts:
        raise SystemExit(
            "Nenhuma das duas fontes devolveu post com clipe — e o vídeo é "
            "montado só com clipes. As linhas '[x] curtidas:' e '[x] lista:' "
            "acima dizem o que foi descartado e por quê: muito post lido e "
            "pouco clipe é fonte publicando texto em vez de vídeo; nada lido "
            "nas curtidas é escopo `like.read` ausente ou semana sem curtir; "
            "nada lido na lista é lista sem membros ou token do X vencido; "
            "tudo descartado como 'já publicados por nós' é a curadoria "
            "ESGOTADA — as curtidas do histórico já viraram vídeo, e a saída é "
            "curtir post novo."
            + (
                f" No Short entra ainda o teto de "
                f"{cfg.curto_max_dur_clipe_s}s por clipe."
                if cfg.formato == "curto"
                else ""
            )
        )

    # Todo post que chega aqui tem clipe (o filtro está em `_filtrar_posts`),
    # então a contagem é o próprio tamanho da coleta. Ela segue impressa porque
    # é O número que decide se há material: sem ela a escassez só aparecia lá na
    # frente, como "pool de 2 clipes".
    print(
        f"[x] {len(posts)} posts com clipe de vídeo nativo; resumindo as "
        "trends com o GPT..."
    )
    return _montar_trends(cfg, posts), usou_lista


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
    # MATERIAL DE VÍDEO POR POST, em segundos (2026-08-28). No Short a montagem
    # não repete mais clipe em loop, então a soma disto é o TETO de quanto
    # vídeo a pauta consegue segurar na tela — e é ela que dimensiona o roteiro
    # (ver `segundos_video` abaixo e `_alvo_do_material` em main.py).
    teto = _teto_de_clipe(cfg)
    dur_por_url: dict[str, float] = {}
    for post in posts:
        cabem = [
            d for d in (post.get("dur_videos_s") or [])
            if teto is None or d <= teto
        ]
        if cabem:
            # O mais LONGO que cabe: é o que a montagem vai preferir, e contar
            # o mais curto subestimaria o material a ponto de vetar pauta que
            # tem imagem de sobra.
            dur_por_url[post["url"]] = max(cabem)

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

        # SEGUNDOS DE VÍDEO DA TREND: a soma dos `max_clipes` clipes mais
        # longos que ela tem. É o material que pode ir à tela — os outros posts
        # com vídeo existem como folga da auditoria, não como tempo de tela,
        # porque a montagem usa no máximo `max_clipes`. Clipe de duração
        # desconhecida (GIF) não entra na soma: aqui o número existe para
        # dimensionar o roteiro, e chutar duração inflaria o alvo.
        duracoes = sorted(
            (dur_por_url[u] for u in com_video if u in dur_por_url), reverse=True
        )
        segundos = sum(duracoes[: cfg.max_clipes])
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
                # Segundos de clipe que a trend consegue pôr na tela (soma dos
                # `max_clipes` mais longos). No Short é o que decide o tamanho
                # do roteiro e o que veta a candidata sem material — ver
                # `selecionar_trend` (escritor.py).
                "segundos_video": round(segundos, 1),
                "data": t.get("data", ""),
            }
        )

    if not trends:
        raise SystemExit(
            f"Nenhuma trend identificada nos {len(posts)} posts coletados. "
            "A alavanca é X_MAX_POSTS no .env (já no teto de 100 da X API em "
            "produção) ou a própria lista no X — pôr contas que publiquem "
            "vídeo é de graça, subir o teto é decisão de gasto."
        )

    print(f"[x] {len(trends)} trends identificadas")
    return trends
