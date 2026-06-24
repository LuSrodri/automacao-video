"""Seleção da trend do dia e geração de título, descrição e roteiro do vídeo.

Duas etapas:
1. `selecionar_trend` — entre as trends coletadas do X, escolhe a de MAIOR apelo
   visual e chance de viralizar (evitando repetir vídeos recentes) e devolve uma
   consulta de notícias para enriquecer o material.
2. `gerar_roteiro` — com a trend escolhida + notícias do Firecrawl, escreve o
   roteiro narrado seguindo a curva de retenção (gancho, desenvolvimento que
   prende, recompensa no final) e define de 8 a 10 imagens-chave.
"""

import json

from openai import OpenAI

from .config import Config

ESQUEMA_SELECAO = {
    "name": "selecao_trend",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "trend": {
                "type": "string",
                "description": (
                    "A trend escolhida entre as listadas — a de MAIOR apelo "
                    "visual e maior chance de viralizar que NÃO repita os vídeos "
                    "recentes do canal."
                ),
            },
            "motivo": {
                "type": "string",
                "description": (
                    "Uma frase justificando por que essa trend tem o maior "
                    "potencial visual e de viralização."
                ),
            },
            "consulta_noticias": {
                "type": "string",
                "description": (
                    "Consulta de busca de NOTÍCIAS (em inglês, com nomes "
                    "próprios e o acontecimento) para encontrar manchetes "
                    "recentes que complementem a trend com fatos e números."
                ),
            },
        },
        "required": ["trend", "motivo", "consulta_noticias"],
    },
}

ESQUEMA_ROTEIRO = {
    "name": "roteiro_video",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tema": {
                "type": "string",
                "description": "A trend/tema do vídeo.",
            },
            "titulo": {
                "type": "string",
                "description": (
                    "Título chamativo do vídeo, no idioma definido nas "
                    "instruções, até 90 caracteres."
                ),
            },
            "descricao": {
                "type": "string",
                "description": (
                    "Descrição do vídeo no idioma definido nas instruções, "
                    "1 a 3 frases em um único parágrafo, com hashtags "
                    "relevantes no final."
                ),
            },
            "texto_video": {
                "type": "string",
                "description": (
                    "Texto/roteiro narrado do vídeo, no idioma definido nas "
                    "instruções. Dinâmico, rápido e direto ao ponto, com gancho "
                    "impecável nos primeiros 3 segundos e recompensa no final."
                ),
            },
            "imagens": {
                "type": "array",
                "minItems": 8,
                "maxItems": 10,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "consulta": {
                            "type": "string",
                            "description": (
                                "Consulta de busca de imagem em inglês para "
                                "encontrar UMA imagem real e coerente com este "
                                "momento da narração. Priorize a foto do "
                                "próprio fato (pessoas e empresas envolvidas "
                                "na ação, o evento, o produto em uso real). "
                                "Para contextualizar, também valem: foto da "
                                "figura pública citada, o logo/identidade "
                                "visual da empresa mencionada, foto do produto "
                                "e foto do local/lugar relevante. Seja "
                                "específico com nomes próprios e o "
                                "acontecimento. Evite ilustrações genéricas, "
                                "fotos de banco de imagens (stock) e imagens "
                                "geradas por IA."
                            ),
                        },
                        "trecho": {
                            "type": "string",
                            "description": (
                                "Trecho copiado LITERALMENTE do texto_video "
                                "(substring exata, contígua) durante o qual "
                                "esta imagem deve aparecer na tela."
                            ),
                        },
                    },
                    "required": ["consulta", "trecho"],
                },
                "description": (
                    "8 a 10 imagens-chave sincronizadas com a narração, "
                    "distribuídas do início ao fim do roteiro para que NUNCA "
                    "haja um trecho sem imagem na tela."
                ),
            },
        },
        "required": ["tema", "titulo", "descricao", "texto_video", "imagens"],
    },
}

FOCO_BRASIL = """\
Escreva tudo (título, descrição e narração) em PORTUGUÊS DO BRASIL, com foco em
temas e referências relevantes para o público brasileiro de tecnologia.\
"""

