"""Pontuação de "acessibilidade pré-conceitual" das trends candidatas.

Etapa entre a captação (x_client) e a escolha da trend (escritor): o público de
Shorts é passivo, então só viram vídeo notícias compreensíveis sem NENHUM
conhecimento prévio e com imagem mental instantânea. Dado observado do canal:
eventos concretos/visuais (explosão, ameaça de guerra) fazem 1.1k+ views;
conceitos abstratos (benchmark de código) fazem ~20.

Uma única chamada ao GPT pontua todas as candidatas de 1 a 5; o main.py só
produz vídeo de trend com score >= 4. Score e justificativa de TODAS as
candidatas (inclusive rejeitadas) são logados no console.
"""

import json

from openai import OpenAI

from .config import Config

SCORE_MINIMO = 4  # só vira vídeo trend com score >= 4

# Macrotemas do canal: a rotação em escritor.py bloqueia repetir o macrotema do
# último vídeo publicado, para o canal cobrir TODAS as áreas de interesse em vez
# de deixar um macrotema (ex.: guerra) monopolizar a pauta.
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
- guerra-geopolitica: guerra, conflito militar, geopolítica
- ciencia-espaco: ciência, espaço, energia
- outro: o que não couber acima\
"""

INSTRUCOES_PONTUACAO = """\
Você avalia notícias candidatas a vídeo curto (YouTube Shorts) de um canal de
tecnologia, IA, desenvolvimento de software e mercado de trabalho de TI.

O público de Shorts é PASSIVO: só funciona conteúdo "pré-conceitual" —
compreensível sem nenhum conhecimento prévio e com imagem mental instantânea.

Pontue CADA notícia de 1 a 5 em "acessibilidade pré-conceitual":
- 5: evento físico/visual com carga emocional imediata, zero contexto necessário
  (robô caindo no palco, data center em chamas, demonstração ao vivo que falha,
  queda global de um serviço que todo mundo usa, flagrante, desastre — de
  QUALQUER domínio)
- 4: ação humana dramática compreensível por qualquer pessoa (corte de milhares
  de empregos com número, CEO demitido da noite para o dia, aquisição bilionária
  relâmpago, prisão, escândalo, ultimato de um líder)
- 3: consequência concreta de algo abstrato (preços dispararam, voos cancelados)
- 2: exige conhecer 1 conceito prévio (sanção, tarifa, indiciamento)
- 1: exige conhecimento de domínio (benchmark, protocolo, regulação técnica)

O score mede FORMA (acessibilidade), NUNCA o tema: violência e guerra NÃO valem
bônus. Uma notícia de tecnologia com evento físico/visual ou drama humano vale
4-5 exatamente como uma bélica — e um confronto militar sem imagem mental
concreta vale pouco como qualquer outra notícia sem imagem mental. Não desconte
pontos por a notícia ser de tech, e não some pontos por ser de guerra.

Classifique também o "macrotema" de cada notícia:
{macrotemas}

Regras:
- "imagem_mental": descrição em 5 palavras do que a pessoa VISUALIZA ao ouvir a
  notícia. Se não for possível preencher uma imagem mental concreta, deixe o
  campo vazio — e nesse caso o score máximo é 2.
- "justificativa": 1 frase explicando o score.
- Avalie TODAS as notícias listadas, na mesma ordem, usando o campo "indice".

Responda somente com o JSON pedido.\
""".format(macrotemas=MACROTEMAS_DESCRICAO)

ESQUEMA_PONTUACAO = {
    "name": "pontuacao_trends",
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
                        "score": {
                            "type": "integer",
                            "description": (
                                "Acessibilidade pré-conceitual, de 1 a 5."
                            ),
                        },
                        "imagem_mental": {
                            "type": "string",
                            "description": (
                                "Descrição em 5 palavras do que a pessoa "
                                "visualiza; vazio se não houver imagem mental."
                            ),
                        },
                        "justificativa": {
                            "type": "string",
                            "description": "1 frase justificando o score.",
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
                    "required": [
                        "indice",
                        "score",
                        "imagem_mental",
                        "justificativa",
                        "macrotema",
                    ],
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


def pontuar_trends(cfg: Config, trends: list[dict]) -> list[dict]:
    """Anota cada trend com score, imagem_mental e justificativa (1 chamada).

    Loga a avaliação de todas as candidatas, inclusive as rejeitadas. Falha na
    chamada ABORTA a execução: devolver tudo com score 0 se disfarçaria de
    "dia sem pauta aprovada" e a falha real nunca seria investigada.
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)

    print(f"[score] Pontuando {len(trends)} candidatas em acessibilidade "
          "pré-conceitual...")
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_PONTUACAO},
                {
                    "role": "user",
                    "content": "Notícias candidatas:\n" + _listar_candidatas(trends),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_PONTUACAO,
            },
        )
        avaliacoes = json.loads(resposta.choices[0].message.content)["avaliacoes"]
    except Exception as erro:  # noqa: BLE001 — sem score não há como filtrar
        raise SystemExit(
            "Pontuação das candidatas falhou (OpenAI) — sem score não existe "
            f"filtro pré-conceitual; abortando: {erro}"
        ) from erro

    por_indice = {a["indice"]: a for a in avaliacoes}
    anotadas = []
    for i, trend in enumerate(trends, 1):
        av = por_indice.get(i, {})
        score = max(1, min(int(av.get("score") or 1), 5))
        imagem = (av.get("imagem_mental") or "").strip()
        if not imagem:  # sem imagem mental, o teto é 2
            score = min(score, 2)
        justificativa = (av.get("justificativa") or "").strip()
        macrotema = (av.get("macrotema") or "").strip().lower()
        if macrotema not in MACROTEMAS:
            macrotema = "outro"
        status = "APROVADA" if score >= SCORE_MINIMO else "rejeitada"
        print(
            f"[score] {score}/5 ({status}) [{macrotema}] — {trend['trend']}\n"
            f"        imagem mental: {imagem or '(nenhuma)'}\n"
            f"        {justificativa}"
        )
        anotadas.append(
            dict(trend, score=score, imagem_mental=imagem,
                 justificativa=justificativa, macrotema=macrotema)
        )
    return anotadas
