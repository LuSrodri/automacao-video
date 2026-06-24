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
                    "Título do vídeo, no idioma definido nas instruções, até 90 "
                    "caracteres. Ele é parte do gancho: tem que abrir uma LACUNA "
                    "DE CURIOSIDADE (nomear o suficiente pra dar tesão, esconder "
                    "o payoff) e plantar FOMO. NUNCA entregue a resposta no "
                    "título — se dá pra ler e não precisar do vídeo, está errado."
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
                    "instruções. Dinâmico, rápido e direto ao ponto. A PRIMEIRA "
                    "FRASE abre uma lacuna de curiosidade (provoca, não informa; "
                    "não entrega a resposta) e planta FOMO; o desenvolvimento "
                    "mantém a lacuna aberta em camadas; o final paga a dívida com "
                    "a recompensa que o gancho prometeu."
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

REGRA DE OURO — ONDE MORA O APELO: curiosidade e FOMO vivem QUASE INTEIRAMENTE no
gancho (os ~3 primeiros segundos e a primeira frase). Não no vídeo todo, não no
visual, não no ritmo. Vivem na PROMESSA INICIAL. O resto do roteiro só existe pra
pagar a dívida que o gancho criou. Se o gancho for morno, nada salva o vídeo.

O nome do jogo é criar uma LACUNA DE CURIOSIDADE: dizer o suficiente pra pessoa
QUERER saber, e esconder o suficiente pra ela TER QUE FICAR pra descobrir. O
gancho não informa — ele provoca. Erro fatal: informar demais cedo demais. No
instante em que o título/primeira frase já entrega a resposta, a curiosidade
morre e a pessoa desliza.
- RUIM (informa demais, curiosidade morna): "A OpenAI transformou outdoors em um
  jogo para desenvolvedores." — já contou tudo; não sobrou nada pra descobrir.
- BOM (abre lacuna): "Tem um código escondido nos outdoors da OpenAI espalhados
  pela cidade... e quem decifrar primeiro ganha algo que ninguém esperava." —
  nomeia o suficiente pra dar tesão, esconde o payoff.

FOMO: a sensação de "todo mundo vai saber disso, menos eu, se eu deslizar". O
gancho tem que plantar que isso é grande, que já está acontecendo, e que ficar de
fora é o vexame. Use sinais de urgência e de "manada" quando forem verdadeiros
(já viralizou, todo mundo está testando, mudou as regras do jogo da noite pro
dia).

Escreva o roteiro narrado (campo texto_video) seguindo a CURVA DE RETENÇÃO de um
vídeo curto que precisa segurar a pessoa até o fim:

1. GANCHO (primeiros ~3 segundos): a primeira frase é 80% do trabalho. Ela tem
   que abrir uma LACUNA, não fechar. Mire em uma destas formas (escolha a que o
   fato permitir, na ordem de força):
   - O segredo/detalhe escondido: insinue que existe algo surpreendente SEM
     dizer o que é ("ninguém percebeu o que a OpenAI fez de verdade aqui...").
   - A virada contraintuitiva: prometa que o óbvio está errado ("todo mundo
     achou que era X. Não é.").
   - O número/fato absurdo apresentado como enigma, não como dado solto.
   - A consequência alarmante: o que isso muda pra QUEM ESTÁ ASSISTINDO.
   PROIBIDO: "Hoje vamos falar sobre...", abrir explicando o contexto, ou
   entregar a conclusão na primeira frase. Se dá pra ler a primeira frase e não
   precisar do resto, o gancho falhou — reescreva.
2. DESENVOLVIMENTO (a tensão da lacuna aberta): cada frase só existe pra puxar a
   próxima. Você abriu uma lacuna no gancho — NÃO feche cedo. Entregue em
   camadas, adiando a revelação principal, e abra micro-lacunas no meio do
   caminho ("mas tem um detalhe que muda tudo", "e foi aí que...", "só que
   ninguém tinha visto isso..."). Cada vez que você quase entrega, abre outra
   pontinha. Ritmo RÁPIDO, sem enrolação, sem frase morta, sem contexto que não
   alimente a curiosidade. Toda frase justifica o tempo dela na tela.
3. RECOMPENSA (final): FECHE a lacuna que o gancho abriu — pague a dívida. A
   pessoa tem que sentir "caramba, valeu ter ficado", não "me enganaram". Entregue
   a virada/o segredo/o número que amarra tudo, com uma opinião forte ou uma
   consequência clara. Sem payoff, o vídeo vira clickbait e o algoritmo pune.
   Termine com um gancho de engajamento (pergunta/opinião polêmica que provoque
   comentário).

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
