"""Classificação das trends candidatas: macrotema + imagem mental.

Este módulo era o filtro de "acessibilidade pré-conceitual" (score 1-5; só
virava vídeo candidata com score >= 4). Diretriz de 2026-07-18: a seleção
passou a ser guiada SOMENTE pelo que a audiência do canal está assistindo —
sem pesos nem filtro editorial, nenhuma candidata é rejeitada aqui. O que
sobrou desta etapa é a anotação que a seleção ainda precisa:

- macrotema: rotula a candidata para a seleção poder ler a régua de audiência
  por TEMA e não vídeo a vídeo ("os 'mercado-trabalho' fazem 15 mil views, os
  'dev-software' fazem 200" — ver escritor.py). É também o que alimenta o
  RODÍZIO de temas dos Shorts, e por isso a lista precisa cobrir todos os
  assuntos possíveis desde que o canal deixou de ter recorte temático;
- imagem_mental: o que a pessoa visualiza ao ouvir a notícia; é a matéria-prima
  do HOOK na hora do roteiro.

Uma única chamada ao GPT anota todas as candidatas, e todas seguem vivas para
a seleção.
"""

import json

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config

# Macrotemas do canal. No formato CURTO eles têm efeito de regra: o RODÍZIO de
# temas dos Shorts (2026-08-04, escritor.py) veta as candidatas cujo macrotema é
# o dos últimos Shorts publicados, para que cada Short saia de um tema diferente
# do anterior. No formato longo eles seguem só como contexto.
#
# A LISTA COBRE TODOS OS TEMAS desde 2026-08-16 (pedido do usuário): o canal
# deixou de ter recorte temático, e uma lista só de rótulos de tecnologia
# empurraria metade das pautas novas para "outro" — que é o balde de descarte e
# NÃO entra no rodízio, ou seja, o rodízio pararia de funcionar justamente nos
# assuntos recém-admitidos. Voltou por isso "mundo-conflitos", que tinha saído
# em 2026-07-30 quando guerra e geopolítica foram vetadas.
MACROTEMAS = [
    "ia",
    "criacoes-ia",
    "dev-software",
    "hardware-chips",
    "bigtech-negocios",
    "mercado-trabalho",
    "mercado-financeiro",
    "ciencia-espaco",
    "saude-bem-estar",
    "politica-sociedade",
    "mundo-conflitos",
    "crime-justica",
    "clima-ambiente",
    "esporte",
    "cultura-entretenimento",
    "consumo-cotidiano",
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
- saude-bem-estar: medicina, remédios, epidemias, saúde pública, alimentação
- politica-sociedade: governo, eleições, leis, decisões públicas, protestos,
  costumes, religião, educação
- mundo-conflitos: guerra, conflito armado, geopolítica, diplomacia, defesa,
  fronteiras, migração
- crime-justica: crimes, investigações, prisões, julgamentos, tribunais
- clima-ambiente: clima, desastres naturais, meio ambiente, catástrofes
- esporte: competições, atletas, resultados, transferências, federações
- cultura-entretenimento: cinema, séries, música, games, celebridades, internet
- consumo-cotidiano: preços, produtos, varejo, viagem, transporte, moradia
- outro: o que não couber em NENHUM dos anteriores (use com parcimônia)\
"""

INSTRUCOES_CLASSIFICACAO = """\
Você anota notícias candidatas a vídeo de um canal de análise SEM RECORTE
TEMÁTICO: qualquer assunto pode virar vídeo, então classifique o que receber
sem julgar se o tema "combina" com o canal.

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


# Macrotema que NÃO é macrotema: "outro" é o balde do que não coube em nenhum
# rótulo da lista, e a instrução manda usá-lo com parcimônia justamente por
# isso. Ver `filtrar_por_macrotema`.
MACROTEMA_DESCARTE = "outro"


def filtrar_por_macrotema(trends: list[dict]) -> list[dict]:
    """Deixa passar só as candidatas de um macrotema DEFINIDO; muta nada.

    Pedido do usuário em 2026-08-28, junto com a virada das curtidas: a pauta
    tem de estar "dentro nos macrotemas que a gente definiu". Como a lista
    cobre todos os assuntos desde 2026-08-16 (o canal não tem recorte
    temático), o que este filtro faz de fato é derrubar o BALDE: a candidata
    que o classificador não conseguiu pôr em nenhum dos dezesseis rótulos.

    O corte tem consequência prática além da editorial, e é ela que o
    justifica: "outro" não entra no RODÍZIO de temas dos Shorts (escritor.py) —
    um Short de "outro" seguido de outro Short de "outro" não é barrado por
    nada. Enquanto ele era só um rótulo de contexto isso passava; com as
    curtidas na fonte da pauta o volume de assunto atípico sobe, e o rodízio
    deixaria de funcionar exatamente onde mais precisa.

    O filtro CEDE quando zeraria a disputa, como o rodízio cede: o dia em que
    todas as candidatas caíram no balde é um dia de classificação ruim, não de
    pauta ruim, e trocar um vídeo por nenhum vídeo é caro demais para um rótulo.
    """
    dentro = [t for t in trends if t.get("macrotema") != MACROTEMA_DESCARTE]
    fora = len(trends) - len(dentro)
    if not fora:
        return trends
    if not dentro:
        print(
            f"[classificacao] TODAS as {len(trends)} candidatas caíram em "
            f"'{MACROTEMA_DESCARTE}'; o filtro de macrotema cede (o rodízio de "
            "temas do Short fica sem efeito nesta execução)."
        )
        return trends
    print(
        f"[classificacao] {fora} candidata(s) fora dos macrotemas definidos "
        f"('{MACROTEMA_DESCARTE}') saem da disputa; {len(dentro)} seguem."
    )
    return dentro
