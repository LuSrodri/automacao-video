"""Coleta dos posts das contas seguidas no X e sumarização das trends via GPT.

Usa a X API oficial v2 em modo pay-per-use (a mesma credencial do download de
mídias em midia_x.py): resolve o usuário de X_USERNAME, busca a lista de contas
que ele segue (com cache local em seguindo.json, renovado a cada 7 dias, para
não pagar essa leitura toda execução) e coleta os posts dessas contas na janela
configurada via /2/tweets/search/recent. Como a leitura é cobrada por post
(~US$ 0,005 cada), X_MAX_POSTS limita o total lido por execução.

Os posts coletados vão para o GPT, que os agrupa nas N trends mais quentes —
notícias, lançamentos, novidades, curiosidades e tretas — no mesmo formato que
o resto do pipeline já consome (trend, resumo, engajamento, sentimento,
apelo_visual, posts, data).
"""

import json
import random
import time
from datetime import datetime, timedelta, timezone

import requests
from openai import OpenAI

from .config import RAIZ, Config

TOKEN_ENDPOINT = "https://api.x.com/oauth2/token"
USERS_BY_USERNAME_ENDPOINT = "https://api.x.com/2/users/by/username/{username}"
FOLLOWING_ENDPOINT = "https://api.x.com/2/users/{id}/following"
SEARCH_ENDPOINT = "https://api.x.com/2/tweets/search/recent"

CACHE_SEGUINDO = RAIZ / "seguindo.json"
CACHE_SEGUINDO_DIAS = 7  # idade máxima do cache da lista de seguidos

MAX_QUERY = 512  # limite de caracteres da query do search/recent
MAX_TEXTO_POST = 300  # caracteres do texto de cada post enviados ao GPT


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


