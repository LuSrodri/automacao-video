"""Coleta dos posts da lista fixa de contas do X e sumarização das trends via GPT.

Usa a X API oficial v2 em modo pay-per-use (a mesma credencial do download de
mídias em midia_x.py): coleta os posts das contas configuradas (CONTAS_PADRAO
em config.py, ou X_ACCOUNTS no .env) na janela configurada via
/2/tweets/search/recent. Como a leitura é cobrada por post (~US$ 0,005 cada),
X_MAX_POSTS limita o total lido por execução.

Os posts coletados vão para o GPT, que os agrupa nas N trends mais quentes —
notícias, lançamentos, novidades, curiosidades e tretas — no mesmo formato que
o resto do pipeline já consome (trend, resumo, num_posts, engajamento,
sentimento, apelo_visual, posts, data).
"""

import json
from datetime import datetime, timedelta, timezone

import requests
from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, RAIZ, Config

TOKEN_ENDPOINT = "https://api.x.com/oauth2/token"
SEARCH_ENDPOINT = "https://api.x.com/2/tweets/search/recent"

MAX_QUERY = 512  # limite de caracteres da query do search/recent
MAX_TEXTO_POST = 300  # caracteres do texto de cada post enviados ao GPT

# Estado da rotação de lotes entre execuções: quando X_MAX_POSTS não cobre
# todas as consultas, as execuções avançam um cursor circular em vez de
# sortear — sorteio deixava contas dias sem serem lidas no azar.
ESTADO_ROTACAO = RAIZ / ".rotacao_lotes"


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


def _lotes_de_query(contas: list[str]) -> list[str]:
    """Agrupa as contas em queries `from:a OR from:b ...` de até 512 caracteres."""
    sufixo = " -is:retweet -is:reply"
    lotes, atual = [], []
    for conta in contas:
        candidato = "(" + " OR ".join(f"from:{c}" for c in atual + [conta]) + ")"
        if atual and len(candidato) + len(sufixo) > MAX_QUERY:
            lotes.append("(" + " OR ".join(f"from:{c}" for c in atual) + ")" + sufixo)
            atual = [conta]
        else:
            atual.append(conta)
    if atual:
        lotes.append("(" + " OR ".join(f"from:{c}" for c in atual) + ")" + sufixo)
    return lotes