FOCO_USA = """\
Escreva tudo (título, descrição e narração) em INGLÊS AMERICANO, 100% para o
público dos EUA: tom, referências, unidades e hashtags americanas. Nada de
português.\
"""

INSTRUCOES_SELECAO = """\
Você é editor de um canal de vídeos curtos sobre trends de tecnologia e IA.

Você recebe as trends mais faladas do X hoje (cada uma com resumo, engajamento e
uma nota de apelo visual) e os últimos vídeos já publicados no canal.

Escolha UMA trend para virar o próximo vídeo, segundo estes critérios, nesta ordem:
1. MAIOR chance de viralizar (impacto, polêmica, novidade, curiosidade) E maior
   APELO VISUAL — assuntos com pessoas conhecidas, produtos, eventos e lugares
   que rendem boas imagens reais.
2. NÃO repetir os temas dos vídeos recentes do canal, salvo se houver novidade
   real e relevante.

Gere também uma consulta de busca de NOTÍCIAS (em inglês) para a trend escolhida.
Responda somente com o JSON pedido.\
"""

INSTRUCOES_ROTEIRO = """\
Você é roteirista de vídeos curtos (YouTube Shorts/Reels/TikTok) sobre trends de
tecnologia e inteligência artificial. {foco}

Você recebe a TREND escolhida para o vídeo e NOTÍCIAS recentes sobre ela. Use as
notícias para acertar fatos, nomes, empresas, datas e números — não invente.

Escreva o roteiro narrado (campo texto_video) seguindo a CURVA DE RETENÇÃO de um
vídeo curto que precisa segurar a pessoa até o fim:

1. GANCHO (primeiros ~3 segundos): a primeira frase tem que ser IMPECÁVEL e
   irresistível — uma afirmação chocante, um número absurdo, uma pergunta
   provocadora ou uma promessa clara do que a pessoa vai descobrir. Nada de
   "Hoje vamos falar sobre...". Crie uma lacuna de curiosidade imediata.
2. DESENVOLVIMENTO: cada frase puxa a próxima. Entregue a informação em camadas,
   adiando a revelação principal, criando pequenas tensões ("mas tem um detalhe",
   "e foi aí que..."). O ritmo é RÁPIDO, dinâmico e direto ao ponto — sem
   enrolação, sem frases mortas, sem pausas. Toda frase tem que justificar o
   tempo dela na tela.
3. RECOMPENSA (final): entregue a revelação/payoff que o gancho prometeu, de
   forma que a pessoa sinta que VALEU A PENA ter ficado até o fim — uma
   conclusão satisfatória, uma virada, um dado que amarra tudo ou uma opinião
   forte. A pessoa não pode se sentir enganada. Termine com um gancho de
   engajamento (pergunta/opinião que provoque comentários).

O roteiro deve ser narrável em cerca de {duracao} segundos (aproximadamente
{palavras} palavras).

IMAGENS — defina de 8 a 10 imagens-chave, distribuídas do começo ao fim do
roteiro (NUNCA pode haver um trecho da narração sem imagem na tela). REGRAS:
- As imagens serão buscadas na web (fotos REAIS, nada gerado por IA). Em
  "consulta", escreva a busca em inglês que encontra a imagem mais COERENTE com
  a notícia daquele momento. Use uma MISTURA de tipos: a foto do próprio
  fato/evento, a figura pública envolvida, o logo da empresa, o produto e o
  lugar/local relevante.
  Exemplo (OpenAI lançando o GPT-6): "Sam Altman GPT-6 launch keynote 2026",
  "OpenAI GPT-6 announcement event", "OpenAI logo",
  "OpenAI headquarters San Francisco".
- Prefira a imagem do acontecimento real em vez de ilustração genérica; evite
  fotos de banco de imagens (stock) e imagens geradas por IA. Logos, retratos e
  fotos de lugares são bem-vindos como contexto — só não deixe que TODAS as
  imagens sejam apenas logos.
- Prefira assuntos visualmente documentados e fáceis de achar em boa resolução.
- Em "trecho", copie literalmente a parte do texto_video em que a imagem deve
  aparecer (substring exata do texto_video, sem alterar nada). Distribua as
  imagens uniformemente ao longo de TODO o texto.

NARRAÇÃO EXPRESSIVA — insira audio tags do ElevenLabs v3 no texto_video:
palavras em inglês entre colchetes, imediatamente antes do trecho que modificam.
Exemplos: [excited], [curious], [whispers], [surprised], [sighs], [laughs],
[short pause]. Use de 8 a 12 tags, variando a emoção conforme o conteúdo (elas
não são faladas nem aparecem nas legendas). A pontuação também guia a entrega:
reticências para suspense, MAIÚSCULAS para ênfase pontual.

Responda somente com o JSON pedido.\
"""


