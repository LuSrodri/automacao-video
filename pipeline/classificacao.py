"""Classificação das trends candidatas: macrotema + imagem mental.

Este módulo era o filtro de "acessibilidade pré-conceitual" (score 1-5; só
virava vídeo candidata com score >= 4). Diretriz de 2026-07-18: a seleção
passou a ser guiada SOMENTE pelo que a audiência do canal está assistindo —
sem pesos nem filtro editorial, nenhuma candidata é rejeitada aqui. O que
sobrou desta etapa é a anotação que a seleção ainda precisa:

- macrotema: rotula a candidata para a seleção poder ler a régua de audiência
  por TEMA e não vídeo a vídeo ("os 'mercado-trabalho' fazem 15 mil views, os
  'dev-software' fazem 200" — ver escritor.py). Já alimentou um teto de
  macrotemas seguidos, removido em 2026-07-28;
- imagem_mental: o que a pessoa visualiza ao ouvir a notícia; é a matéria-prima
  do HOOK na hora do roteiro.

Uma única chamada ao GPT anota todas as candidatas, e todas seguem vivas para
a seleção.
"""

import json

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config

# Macrotemas do canal. No formato CURTO eles voltaram a ter efeito de regra: o
# RODÍZIO de temas dos Shorts (2026-08-04, escritor.py) veta as candidatas cujo
# macrotema é o dos últimos Shorts publicados, para que cada Short saia de um
# tema diferente do anterior. No formato longo eles seguem só como contexto.
# "guerra-geopolitica" saiu em 2026-07-30 junto com as
# contas de inteligência/defesa: o canal deixou de cobrir o assunto, e manter o
# rótulo só serviria para rotular como "outro" disfarçado o que já não é pauta.
# "mercado-financeiro" entrou no lugar, com o novo foco do canal.
MACROTEMAS = [
    "ia",
    "criacoes-ia",
    "dev-software",
    "hardware-chips",
    "bigtech-negocios",
    "mercado-trabalho",
    "mercado-financeiro",
    "ciencia-espaco",
    "outro",
]

# "criacoes-ia" entrou em 2026-08-04 (pedido do usuário). Ele é o oposto de
# "ia": "ia" é a notícia sobre o LABORATÓRIO (modelo lançado, rodada de
# investimento, benchmark), "criacoes-ia" é a notícia sobre o QUE FOI FEITO com
# a ferramenta — o vídeo, a música, a imagem, o curta, o personagem, o app
# gerado. É o macrotema do vídeo que mostra o resultado na tela, e é o que
# melhor casa com um formato montado só de clipes: a criação é o clipe.
MACROTEMAS_DESCRICAO = """\
- ia: modelos, produtos, pesquisas e empresas de IA (o lado do laboratório:
  lançamento, benchmark, investimento, disputa entre labs)
- criacoes-ia: CRIAÇÕES FEITAS COM IA — vídeo, curta, animação, música, imagem,
  arte, personagem, jogo, site ou app gerados por IA; o trabalho de quem usa as
  ferramentas generativas e o resultado que dá para ver ou ouvir na tela. Se a
  notícia é sobre a OBRA gerada (e não sobre o modelo que a gerou), é aqui
- dev-software: desenvolvimento de software, linguagens, frameworks, ferramentas
- hardware-chips: chips, GPUs, dispositivos, robôs, data centers
- bigtech-negocios: negócios, aquisições, disputas e resultados das big techs
- mercado-trabalho: empregos, demissões, contratações, salários e carreira
- mercado-financeiro: bolsa, juros, inflação, resultados, investimento,
  regulação financeira, cripto
- ciencia-espaco: ciência, espaço, energia
- outro: o que não couber acima\
"""

INSTRUCOES_CLASSIFICACAO = """\
Você anota notícias candidatas a vídeo de um canal de análise sobre
tecnologia, inteligência artificial, mercado de trabalho e mercado financeiro.

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
                    "content": AVISO_DADOS_EXTERNOS
                    + "\n\nNotícias candidatas:\n"
                    + _listar_candidatas(trends),
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
