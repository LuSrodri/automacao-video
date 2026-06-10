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
                "description": "O tema do dia escolhido entre as notícias.",
            },
            "titulo": {
                "type": "string",
                "description": "Título chamativo do vídeo, em português, até 90 caracteres.",
            },
            "descricao": {
                "type": "string",
                "description": (
                    "Descrição do vídeo em português, 1 a 3 frases em um único "
                    "parágrafo, com hashtags relevantes no final."
                ),
            },
            "texto_video": {
                "type": "string",
                "description": (
                    "Texto/roteiro narrado do vídeo, em português, conciso e "
                    "dinâmico, adequado a um vídeo curto."
                ),
            },
            "imagens": {
                "type": "array",
                "minItems": 1,
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": (
                                "Prompt em inglês para a imagem-chave. "
                                "Obrigatoriamente um logo de marca conhecida OU "
                                "uma figura pública conhecida ligada à notícia, "
                                "em estilo caricato/cartoon, elemento único e "
                                "isolado, sem fundo nem cenário."
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
                    "required": ["prompt", "trecho"],
                },
                "description": (
                    "1 a 3 imagens-chave sincronizadas com a narração do vídeo."
                ),
            },
        },
        "required": ["tema", "titulo", "descricao", "texto_video", "imagens"],
    },
}

INSTRUCOES = """\
Você é roteirista de vídeos curtos sobre tecnologia e inteligência artificial.

Você receberá posts recentes do X (Twitter). Sua tarefa:
1. Escolher O TEMA MAIS RELEVANTE do dia (maior impacto/novidade para o público tech).
2. Criar título, descrição e o texto do vídeo, todos em português do Brasil.
3. O texto do vídeo deve ser narrável em cerca de 20 segundos: direto,
   empolgante, sem enrolação, explicando a notícia e por que ela importa.
4. Definir de 1 a 3 imagens-chave. REGRAS DAS IMAGENS:
   - Cada imagem deve ser OU o logo de uma marca/empresa conhecida OU uma
     figura pública conhecida, sempre diretamente ligada à notícia.
     Exemplo: notícia sobre a OpenAI -> logo da OpenAI e caricatura do
     Sam Altman.
   - Estilo sempre caricato/cartoon (caricatura divertida para pessoas,
     versão cartunizada e estilizada para logos).
   - O prompt deve ser em inglês, descrevendo UM elemento único, isolado,
     sem fundo, sem cenário e SEM nenhum texto além do que faz parte do logo.
   - Em "trecho", copie literalmente a parte do texto_video em que a imagem
     deve aparecer (substring exata do texto_video, sem alterar nada), para
     sincronizar a imagem com a narração.

Responda somente com o JSON pedido.\
"""


def gerar_roteiro(cfg: Config, tweets: list[dict]) -> dict:
    cliente = OpenAI(api_key=cfg.openai_api_key)

    linhas = [
        f"- @{t['conta']} ({t['data']}): {t['texto']}"
        for t in tweets[:40]
    ]
    conteudo = "Posts coletados hoje:\n" + "\n".join(linhas)

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": INSTRUCOES},
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_ROTEIRO},
    )

    roteiro = json.loads(resposta.choices[0].message.content)
    print(f"[roteiro] Tema do dia: {roteiro['tema']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    return roteiro
