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
Use a busca no X para listar os posts mais relevantes sobre tecnologia e
inteligência artificial publicados pelas contas permitidas no período.\
"""

INSTRUCOES_TRENDING = """\
Use a busca no X para encontrar as threads e posts MAIS DISCUTIDOS do dia
sobre tecnologia e inteligência artificial: anúncios de empresas, lançamentos
de modelos e produtos, pesquisas e polêmicas que estão dominando a conversa.
Priorize posts virais e de grande engajamento, vindos de fontes confiáveis
(empresas, pesquisadores, jornalistas de tech).\
"""

FORMATO_RESPOSTA = """

Responda SOMENTE com um array JSON, sem texto antes ou depois, no formato:
[{"conta": "username", "texto": "conteúdo completo do post", "data": "YYYY-MM-DD"}]

Inclua até 20 posts, priorizando anúncios, lançamentos e notícias de maior
impacto. Reproduza o texto dos posts fielmente, sem resumir demais.\
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
    if cfg.contas:
        ferramenta["allowed_x_handles"] = cfg.contas
        instrucoes = INSTRUCOES_CONTAS + FORMATO_RESPOSTA
        print(f"[x] Buscando posts de {len(cfg.contas)} contas via X Search da xAI...")
    else:
        instrucoes = INSTRUCOES_TRENDING + FORMATO_RESPOSTA
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
