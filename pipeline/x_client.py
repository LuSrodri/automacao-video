"""Coleta das trends mais faladas do X nas últimas 24h.

Usa a ferramenta X Search da xAI (via Responses API compatível com OpenAI),
o que dispensa credenciais e créditos da X API: tudo é cobrado na mesma
conta xAI usada pelo Grok. A coleta devolve as N trends mais discutidas,
cada uma com um resumo do que está sendo dito e uma nota de apelo visual,
para o roteirista escolher a de maior chance de viralizar.
"""

import json
import re
from datetime import datetime, timedelta, timezone

from openai import OpenAI

from .config import Config

INSTRUCOES_TRENDING = """\
Use a busca no X para mapear AS {n} TRENDS MAIS FALADAS das últimas {horas} horas
sobre tecnologia, inteligência artificial, desenvolvimento de software e o
mercado de trabalho de TI: anúncios e lançamentos de empresas e modelos,
polêmicas, rumores, quedas de serviço, pesquisas, linguagens/ferramentas/
frameworks em alta ou em declínio, demissões e contratações em massa nas big
techs, salários, trabalho remoto, impacto da IA nas vagas e viradas que estão
DOMINANDO a conversa. Priorize o que tem maior volume de posts, engajamento e
reverberação, vindo de fontes confiáveis e usuários reconhecidos.\
"""

INSTRUCOES_CONTAS = """\
Use a busca no X para mapear AS {n} TRENDS MAIS FALADAS das últimas {horas} horas
sobre tecnologia, inteligência artificial, desenvolvimento de software e o
mercado de trabalho de TI nas contas indicadas. Priorize os assuntos com maior
engajamento e reverberação.\
"""

FORMATO_RESPOSTA = """

Responda SOMENTE com um array JSON com EXATAMENTE {n} objetos (ou menos, se não
houver tantas trends reais), ordenado da MAIS falada para a menos falada, no
formato:
[{{
  "trend": "nome curto e claro do assunto",
  "resumo": "2 a 4 frases explicando o que está sendo dito, com os fatos, nomes,
             empresas e números concretos que apareceram nos posts",
  "engajamento": "uma frase sobre o quão quente está (volume de posts, reações,
                  quem está comentando)",
  "sentimento": "a EMOÇÃO dominante nos posts (ex.: indignação, medo, deboche,
                 euforia, ceticismo, fascínio) e por quê — qual sentimento está
                 movendo a conversa, não só o fato",
  "apelo_visual": "uma frase sobre o quanto o assunto rende boas imagens reais
                   (pessoas conhecidas, produtos, eventos, lugares) — alto/médio/baixo
                   e por quê",
  "posts": ["até 4 URLs dos posts mais virais/centrais da trend, no formato
             https://x.com/usuario/status/ID — PRIORIZE posts com foto ou vídeo
             anexado; use somente URLs REAIS vistas na busca, nunca inventadas"],
  "data": "YYYY-MM-DD"
}}]

Reproduza os fatos com fidelidade, sem inventar. Não escreva nada antes nem
depois do array JSON.\
"""


def _extrair_json(texto: str) -> list[dict]:
    texto = texto.strip()
    # Remove cerca de código markdown, se o modelo usar
    texto = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto)
    inicio, fim = texto.find("["), texto.rfind("]")
    if inicio == -1 or fim == -1:
        raise SystemExit(f"Resposta da X Search sem JSON reconhecível:\n{texto[:500]}")
    return json.loads(texto[inicio : fim + 1])


INSTRUCOES_MIDIAS = """\
Busque no X os posts abaixo e ANALISE A MÍDIA (foto ou vídeo) anexada a cada um.

Para cada post, descreva a mídia em 2 a 4 frases OBJETIVAS: o que aparece
(pessoas, produtos, telas, lugares), o que acontece (em vídeos: a ação do começo
ao fim) e qualquer texto legível na imagem. A descrição vai orientar um editor
de vídeo que NÃO viu a mídia — seja concreto, sem opinião.

Posts:
{urls}

Responda SOMENTE com um array JSON no formato:
[{{"url": "https://x.com/usuario/status/ID", "descricao": "..."}}]
Um objeto por post, na mesma ordem. Se um post não tiver mídia ou não for
encontrado, use "descricao": "".\
"""


