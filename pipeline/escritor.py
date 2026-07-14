"""Seleção da trend do dia e geração de título, descrição e roteiro do vídeo.

Duas etapas:
1. `selecionar_trend` — entre as trends já APROVADAS no score de acessibilidade
   pré-conceitual (pontuacao.py), escolhe a melhor priorizando posts com VÍDEO,
   depois com foto e por último só texto (evitando repetir vídeos recentes), e
   devolve uma consulta de notícias para enriquecer o material.
2. `gerar_roteiro` — com a trend escolhida + notícias do Firecrawl, escreve o
   roteiro pré-conceitual (frases de até 8 palavras, vocabulário de criança,
   estrutura HOOK → FATO → IMPLICAÇÃO → CORTE) e define de 8 a 10 imagens-chave.
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
                    "A trend escolhida entre as listadas — priorizando posts "
                    "com VÍDEO, depois foto, por último só texto — que NÃO "
                    "repita os vídeos recentes do canal."
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
                    "Consulta CURTA de busca de NOTÍCIAS em inglês: 3 a 6 "
                    "palavras, só os nomes próprios principais + o acontecimento "
                    "central (ex.: 'Anthropic Claude global outage'). NÃO empilhe "
                    "detalhes, sintomas, códigos de erro nem sinônimos — consulta "
                    "longa demais zera os resultados."
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
            "hook": {
                "type": "string",
                "description": (
                    "A frase de abertura (0-2s): a imagem mais CHOCANTE da "
                    "notícia, direta, sem preâmbulo. Máximo 8 palavras. NUNCA "
                    "começar com contexto, data ou nome de instituição. A "
                    "primeira frase de texto_video DEVE ser exatamente esta "
                    "(copiada palavra por palavra, antes de qualquer audio tag)."
                ),
            },
            "implicacao": {
                "type": "string",
                "description": (
                    "A ÚNICA consequência simples que o vídeo entrega "
                    "('isso significa que...'). Uma só — decida antes de "
                    "escrever o texto_video."
                ),
            },
            "titulo": {
                "type": "string",
                "description": (
                    "Título do vídeo, no idioma definido nas instruções, até 90 "
                    "caracteres. O título promete EXATAMENTE o que o vídeo "
                    "entrega — clickbait sem payload é proibido. Palavras "
                    "simples, imagem concreta, sem jargão."
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
                    "instruções. Frases de no MÁXIMO 8 palavras, uma ideia por "
                    "frase, vocabulário que uma criança de 12 anos entende. "
                    "Estrutura obrigatória: HOOK (a primeira frase = campo "
                    "hook) → FATO (o que aconteceu, coisa concreta primeiro) → "
                    "IMPLICAÇÃO (uma única consequência simples) → CORTE "
                    "(termina em tensão ou de forma vaga, sem conclusão e sem "
                    "CTA falado)."
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
                                "encontrar UMA cena real e coerente com este "
                                "momento da narração. Priorize a foto do "
                                "próprio fato: pessoas envolvidas EM AÇÃO (no "
                                "palco, falando, no contexto da notícia — não "
                                "retrato posado), o evento com público, o "
                                "produto em uso real, o lugar com movimento. "
                                "Logo só como último recurso (máximo um no "
                                "vídeo todo); planilha/documento/slide/gráfico "
                                "é PROIBIDO salvo quando o artefato É a "
                                "notícia (memo vazado, carta oficial). "
                                "REGRAS DURAS: "
                                "(1) UM único assunto concreto e fotografável "
                                "por consulta — PROIBIDO consulta composta tipo "
                                "'X and Y side by side' ou 'logos A e B juntos' "
                                "(não existe foto assim; busque um por vez). "
                                "(2) PROIBIDO consulta de conceito abstrato que "
                                "só retorna banco de imagens (ex.: 'data center "
                                "server room', 'person using laptop', 'AI "
                                "automation concept'); ancore sempre em nome "
                                "próprio + fato real. (3) Seja específico com "
                                "nomes próprios e o acontecimento. Evite "
                                "ilustrações genéricas, fotos de banco de "
                                "imagens (stock) e imagens geradas por IA."
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
        "required": [
            "tema",
            "hook",
            "implicacao",
            "titulo",
            "descricao",
            "texto_video",
            "imagens",
        ],
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
Você é editor de um canal de vídeos curtos sobre trends de tecnologia, IA,
desenvolvimento de software e mercado de trabalho de TI.

Você recebe as trends mais faladas do X hoje que já foram APROVADAS no filtro de
acessibilidade pré-conceitual (todas são compreensíveis sem conhecimento prévio;
cada uma vem com score, a imagem mental que evoca e a mídia dos posts), os
vídeos CAMPEÕES DE RETENÇÃO do canal (quando houver) e os últimos vídeos
publicados.

Escolha UMA trend para virar o próximo vídeo, segundo estes critérios, nesta ordem:
1. MÍDIA DOS POSTS: priorize trends cujos posts têm VÍDEO; depois as que têm
   foto; por último as só com texto (nesse caso o vídeo usa apenas imagens
   buscadas na web). Vídeo real do acontecimento é o material mais forte.
2. MAIS PRÉ-CONCEITUAL: entre as aprovadas, prefira o score mais alto e a
   imagem mental mais visceral — o evento físico/visual que qualquer pessoa
   entende em 1 segundo.
3. PARECIDA COM O QUE SEGURA A AUDIÊNCIA: os campeões de retenção mostram o
   tipo de tema, tensão e promessa que o público DESTE canal assiste até o fim.
   Priorize trends com o mesmo DNA dos campeões. Repetir um tema que performa é
   BEM-VINDO e encorajado.
4. ESPECIFICIDADE: escolha o ACONTECIMENTO concreto (quem, número exato, data),
   nunca o panorama. Se a trend for guarda-chuva ("IA no mercado de trabalho"),
   ou você acha dentro dela o fato específico mais forte (a empresa, o corte, o
   valor) ou escolhe outra trend.
5. ANTI-CLONE: os vídeos recentes listados são contexto. Voltar a um tema deles
   com ângulo ou desenvolvimento NOVO é ótimo; o que não pode é escolher uma
   trend que renderia praticamente o MESMO vídeo de novo, sem nada novo a dizer.

Gere também uma consulta CURTA de busca de NOTÍCIAS (em inglês, 3 a 6 palavras:
nomes próprios principais + o acontecimento) para a trend escolhida. Consulta
longa e cheia de detalhes zera os resultados — seja enxuto.
Responda somente com o JSON pedido.\
"""