def _contas_seguidas(cfg: Config, token: str) -> list[str]:
    """Lista de @usuários que X_USERNAME segue, com cache local de alguns dias."""
    if CACHE_SEGUINDO.exists():
        try:
            cache = json.loads(CACHE_SEGUINDO.read_text(encoding="utf-8"))
            idade = time.time() - cache.get("quando", 0)
            if (
                cache.get("usuario") == cfg.x_username
                and idade < CACHE_SEGUINDO_DIAS * 86400
                and cache.get("contas")
            ):
                print(
                    f"[x] {len(cache['contas'])} contas seguidas (cache de "
                    f"{idade / 86400:.0f} dia(s))"
                )
                return cache["contas"]
        except (ValueError, OSError):
            pass

    dados = _get(
        token, USERS_BY_USERNAME_ENDPOINT.format(username=cfg.x_username), {}
    )
    id_usuario = dados["data"]["id"]

    contas: list[str] = []
    params: dict = {"max_results": 1000, "user.fields": "username"}
    while True:
        pagina = _get(token, FOLLOWING_ENDPOINT.format(id=id_usuario), params)
        contas += [u["username"] for u in pagina.get("data") or []]
        proximo = (pagina.get("meta") or {}).get("next_token")
        if not proximo:
            break
        params["pagination_token"] = proximo

    if not contas:
        raise SystemExit(
            f"A conta @{cfg.x_username} não segue ninguém no X. "
            "Siga as contas que quer acompanhar ou preencha X_ACCOUNTS no .env."
        )

    CACHE_SEGUINDO.write_text(
        json.dumps(
            {"usuario": cfg.x_username, "quando": time.time(), "contas": contas},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[x] {len(contas)} contas seguidas por @{cfg.x_username}")
    return contas


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


def _coletar_posts(cfg: Config, token: str, contas: list[str]) -> list[dict]:
    """Posts das contas na janela, limitados a cfg.x_max_posts (leitura é paga)."""
    inicio = datetime.now(timezone.utc) - timedelta(hours=cfg.janela_horas)
    lotes = _lotes_de_query(contas)

    # Orçamento de leitura: divide o teto entre os lotes. O mínimo da API é 10
    # por chamada; se há lotes demais para o teto, sorteia quais entram nesta
    # execução (dia a dia a rotação cobre todas as contas).
    max_lotes = max(cfg.x_max_posts // 10, 1)
    if len(lotes) > max_lotes:
        print(
            f"[aviso] {len(contas)} contas geram {len(lotes)} consultas, mas "
            f"X_MAX_POSTS={cfg.x_max_posts} só cobre {max_lotes}; sorteando "
            "quais contas entram hoje (aumente X_MAX_POSTS para cobrir todas)"
        )
        lotes = random.sample(lotes, max_lotes)
    por_lote = min(max(cfg.x_max_posts // len(lotes), 10), 100)

    posts: list[dict] = []
    for query in lotes:
        try:
            dados = _get(
                token,
                SEARCH_ENDPOINT,
                {
                    "query": query,
                    "max_results": por_lote,
                    "start_time": inicio.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sort_order": "relevancy",
                    "tweet.fields": "created_at,public_metrics,attachments,text",
                    "expansions": "author_id,attachments.media_keys",
                    "user.fields": "username",
                    "media.fields": "type",
                },
            )
        except requests.RequestException as erro:
            print(f"[aviso] X API: consulta de posts falhou ({erro}); lote pulado")
            continue

        includes = dados.get("includes") or {}
        autores = {u["id"]: u["username"] for u in includes.get("users") or []}
        tipos_midia = {m["media_key"]: m.get("type", "") for m in includes.get("media") or []}

        for post in dados.get("data") or []:
            metricas = post.get("public_metrics") or {}
            chaves = (post.get("attachments") or {}).get("media_keys") or []
            midias = [tipos_midia.get(k, "") for k in chaves]
            usuario = autores.get(post.get("author_id"), "")
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
                    "midia": (
                        "vídeo"
                        if any(t in ("video", "animated_gif") for t in midias)
                        else "foto" if "photo" in midias else ""
                    ),
                }
            )

    # Mais engajados primeiro; corta no teto configurado
    posts.sort(
        key=lambda p: p["likes"] + 3 * p["reposts"] + p["respostas"], reverse=True
    )
    return posts[: cfg.x_max_posts]


def _listar_posts(posts: list[dict]) -> str:
    linhas = []
    for p in posts:
        texto = " ".join(p["texto"].split())[:MAX_TEXTO_POST]
        midia = f" | mídia: {p['midia']}" if p["midia"] else ""
        linhas.append(
            f"- @{p['usuario']} | {p['data']} UTC | {p['likes']} likes, "
            f"{p['reposts']} reposts, {p['respostas']} respostas{midia}\n"
            f"  {p['url']}\n"
            f"  \"{texto}\""
        )
    return "\n".join(linhas)


INSTRUCOES_RESUMO = """\
Você é curador de um canal de vídeos curtos sobre tecnologia, inteligência
artificial, desenvolvimento de software e mercado de trabalho de TI.

Você recebe os posts publicados nas últimas {horas} horas pelas contas que o
canal acompanha no X, com autor, data, métricas de engajamento, mídia anexada e
texto. Agrupe-os nas ATÉ {n} TRENDS mais quentes: notícias, anúncios e
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
- "engajamento": uma frase sobre o quão quente está (some as métricas dos posts
  do assunto e cite quem está falando).
- "sentimento": a EMOÇÃO dominante nos posts (indignação, medo, deboche,
  euforia, ceticismo, fascínio...) e por quê — o que está movendo a conversa.
- "apelo_visual": uma frase sobre o quanto o assunto rende boas imagens reais
  (pessoas conhecidas, produtos, eventos, lugares) — alto/médio/baixo e por quê.
- "posts": até 5 URLs escolhidas SOMENTE entre as listadas acima, dos posts
  mais centrais da trend — PRIORIZE os marcados com "mídia: vídeo", depois
  "mídia: foto". Nunca invente URL.
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
                        "engajamento": {"type": "string"},
                        "sentimento": {"type": "string"},
                        "apelo_visual": {"type": "string"},
                        "posts": {"type": "array", "items": {"type": "string"}},
                        "data": {"type": "string"},
                    },
                    "required": [
                        "trend",
                        "resumo",
                        "engajamento",
                        "sentimento",
                        "apelo_visual",
                        "posts",
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
        horas=cfg.janela_horas, n=cfg.num_trends, foco_usa=foco_usa
    )

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": "Posts coletados:\n" + _listar_posts(posts)},
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_TRENDS},
    )
    return json.loads(resposta.choices[0].message.content)["trends"]


def coletar_trends(cfg: Config) -> list[dict]:
    """Posts das contas seguidas (X API) sumarizados em trends pelo GPT."""
    token = obter_bearer(cfg)
    if token is None:
        raise SystemExit(
            "Sem token da X API não há coleta de posts. Confira X_CONSUMER_KEY "
            "e X_CONSUMER_SECRET no .env."
        )

    if cfg.contas:
        contas = cfg.contas
        print(f"[x] Usando as {len(contas)} contas de X_ACCOUNTS")
    else:
        try:
            contas = _contas_seguidas(cfg, token)
        except requests.RequestException as erro:
            raise SystemExit(
                f"X API: falha ao ler as contas seguidas ({erro}). Se o seu "
                "plano não permite essa leitura, preencha X_ACCOUNTS no .env."
            )

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
    print(f"[x] {len(posts)} posts coletados; resumindo as trends com o GPT...")

    brutos = _resumir_trends(cfg, posts)
    urls_reais = {p["url"] for p in posts}
    midia_por_url = {p["url"]: p["midia"] for p in posts}

    def _midia_posts(urls: list[str]) -> str:
        """Melhor mídia disponível nos posts da trend: vídeo > foto > só texto."""
        midias = {midia_por_url.get(u, "") for u in urls}
        if "vídeo" in midias:
            return "vídeo"
        if "foto" in midias:
            return "foto"
        return "só texto"

    trends = []
    for t in brutos:
        if not (t.get("trend") and t.get("resumo")):
            continue
        # Garante que só URLs realmente coletadas seguem no pipeline
        urls = [u for u in (t.get("posts") or []) if u in urls_reais]
        trends.append(
            {
                "trend": t.get("trend", "").strip(),
                "resumo": t.get("resumo", "").strip(),
                "engajamento": t.get("engajamento", "").strip(),
                "sentimento": t.get("sentimento", "").strip(),
                "apelo_visual": t.get("apelo_visual", "").strip(),
                "posts": urls,
                "midia_posts": _midia_posts(urls),
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