def _rotacionar_lotes(lotes: list[str], max_lotes: int) -> list[str]:
    """Seleciona `max_lotes` consultas avançando um cursor circular persistido.

    Garante que todas as contas sejam lidas ao longo das execuções (o sorteio
    anterior podia deixar as mesmas contas dias sem coleta).
    """
    try:
        inicio = int(ESTADO_ROTACAO.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        inicio = 0
    inicio %= len(lotes)
    escolhidos = [lotes[(inicio + k) % len(lotes)] for k in range(max_lotes)]
    try:
        ESTADO_ROTACAO.write_text(
            str((inicio + max_lotes) % len(lotes)), encoding="utf-8"
        )
    except OSError as erro:
        print(f"[aviso] Não consegui salvar o estado da rotação de lotes: {erro}")
    return escolhidos


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
                "tweet.fields": "created_at,public_metrics,text",
                "expansions": "author_id,attachments.media_keys",
                "user.fields": "username",
                "media.fields": "type",
            },
        )
    except requests.RequestException as erro:
        print(f"[aviso] X API: consulta de posts falhou ({erro}); lote pulado")
        return []

    includes = dados.get("includes") or {}
    autores = {u["id"]: u["username"] for u in includes.get("users") or []}
    # Tipo de cada mídia anexada: o formato do vídeo é montado SÓ com clipes
    # dos posts, então saber quem tem vídeo nativo orienta a curadoria e a
    # seleção (mesma chamada, nenhum custo extra).
    tipo_midia = {
        m.get("media_key"): m.get("type") for m in includes.get("media") or []
    }

    posts = []
    for post in dados.get("data") or []:
        metricas = post.get("public_metrics") or {}
        usuario = autores.get(post.get("author_id"), "")
        chaves = (post.get("attachments") or {}).get("media_keys") or []
        tem_video = any(
            tipo_midia.get(c) in ("video", "animated_gif") for c in chaves
        )
        posts.append(
            {
                "url": f"https://x.com/{usuario}/status/{post['id']}",
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


def _por_engajamento(post: dict) -> int:
    return post["likes"] + 3 * post["reposts"] + post["respostas"]


def _coletar_posts(cfg: Config, token: str, contas: list[str]) -> list[dict]:
    """Posts das contas na janela, limitados a cfg.x_max_posts (leitura é paga).

    Duas passadas sobre os mesmos lotes de contas. A primeira é a coleta
    normal, por relevância. A segunda repete as consultas com `has:videos` e
    existe porque a primeira NÃO prefere vídeo: post com clipe disputa as vagas
    do teto em pé de igualdade com texto, e as contas do canal postam muito
    mais texto — o material que o formato precisa era o que mais perdia vaga.
    A varredura é o mesmo conjunto de contas (nenhuma fonte nova entra por
    aqui), custa `x_max_posts_video` leituras a mais e pode ser desligada com
    X_MAX_POSTS_VIDEO=0.
    """
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)
    lotes = _lotes_de_query(contas)

    # Orçamento de leitura: divide o teto entre os lotes. O mínimo da API é 10
    # por chamada; se há lotes demais para o teto, um cursor circular decide
    # quais entram nesta execução (execução a execução a rotação cobre todas
    # as contas, sem depender de sorte).
    max_lotes = max(cfg.x_max_posts // 10, 1)
    if len(lotes) > max_lotes:
        print(
            f"[aviso] {len(contas)} contas geram {len(lotes)} consultas, mas "
            f"X_MAX_POSTS={cfg.x_max_posts} só cobre {max_lotes}; rotacionando "
            "quais contas entram hoje (aumente X_MAX_POSTS para cobrir todas)"
        )
        lotes = _rotacionar_lotes(lotes, max_lotes)
    por_lote = min(max(cfg.x_max_posts // len(lotes), 10), 100)

    posts: list[dict] = []
    for query in lotes:
        posts += _consultar(token, query, inicio, por_lote)

    posts.sort(key=_por_engajamento, reverse=True)
    posts = posts[: cfg.x_max_posts]

    orcamento_video = getattr(cfg, "x_max_posts_video", 0) or 0
    if orcamento_video:
        por_lote_video = min(max(orcamento_video // len(lotes), 10), 100)
        vistos = {p["url"] for p in posts}
        novos: list[dict] = []
        for query in lotes:
            # `has:videos` cobre vídeo nativo e GIF animado, que é exatamente o
            # que o pipeline consegue baixar e montar.
            for post in _consultar(
                token, f"{query} has:videos", inicio, por_lote_video
            ):
                if post["url"] not in vistos:
                    vistos.add(post["url"])
                    novos.append(post)
        novos.sort(key=_por_engajamento, reverse=True)
        novos = novos[:orcamento_video]
        if novos:
            print(
                f"[x] Varredura has:videos trouxe {len(novos)} post(s) com "
                "clipe que a coleta por relevância havia deixado de fora."
            )
        posts += novos

    return posts


def buscar_posts_com_video(cfg: Config, consulta: str) -> list[str]:
    """URLs de posts com clipe sobre o assunto, de QUALQUER conta do X.

    A coleta e a varredura `has:videos` só enxergam as contas do canal, então o
    material fica limitado ao que essas 50 contas publicaram sobre ESTE fato —
    que é o gargalo real do formato longo (vídeo não falta no X; falta vídeo
    concentrado num mesmo acontecimento). Esta busca é aberta.

    Em troca, as fontes NÃO são curadas: entra conta desconhecida, telejornal
    reempacotado e, eventualmente, material enganoso. Quem filtra depois é a
    auditoria de visão, que julga PERTINÊNCIA, não veracidade — por isso o
    orçamento aqui é modesto de propósito, e X_MAX_POSTS_BUSCA=0 desliga.

    Falha da API não aborta: devolve lista vazia e a execução segue com o
    material das contas do canal.
    """
    orcamento = getattr(cfg, "x_max_posts_busca", 0) or 0
    consulta = (consulta or "").strip()
    if not (orcamento and consulta):
        return []

    token = obter_bearer(cfg)
    if token is None:
        print("[aviso] Sem token da X API; busca aberta por clipes pulada.")
        return []

    # A língua acompanha o público: clipe legendado em outra língua na tela
    # atrapalha mais do que ajuda.
    idioma = "en" if cfg.publico == "usa" else "pt"
    query = f"({consulta}) has:videos -is:retweet -is:reply lang:{idioma}"
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)

    print(f"[midia-x] Busca aberta por clipes sobre: {consulta} ({idioma})")
    posts = _consultar(token, query, inicio, min(max(orcamento, 10), 100))
    posts = [p for p in posts if p.get("video")]
    posts.sort(key=_por_engajamento, reverse=True)
    posts = posts[:orcamento]
    print(
        f"[midia-x] Busca aberta achou {len(posts)} post(s) com clipe fora das "
        "contas do canal (fontes não curadas; a auditoria decide o que entra)."
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
Você é curador de um canal de vídeos sobre geopolítica, inteligência
(espionagem, defesa, OSINT), inteligência artificial e tecnologia. O canal
trata cada pauta em formato EXPLICATIVO — análise ou educacional: o vídeo
explica o que aconteceu e por que importa.

Você recebe os posts publicados nas últimas {horas} horas pelas contas que o
canal acompanha no X, com autor, data, métricas de engajamento e texto.
Agrupe-os nas ATÉ {n} TRENDS mais quentes: notícias, anúncios e
lançamentos, novidades, curiosidades, tretas/polêmicas, rumores, quedas de
serviço, demissões/contratações e viradas que estão dominando a conversa.
Ordene da mais quente para a menos quente, pesando engajamento (likes, reposts,
respostas) e quantos posts falam do mesmo assunto.

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
    """Posts da lista fixa de contas (X API) sumarizados em trends pelo GPT."""
    token = obter_bearer(cfg)
    if token is None:
        raise SystemExit(
            "Sem token da X API não há coleta de posts. Confira X_CONSUMER_KEY "
            "e X_CONSUMER_SECRET no .env."
        )

    contas = cfg.contas
    print(
        f"[x] Coletando até {cfg.x_max_posts} posts das últimas "
        f"{cfg.janela_horas}h de {len(contas)} contas..."
    )
    posts = _coletar_posts(cfg, token, contas)
    if not posts:
        raise SystemExit(
            f"Nenhum post encontrado nas últimas {cfg.janela_horas}h. "
            "Aumente JANELA_HORAS no .env ou revise as contas."
        )
    # Quantos posts trazem clipe é O número que decide se o formato longo tem
    # material: o vídeo é montado só com clipes, e eles precisam estar
    # concentrados num mesmo acontecimento. Sem esta linha, a escassez só
    # aparecia lá na frente, como "pool de 2 clipes".
    com_video = sum(1 for p in posts if p.get("video"))
    print(
        f"[x] {len(posts)} posts coletados ({com_video} com clipe de vídeo "
        "nativo); resumindo as trends com o GPT..."
    )

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