INSTRUCOES_ROTEIRO = """\
Você é roteirista de vídeos curtos (YouTube Shorts/Reels/TikTok) sobre trends de
tecnologia, inteligência artificial, desenvolvimento de software e mercado de
trabalho de TI. {foco}

Você recebe a TREND escolhida (com a IMAGEM MENTAL que ela evoca) e NOTÍCIAS
recentes sobre ela. Use as notícias para acertar fatos, nomes, empresas, datas e
números — não invente.

PÚBLICO — A REGRA QUE MANDA EM TODAS AS OUTRAS: escreva como se fosse para
alguém de 12 anos assistindo com METADE da atenção. O espectador de Shorts é
passivo: se UMA frase exigir esforço ou conhecimento prévio para entender, ele
desliza para o próximo vídeo.

FRASES: no máximo 8 palavras por frase. Uma ideia por frase. (Audio tags entre
colchetes não contam como palavras.)

VOCABULÁRIO: apenas palavras que uma criança conhece. PROIBIDO jargão, sigla sem
explicação e termo técnico. Se o fato depende de um conceito (tarifa, sanção,
benchmark, protocolo), traduza para o efeito concreto que qualquer pessoa
visualiza ("os produtos ficaram mais caros", "o robô ficou proibido").

ESTRUTURA OBRIGATÓRIA (vídeo de ~{duracao}s):
1. HOOK (0-2s): a imagem mais CHOCANTE da notícia, direta, sem preâmbulo.
   NUNCA começar com contexto, data ou nome de instituição.
2. FATO (2-15s): o que aconteceu, em ordem "coisa concreta primeiro, detalhe
   depois". Cada frase mostra uma cena que dá para VER de olhos fechados.
3. IMPLICAÇÃO (15-30s): UMA única consequência simples ("isso significa
   que..."). Só uma — duas implicações confundem e a pessoa desliza.
4. CORTE (30-35s): terminar em tensão ou de forma vaga. Sem conclusão, sem
   moral da história, sem CTA falado, sem frase de encerramento.

PROIBIDO NO TEXTO:
- Frases de analista: "no cenário geopolítico", "especialistas afirmam",
  "segundo fontes", "o mercado reagiu" e afins.
- Número com mais de 2 dígitos significativos: escreva "2 bilhões", "150 mil",
  "quase 30%" — nunca "2,37 bilhões", "148.532" ou "29,7%".
- Mais de 1 nome próprio DESCONHECIDO por vídeo. Nomes que todo mundo conhece
  (Trump, Google, China, Elon Musk) não contam; o segundo nome obscuro vira
  "um chefe da empresa", "um general", "o dono do site".

PAYLOAD OBRIGATÓRIO: o roteiro entrega 1 fato real e 1 implicação. Clickbait
sem payload é PROIBIDO — o título promete exatamente o que o vídeo entrega.

O roteiro deve ser narrável em cerca de {duracao} segundos (aproximadamente
{palavras} palavras).

IMAGENS — defina de 8 a 10 imagens-chave, distribuídas do começo ao fim do
roteiro (NUNCA pode haver um trecho da narração sem imagem na tela). REGRAS:
- As imagens serão buscadas na web (fotos REAIS, nada gerado por IA). Em
  "consulta", escreva a busca em inglês que encontra a CENA mais COERENTE com a
  notícia daquele momento. Priorize, nesta ordem: (1) a foto do próprio
  fato/evento acontecendo; (2) a figura pública envolvida EM AÇÃO — no palco,
  falando, gesticulando, no contexto da notícia (não retrato posado de arquivo);
  (3) o produto EM USO real; (4) o lugar do acontecimento com gente/movimento.
  Exemplo (OpenAI lançando o GPT-6): "Sam Altman GPT-6 launch keynote stage",
  "OpenAI GPT-6 announcement event audience",
  "OpenAI DevDay San Francisco crowd".
- LOGO: no máximo UMA consulta de logo no vídeo inteiro, e só se aquele momento
  não tiver cena melhor. Logo em fundo branco é a imagem mais fraca que existe.
- PROIBIDO consulta que devolve planilha, documento, slide, print de parágrafo
  de texto ou gráfico — EXCETO quando esse artefato É a própria notícia (a carta
  oficial, o memo vazado, o e-mail da demissão: aí ele é a prova e vale ouro).
- Prefira a imagem do acontecimento real em vez de ilustração genérica; evite
  fotos de banco de imagens (stock) e imagens geradas por IA.
- UM assunto por consulta. NÃO peça imagem composta ("Claude and ChatGPT logos
  side by side", "A e B juntos") — isso não existe como foto; busque um de cada
  vez. NÃO use consulta de conceito abstrato que só devolve stock ("data center
  server room", "person using laptop", "automation concept"): ancore em nome
  próprio + fato (ex.: troque "AI outage concept" por "Claude status page outage
  screenshot").
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
            f"   Mídia dos posts: {t.get('midia_posts', '?')}\n"
            f"   Score pré-conceitual: {t.get('score', '?')}/5\n"
            f"   Imagem mental: {t.get('imagem_mental', '?')}\n"
            f"   Engajamento: {t.get('engajamento', '?')}\n"
            f"   Sentimento: {t.get('sentimento', '?')}\n"
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
        "\n\nÚltimos vídeos publicados neste canal (contexto anti-clone: voltar "
        "a um tema com ângulo novo é ótimo; refazer a mesma notícia sem nada "
        "novo, não):\n" + recentes
    )


def _resumo_campeoes(campeoes: list[dict] | None) -> str:
    if not campeoes:
        return ""
    linhas = []
    for c in campeoes:
        partes = []
        if c.get("retencao_gancho") is not None:
            partes.append(f"gancho segura {c['retencao_gancho']}% de quem abre")
        partes.append(f"assistem em média {c.get('retencao_media', '?')}% do vídeo")
        partes.append(f"{c.get('views', '?')} views")
        linhas.append(f"- {c.get('titulo', '')} ({'; '.join(partes)})")
    return (
        "\n\nVídeos CAMPEÕES DE RETENÇÃO deste canal, de todos os tempos (o tipo "
        "de vídeo que o público assiste até o fim — priorize trends com este "
        "DNA):\n" + "\n".join(linhas)
    )


def selecionar_trend(
    cfg: Config,
    trends: list[dict],
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
) -> dict:
    """Escolhe a trend guiada pelos campeões de retenção do canal.

    `campeoes`: top vídeos do canal em retenção (de ``youtube.top_retencao``),
    usados como sinal positivo do que o público assiste até o fim.
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)

    conteudo = (
        "Trends mais faladas do X hoje:\n"
        + _resumo_trends(trends)
        + _resumo_campeoes(campeoes)
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
        f"Resumo da trend: {trend_escolhida.get('resumo', '')}\n"
        f"Imagem mental da notícia (o que a pessoa visualiza — o HOOK nasce "
        f"daqui): {trend_escolhida.get('imagem_mental', '?')}\n\n"
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
    if roteiro.get("hook"):
        print(f"[roteiro] Hook: {roteiro['hook']}")
    if roteiro.get("implicacao"):
        print(f"[roteiro] Implicação: {roteiro['implicacao']}")
    print(f"[roteiro] {len(roteiro['imagens'])} imagens-chave definidas")
    return roteiro