def descrever_midias_posts(cfg: Config, urls_posts: list[str]) -> dict[str, str]:
    """Descreve as mídias dos posts via x_search com análise de imagem/vídeo.

    Devolve {id_do_post: descrição}; vazio em qualquer falha (etapa opcional).
    """
    urls = [u for u in urls_posts if "status/" in u]
    if not urls:
        return {}

    cliente = OpenAI(api_key=cfg.xai_api_key, base_url="https://api.x.ai/v1")
    print(f"[midia-x] Analisando as mídias de {len(urls)} posts (x_search)...")
    try:
        resposta = cliente.responses.create(
            model=cfg.search_model,
            input=[{
                "role": "user",
                "content": INSTRUCOES_MIDIAS.format(urls="\n".join(urls)),
            }],
            tools=[{
                "type": "x_search",
                "enable_image_understanding": True,
                "enable_video_understanding": True,
            }],
        )
        itens = _extrair_json(resposta.output_text)
    # Etapa opcional: nunca derruba o pipeline (_extrair_json usa SystemExit)
    except (Exception, SystemExit) as erro:
        print(f"[aviso] Análise de mídias via x_search falhou: {erro}")
        return {}

    descricoes: dict[str, str] = {}
    for item in itens:
        if not isinstance(item, dict):
            continue
        m = re.search(r"status/(\d+)", str(item.get("url", "")))
        descricao = str(item.get("descricao", "")).strip()
        if m and descricao:
            descricoes[m.group(1)] = descricao
    print(f"[midia-x] {len(descricoes)} mídias descritas")
    return descricoes


def coletar_trends(cfg: Config) -> list[dict]:
    """Busca as N trends mais faladas do X nas últimas `janela_horas` horas."""
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
        "contas e empresas americanas e notícias com impacto nos EUA."
        if cfg.publico == "usa"
        else ""
    )
    base = INSTRUCOES_CONTAS if cfg.contas else INSTRUCOES_TRENDING
    if cfg.contas:
        ferramenta["allowed_x_handles"] = cfg.contas
        print(f"[x] Mapeando as {cfg.num_trends} trends de {len(cfg.contas)} contas...")
    else:
        print(
            f"[x] Mapeando as {cfg.num_trends} trends de tech/AI/dev/mercado de TI "
            "mais faladas do dia..."
        )

    instrucoes = (
        base.format(n=cfg.num_trends, horas=cfg.janela_horas)
        + foco_usa
        + FORMATO_RESPOSTA.format(n=cfg.num_trends)
    )

    resposta = cliente.responses.create(
        model=cfg.search_model,
        input=[{"role": "user", "content": instrucoes}],
        tools=[ferramenta],
    )

    brutos = _extrair_json(resposta.output_text)
    trends = [
        {
            "trend": t.get("trend", "").strip(),
            "resumo": t.get("resumo", "").strip(),
            "engajamento": t.get("engajamento", "").strip(),
            "sentimento": t.get("sentimento", "").strip(),
            "apelo_visual": t.get("apelo_visual", "").strip(),
            "posts": [u for u in (t.get("posts") or []) if isinstance(u, str)],
            "data": t.get("data", ""),
        }
        for t in brutos
        if t.get("trend") and t.get("resumo")
    ]

    if not trends:
        raise SystemExit(
            f"Nenhuma trend encontrada nas últimas {cfg.janela_horas}h. "
            "Aumente JANELA_HORAS no .env ou revise as contas."
        )

    print(f"[x] {len(trends)} trends coletadas")
    return trends
