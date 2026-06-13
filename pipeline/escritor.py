"""Seleção do tema do dia e geração de título, descrição e texto do vídeo."""

import json

from openai import OpenAI

from .config import Config

ESQUEMA_ROTEIRO = {
    "name": "roteiro_video",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tema": {
                "type": "string",
                "description": "O tema do dia escolhido entre as trends mais comentadas pelos usuários.",
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
                    "instruções, conciso e dinâmico, adequado a um vídeo curto."
                ),
            },
            "imagens": {
                "type": "array",
                "minItems": 8,
                "maxItems": 12,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "consulta": {
                            "type": "string",
                            "description": (
                                "Consulta de busca de imagem em inglês para "
                                "encontrar UMA foto/imagem real na web que "
                                "ilustre este momento da narração (logo "
                                "oficial, foto de figura pública, foto de "
                                "produto, sede da empresa etc.)."
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
                    "8 a 12 imagens-chave sincronizadas com a narração do vídeo."
                ),
            },
        },
        "required": ["tema", "titulo", "descricao", "texto_video", "imagens"],
    },
}

FOCO_BRASIL = """\
1. Escolher A TREND MAIS COMENTADA PELOS USUÁRIOS do dia (maior impacto/polêmica/interesse para o público tech/AI),
com foco em temas relevantes para o público brasileiro.
2. Criar título, descrição e o texto do vídeo, todos em português do Brasil.\
"""

FOCO_USA = """\
1. Escolher A TREND MAIS COMENTADA PELOS USUÁRIOS do dia para o público de tecnologia dos
ESTADOS UNIDOS: priorize forte impacto/polêmica/interesse, relevância para o público americano, e temas atuais
no mercado e na cultura tech dos EUA.
2. Criar título, descrição e o texto do vídeo, todos em INGLÊS AMERICANO,
escritos 100% para o público dos EUA: tom, referências, unidades e hashtags
americanas. Nada de português.\
"""

INSTRUCOES = """\
Você é roteirista de vídeos curtos sobre trends do dia de tecnologia e inteligência artificial.

Você receberá posts recentes do X (Twitter). Sua tarefa:
{foco}
3. O texto do vídeo deve ser narrável em cerca de {duracao} segundos
   (aproximadamente {palavras} palavras): direto, empolgante, sem enrolação,
   explicando a notícia, o contexto e por que ela importa.
4. Definir de 8 a 12 imagens-chave (use bastante: quanto mais momentos
   ilustrados, mais dinâmico fica o vídeo). REGRAS DAS IMAGENS:
   - As imagens serão buscadas na web (fotos e logos REAIS, nada gerado por
     IA). Em "consulta", escreva a busca em inglês que encontra a melhor
     imagem para aquele momento: logo oficial da empresa, foto da figura
     pública envolvida, foto do produto, gráfico divulgado etc.
     Exemplo: notícia sobre a OpenAI -> "OpenAI official logo" e
     "Sam Altman portrait photo".
   - Prefira assuntos visualmente reconhecíveis e fáceis de achar em boa
     resolução.
   - Em "trecho", copie literalmente a parte do texto_video em que a imagem
     deve aparecer (substring exata do texto_video, sem alterar nada), para
     sincronizar a imagem com a narração. Distribua as imagens ao longo de
     todo o texto, não concentre tudo no início.
5. Deixe a narração expressiva inserindo audio tags do ElevenLabs v3 no
   texto_video: palavras em inglês entre colchetes, posicionadas imediatamente
   antes do trecho que modificam. Exemplos: [excited], [curious], [whispers],
   [surprised], [sighs], [laughs], [clears throat], [short pause]. Use de 8 a
   12 tags por roteiro, variando a emoção conforme o conteúdo (elas não são
   faladas nem aparecem nas legendas). A pontuação também guia a entrega:
   reticências para suspense, MAIÚSCULAS para ênfase pontual.
6. A narração deve ter ganchos com opiniões e perguntas para o público, para aumentar o engajamento e reações.

Responda somente com o JSON pedido.\
"""


def gerar_roteiro(cfg: Config, tweets: list[dict]) -> dict:
    cliente = OpenAI(api_key=cfg.openai_api_key)

    linhas = [
        f"- @{t['conta']} ({t['data']}): {t['texto']}"
        for t in tweets[:40]
    ]
    conteudo = "Posts coletados hoje:\n" + "\n".join(linhas)
    instrucoes = INSTRUCOES.format(
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
    return roteiro
