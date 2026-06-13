"""Coleta de posts recentes das contas selecionadas do X.

Usa a ferramenta X Search da xAI (via Responses API compatível com OpenAI),
o que dispensa credenciais e créditos da X API: tudo é cobrado na mesma
conta xAI usada pelo Grok Imagine.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from .config import Config

INSTRUCOES_CONTAS = """\
Use a busca no X para listar os posts e trends mais relevantes sobre tecnologia e
inteligência artificial publicados por contas de alto engajamento (sendo em português ou inglês)
ou temas que estão em alta no momento.\
"""

INSTRUCOES_TRENDING = """\
Use a busca no X para encontrar as threads e posts MAIS DISCUTIDOS da últimas horas
sobre tecnologia e inteligência artificial: anúncios de empresas, lançamentos
de modelos e produtos, pesquisas e polêmicas que estão dominando a conversa, 
startups brasileiras e internacionais, rumores, quedas de serviços e afins.
Priorize posts virais e de grande engajamento, vindos de fontes confiáveis,
usuários reconhecidos e recorrentes, ou temas altamente em discussão ou polêmicos.\
"""

FORMATO_RESPOSTA = """

Responda SOMENTE com um array JSON, sem texto antes ou depois, no formato:
[{"conta": "username", "texto": "conteúdo completo do post", "data": "YYYY-MM-DD"}]

Inclua posts, anúncios, lançamentos, notícias de maior
impacto, posts de usuários gerais com informações e insights relevantes,
e opiniões com maiores reverberações. 
Reproduza o texto dos posts fielmente, sem resumir demais.\
"""


def _extrair_json(texto: str) -> list[dict]:
    texto = texto.strip()
    # Remove cerca de código markdown, se o modelo usar
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    inicio, fim = texto.find("["), texto.rfind("]")
    if inicio == -1 or fim == -1:
        raise SystemExit(f"Resposta da X Search sem JSON reconhecível:\n{texto[:500]}")
    return json.loads(texto[inicio : fim + 1])


def coletar_tweets(cfg: Config) -> list[dict]:
    """Busca os posts das últimas N horas das contas configuradas."""
    cliente = OpenAI(api_key=cfg.xai_api_key, base_url="https://api.x.ai/v1")

    agora = datetime.now(timezone.utc)
    inicio = agora - timedelta(hours=cfg.janela_horas)

    ferramenta = {
        "type": "x_search",
        "from_date": inicio.strftime("%Y-%m-%d"),
        "to_date": agora.strftime("%Y-%m-%d"),
    }
    foco_usa = (
        "\nPriorize o que está dominando a conversa NOS ESTADOS UNIDOS: "
        "contas americanas, empresas americanas e notícias com impacto no "
        "EUA."
        if cfg.publico == "usa"
        else ""
    )
    if cfg.contas:
        ferramenta["allowed_x_handles"] = cfg.contas
        instrucoes = INSTRUCOES_CONTAS + foco_usa + FORMATO_RESPOSTA
        print(f"[x] Buscando posts de {len(cfg.contas)} contas via X Search da xAI...")
    else:
        instrucoes = INSTRUCOES_TRENDING + foco_usa + FORMATO_RESPOSTA
        print("[x] Buscando as threads de tech/AI mais discutidas do dia...")

    resposta = cliente.responses.create(
        model=cfg.search_model,
        input=[{"role": "user", "content": instrucoes}],
        tools=[ferramenta],
    )

    posts = _extrair_json(resposta.output_text)
    tweets = [
        {
            "conta": p.get("conta", ""),
            "texto": p.get("texto", ""),
            "data": p.get("data", ""),
        }
        for p in posts
        if p.get("texto")
    ]

    if not tweets:
        raise SystemExit(
            f"Nenhum post encontrado nas últimas {cfg.janela_horas}h. "
            "Aumente JANELA_HORAS no .env ou revise as contas."
        )

    print(f"[x] {len(tweets)} posts coletados")
    return tweets
