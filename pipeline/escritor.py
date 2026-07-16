"""Seleção da trend do dia e geração de título, descrição e roteiro do vídeo.

Duas etapas:
1. `selecionar_trend` — entre as trends já APROVADAS no score de acessibilidade
   pré-conceitual (pontuacao.py), escolhe a melhor priorizando posts com VÍDEO,
   depois com foto e por último só texto (evitando repetir vídeos recentes; o
   tema do ÚLTIMO vídeo publicado é vetado em qualquer hipótese), e devolve uma
   consulta de notícias para enriquecer o material.
2. `gerar_roteiro` — com a trend escolhida + notícias do Firecrawl, escreve o
   roteiro pré-conceitual em tom adulto (frases curtas, vocabulário leigo,
   estrutura HOOK → FATO → IMPLICAÇÃO → CORTE em loop) e define de 8 a 10
   imagens-chave.
"""

import json
import re

from openai import OpenAI

from .config import Config

# Ritmo real médio da narração do ElevenLabs (medido nas narrações do canal:
# ~2,1 a 2,5 palavras faladas por segundo, já sem os silêncios). Converte a
# duração-alvo do .env (VIDEO_DURACAO) no teto de palavras do roteiro.
PALAVRAS_POR_SEGUNDO = 2.3
# Tolerância sobre o teto de palavras antes de pedir ao modelo para encurtar.
FOLGA_PALAVRAS = 1.15

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
                    "repita os vídeos recentes do canal e que NUNCA tenha o "
                    "mesmo tema do ÚLTIMO vídeo publicado (proibição absoluta)."
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
                    "instruções. Frases curtas (mire em 8 palavras, máximo "
                    "12), uma ideia por frase, vocabulário do dia a dia de um "
                    "adulto leigo — tom adulto e urgente, nunca infantil. "
                    "Estrutura obrigatória: HOOK (a primeira frase = campo "
                    "hook) → FATO (o que aconteceu, coisa concreta primeiro) → "
                    "IMPLICAÇÃO (uma única consequência simples) → CORTE "
                    "(termina em tensão emendando de volta no hook — o vídeo "
                    "roda em loop — sem conclusão e sem CTA falado). A última "
                    "frase deve ser NOVA: é PROIBIDO repetir o hook (ou "
                    "qualquer frase anterior) palavra por palavra — quem "
                    "repete o hook é o reinício do loop, não o texto."
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
4. COMPARTILHÁVEL: em empate, vença a notícia que um profissional de tech
   mandaria para um colega com "viu isso?" — corte de empregos com número,
   dinheiro grande mudando de mão, decisão que afeta quem trabalha com
   tecnologia. Share é o que multiplica a distribuição no feed, e é esse tipo
   de notícia que gera share neste canal.
5. ESPECIFICIDADE: escolha o ACONTECIMENTO concreto (quem, número exato, data),
   nunca o panorama. Se a trend for guarda-chuva ("IA no mercado de trabalho"),
   ou você acha dentro dela o fato específico mais forte (a empresa, o corte, o
   valor) ou escolhe outra trend.
6. ANTI-CLONE: os vídeos recentes listados são contexto. Voltar a um tema deles
   com ângulo ou desenvolvimento NOVO é ótimo; o que não pode é escolher uma
   trend que renderia praticamente o MESMO vídeo de novo, sem nada novo a dizer.

REGRA ABSOLUTA — VETO AO ÚLTIMO VÍDEO: é PROIBIDO escolher uma trend com o
MESMO tema do ÚLTIMO vídeo publicado (o marcado como "ÚLTIMO PUBLICADO" na
lista). Essa proibição vence TODOS os critérios acima, inclusive o critério 3:
nem ângulo novo, nem desenvolvimento novo, nem score mais alto justificam dois
vídeos SEGUIDOS sobre o mesmo tema. Mesma empresa/pessoa/produto no centro do
mesmo acontecimento = mesmo tema. Se a trend mais forte cair nesse veto,
escolha a segunda mais forte.

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