def _resumo_trends(trends: list[dict]) -> str:
    linhas = []
    for i, t in enumerate(trends, 1):
        linhas.append(
            f"{i}. {t['trend']}\n"
            f"   Resumo: {t['resumo']}\n"
            f"   Engajamento: {t.get('engajamento', '?')}\n"
            f"   Apelo visual: {t.get('apelo_visual', '?')}"
        )
    return "\n".join(linhas)


def _resumo_recentes(videos_recentes: list[dict] | None) -> str:
    if not videos_recentes:
        return ""
    recentes = "\n".join(
        f"- ({v.get('data') or '?'}) {v.get('titulo', '')}" for v in videos_recentes
    )
    return (
        "\n\nÚltimos vídeos já publicados neste canal (NÃO repita esses temas, "
        "salvo novidade real):\n" + recentes
    )


def selecionar_trend(
    cfg: Config,
    trends: list[dict],
    videos_recentes: list[dict] | None = None,
) -> dict:
    """Escolhe a trend de maior apelo visual/viral e a consulta de notícias."""
    cliente = OpenAI(api_key=cfg.openai_api_key)

    conteudo = (
        "Trends mais faladas do X hoje:\n"
        + _resumo_trends(trends)
        + _resumo_recentes(videos_recentes)
    )

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": INSTRUCOES_SELECAO},
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_SELECAO},
    )
    selecao = json.loads(resposta.choices[0].message.content)
    print(f"[roteiro] Trend escolhida: {selecao['trend']}")
    print(f"[roteiro] Motivo: {selecao['motivo']}")
    return selecao


def _resumo_noticias(noticias: list[dict]) -> str:
    if not noticias:
        return "(nenhuma notícia recuperada — baseie-se no resumo da trend.)"
    linhas = []
    for n in noticias:
        data = f" ({n['data']})" if n.get("data") else ""
        linhas.append(f"- {n['titulo']}{data}: {n.get('resumo', '')}")
    return "\n".join(linhas)


def gerar_roteiro(
    cfg: Config,
    selecao: dict,
    trends: list[dict],
    noticias: list[dict],
) -> dict:
    """Gera o roteiro completo da trend escolhida, enriquecido com notícias."""
    cliente = OpenAI(api_key=cfg.openai_api_key)

    trend_escolhida = next(
        (t for t in trends if t["trend"] == selecao["trend"]),
        {"trend": selecao["trend"], "resumo": selecao.get("motivo", "")},
    )

    conteudo = (
        f"TREND ESCOLHIDA: {trend_escolhida['trend']}\n"
        f"Resumo da trend: {trend_escolhida.get('resumo', '')}\n\n"
        "NOTÍCIAS RECENTES SOBRE A TREND:\n" + _resumo_noticias(noticias)
    )

    instrucoes = INSTRUCOES_ROTEIRO.format(
        foco=FOCO_USA if cfg.publico == "usa" else FOCO_BRASIL,
        duracao=cfg.video_duracao,
        palavras=int(cfg.video_duracao * 2.5),
    )

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_ROTEIRO},
    )

    roteiro = json.loads(resposta.choices[0].message.content)
    print(f"[roteiro] Tema do dia: {roteiro['tema']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    print(f"[roteiro] {len(roteiro['imagens'])} imagens-chave definidas")
    return roteiro
