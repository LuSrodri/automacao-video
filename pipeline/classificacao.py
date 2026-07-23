"""Classificação das trends candidatas: macrotema + imagem mental.

Este módulo era o filtro de "acessibilidade pré-conceitual" (score 1-5; só
virava vídeo candidata com score >= 4). Diretriz de 2026-07-18: a seleção
passou a ser guiada SOMENTE pelo que a audiência do canal está assistindo —
sem pesos nem filtro editorial, nenhuma candidata é rejeitada aqui. O que
sobrou desta etapa é a anotação que a seleção ainda precisa:

- macrotema: alimenta o teto de repetição (o mesmo macrotema não emenda mais
  de 4 vídeos seguidos — ver escritor.py);
- imagem_mental: o que a pessoa visualiza ao ouvir a notícia; é a matéria-prima
  do HOOK na hora do roteiro.

Uma única chamada ao GPT anota todas as candidatas, e todas seguem vivas para
a seleção.
"""

import json

from openai import OpenAI

from .config import Config

# Macrotemas do canal: a seleção em escritor.py impede que o mesmo macrotema
# emende mais vídeos seguidos que o teto configurado lá, garantindo um mínimo
# de variabilidade sem impor preferência editorial.
MACROTEMAS = [
    "ia",
    "dev-software",
    "hardware-chips",
    "bigtech-negocios",
    "mercado-trabalho-ti",
    "guerra-geopolitica",
    "ciencia-espaco",
    "outro",
]

MACROTEMAS_DESCRICAO = """\
- ia: modelos, produtos, pesquisas e empresas de IA
- dev-software: desenvolvimento de software, linguagens, frameworks, ferramentas
- hardware-chips: chips, GPUs, dispositivos, robôs, data centers
- bigtech-negocios: negócios, aquisições, disputas e resultados das big techs
- mercado-trabalho-ti: empregos, demissões, salários e carreira em tecnologia
- guerra-geopolitica: guerra, conflito militar, geopolítica, inteligência,
  espionagem, defesa
- ciencia-espaco: ciência, espaço, energia
- outro: o que não couber acima\
"""

INSTRUCOES_CLASSIFICACAO = """\
Você anota notícias candidatas a vídeo curto (YouTube Shorts) de um canal de
notícias quentes (geopolítica, inteligência, IA, tecnologia, negócios e o que
mais estiver dominando a conversa).

Para CADA notícia, preencha:
- "macrotema": UM macrotema da lista:
{macrotemas}
- "imagem_mental": descrição em 5 palavras do que a pessoa VISUALIZA ao ouvir
  a notícia; deixe vazio se ela não evocar nenhuma cena concreta.

Anote TODAS as notícias listadas, na mesma ordem, usando o campo "indice".
Responda somente com o JSON pedido.\
""".format(macrotemas=MACROTEMAS_DESCRICAO)

ESQUEMA_CLASSIFICACAO = {
    "name": "classificacao_trends",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "avaliacoes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "indice": {
                            "type": "integer",
                            "description": "Número da notícia na lista recebida.",
                        },
                        "imagem_mental": {
                            "type": "string",
                            "description": (
                                "Descrição em 5 palavras do que a pessoa "
                                "visualiza; vazio se não houver imagem mental."
                            ),
                        },
                        "macrotema": {
                            "type": "string",
                            "enum": MACROTEMAS,
                            "description": (
                                "Macrotema da notícia, conforme a lista das "
                                "instruções."
                            ),
                        },
                    },
                    "required": ["indice", "imagem_mental", "macrotema"],
                },
            }
        },
        "required": ["avaliacoes"],
    },
}


def _listar_candidatas(trends: list[dict]) -> str:
    linhas = []
    for i, t in enumerate(trends, 1):
        linhas.append(f"{i}. {t['trend']}\n   Resumo: {t['resumo']}")
    return "\n".join(linhas)


def classificar_trends(cfg: Config, trends: list[dict]) -> list[dict]:
    """Anota cada trend com macrotema e imagem_mental (1 chamada, sem filtro).

    Falha na chamada ABORTA a execução: sem o macrotema não existe o teto de
    repetição de macrotemas, e rodar sem ele é o que deixa o canal virar
    monotemático sem ninguém perceber.
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)

    print(f"[classificacao] Classificando {len(trends)} candidatas "
          "(macrotema + imagem mental)...")
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_CLASSIFICACAO},
                {
                    "role": "user",
                    "content": "Notícias candidatas:\n" + _listar_candidatas(trends),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_CLASSIFICACAO,
            },
        )
        avaliacoes = json.loads(resposta.choices[0].message.content)["avaliacoes"]
    except Exception as erro:  # noqa: BLE001 — sem macrotema não há teto de repetição
        raise SystemExit(
            "Classificação das candidatas falhou (OpenAI) — sem macrotema não "
            f"existe o teto de repetição de macrotemas; abortando: {erro}"
        ) from erro

    por_indice = {a["indice"]: a for a in avaliacoes}
    anotadas = []
    for i, trend in enumerate(trends, 1):
        av = por_indice.get(i, {})
        imagem = (av.get("imagem_mental") or "").strip()
        macrotema = (av.get("macrotema") or "").strip().lower()
        if macrotema not in MACROTEMAS:
            macrotema = "outro"
        print(
            f"[classificacao] [{macrotema}] — {trend['trend']}\n"
            f"                imagem mental: {imagem or '(nenhuma)'}"
        )
        anotadas.append(dict(trend, imagem_mental=imagem, macrotema=macrotema))
    return anotadas