PÚBLICO — A REGRA QUE MANDA EM TODAS AS OUTRAS: escreva para um ADULTO leigo
(o espectador real do canal: homem de 25 a 54 anos, curioso por tecnologia,
sem formação técnica) assistindo com METADE da atenção. O espectador de Shorts
é passivo: se UMA frase exigir esforço ou conhecimento prévio para entender,
ele desliza para o próximo vídeo.

TOM: adulto e urgente — como quem conta um furo de notícia a um amigo, com
autoridade seca. Simples NÃO é infantil: PROIBIDO tom didático de professor,
entusiasmo fofo, moral da história e qualquer frase que soaria natural num
desenho animado. Se a frase parece escrita para criança, reescreva como um
âncora de telejornal falaria num corte de 30 segundos.

FRASES: curtas e diretas — mire em 8 palavras, nunca passe de 12. Uma ideia por
frase. Varie o ritmo: só frases mínimas em sequência soa robótico e infantil;
alterne frases de 3-4 palavras com frases mais cheias. (Audio tags entre
colchetes não contam como palavras.)

VOCABULÁRIO: palavras do dia a dia, que qualquer adulto leigo entende sem parar
para pensar. PROIBIDO jargão, sigla sem explicação e termo técnico. Se o fato
depende de um conceito (tarifa, sanção, benchmark, protocolo), traduza para o
efeito concreto que qualquer pessoa visualiza ("os produtos ficaram mais
caros", "o robô ficou proibido").

ESTRUTURA OBRIGATÓRIA (narração de ~{duracao}s):
1. HOOK (0-2s): a imagem mais CHOCANTE da notícia, direta, sem preâmbulo.
   NUNCA começar com contexto, data ou nome de instituição. O hook decide o
   "viewed vs swiped": metade do público desliza no primeiro segundo — esta
   frase e a primeira imagem valem mais que todo o resto do vídeo.
2. FATO (até a metade do vídeo): o que aconteceu, em ordem "coisa concreta
   primeiro, detalhe depois". Cada frase mostra uma cena que dá para VER de
   olhos fechados.
3. IMPLICAÇÃO (segunda metade): UMA única consequência simples ("isso significa
   que..."). Só uma — duas implicações confundem e a pessoa desliza.
4. CORTE (últimos 2-3s): terminar em tensão. Sem conclusão, sem moral da
   história, sem CTA falado, sem frase de encerramento. O Shorts REINICIA
   sozinho: a última frase deve emendar na primeira (o hook) como se a história
   continuasse — o loop bem feito faz a pessoa assistir de novo sem perceber,
   e replay multiplica a distribuição. EMENDAR NÃO É REPETIR: é PROIBIDO
   copiar o hook (ou qualquer frase já dita) no final do texto — escreva uma
   frase NOVA de tensão que, quando o vídeo reiniciar, desemboque naturalmente
   no hook.

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

DURAÇÃO — a narração deve caber em {duracao} segundos: escreva NO MÁXIMO
{palavras} palavras faladas no texto_video (audio tags entre colchetes não
contam). O limite é DURO, não uma sugestão: estourar alonga o vídeo e derruba a
retenção. Se faltar espaço, corte detalhes do FATO — nunca o hook, a implicação
única nem o corte final.

IMAGENS — defina de 8 a 10 imagens-chave, distribuídas do começo ao fim do
roteiro (NUNCA pode haver um trecho da narração sem imagem na tela). REGRAS:
- A PRIMEIRA imagem é a mais importante do vídeo: ela é o primeiro frame que a
  pessoa vê no feed e decide o "viewed vs swiped" junto com o hook. Reserve
  para ela a cena real mais forte e chocante da notícia — nunca logo, nunca
  retrato posado, nunca imagem "de contexto".
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
    linhas = []
    for i, v in enumerate(videos_recentes):
        marca = " [ÚLTIMO PUBLICADO — tema VETADO no próximo vídeo]" if i == 0 else ""
        linhas.append(f"- ({v.get('data') or '?'}) {v.get('titulo', '')}{marca}")
    return (
        "\n\nÚltimos vídeos publicados neste canal, do mais recente para o mais "
        "antigo (contexto anti-clone: voltar a um tema com ângulo novo é ótimo; "
        "refazer a mesma notícia sem nada novo, não — e o tema do ÚLTIMO "
        "PUBLICADO é proibido em qualquer hipótese):\n" + "\n".join(linhas)
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


def _contar_palavras(texto: str) -> int:
    """Palavras faladas do roteiro (audio tags entre colchetes não contam)."""
    return len(re.sub(r"\[[^\]]*\]", " ", texto).split())


def _aparar_hook_final(roteiro: dict) -> None:
    """Remove o hook repetido literalmente no fim do texto_video.

    O loop emenda no hook do REINÍCIO do vídeo; quando o modelo copia o hook
    no final da narração, o gancho fica duplicado e o trecho da última imagem
    passa a existir duas vezes no texto, desalinhando os cortes.
    """
    hook = (roteiro.get("hook") or "").strip()
    texto = (roteiro.get("texto_video") or "").rstrip()
    if not hook or not texto:
        return
    baixo, alvo = texto.lower(), hook.lower()
    ultima = baixo.rfind(alvo)
    if ultima <= baixo.find(alvo):
        return  # o hook só aparece na abertura — nada a aparar
    cauda = re.sub(r"\[[^\]]*\]", "", texto[ultima + len(hook):])
    if cauda.strip(" \t\n.!?…"):
        return  # a repetição não está no fim do texto
    novo = re.sub(r"(?:\s*\[[^\]]*\])*\s*$", "", texto[:ultima])
    if novo:
        roteiro["texto_video"] = novo
        print(
            "[roteiro] Hook repetido no fim do texto removido "
            "(o loop emenda no reinício, não dentro da narração)."
        )


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

    limite = int(cfg.video_duracao * PALAVRAS_POR_SEGUNDO)
    instrucoes = INSTRUCOES_ROTEIRO.format(
        foco=FOCO_USA if cfg.publico == "usa" else FOCO_BRASIL,
        duracao=cfg.video_duracao,
        palavras=limite,
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
    _aparar_hook_final(roteiro)

    # Teto de palavras: o TTS cobra por caractere e vídeo longo mata a
    # retenção, então um estouro grande merece UMA nova tentativa pedindo corte.
    palavras = _contar_palavras(roteiro["texto_video"])
    if palavras > limite * FOLGA_PALAVRAS:
        print(
            f"[roteiro] texto_video com {palavras} palavras faladas "
            f"(máximo {limite}); pedindo versão mais curta..."
        )
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
                {"role": "assistant", "content": resposta.choices[0].message.content},
                {
                    "role": "user",
                    "content": (
                        f"O texto_video ficou com {palavras} palavras faladas; "
                        f"o máximo é {limite}. Reescreva o JSON completo "
                        "cortando detalhes do FATO (mantenha o hook, a "
                        "implicação única e o corte final em tensão) até caber "
                        "no limite, e ajuste os trechos das imagens para "
                        "continuarem substrings exatas do novo texto_video."
                    ),
                },
            ],
            response_format={"type": "json_schema", "json_schema": ESQUEMA_ROTEIRO},
        )
        encurtado = json.loads(resposta.choices[0].message.content)
        _aparar_hook_final(encurtado)
        if _contar_palavras(encurtado["texto_video"]) < palavras:
            roteiro = encurtado
        palavras = _contar_palavras(roteiro["texto_video"])
    print(f"[roteiro] {palavras} palavras faladas (alvo <= {limite})")
    print(f"[roteiro] Tema do dia: {roteiro['tema']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    if roteiro.get("hook"):
        print(f"[roteiro] Hook: {roteiro['hook']}")
    if roteiro.get("implicacao"):
        print(f"[roteiro] Implicação: {roteiro['implicacao']}")
    print(f"[roteiro] {len(roteiro['imagens'])} imagens-chave definidas")
    return roteiro
