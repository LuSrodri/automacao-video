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
            "sentimento": {
                "type": "string",
                "description": (
                    "A emoção DOMINANTE em volta da trend (ex.: indignação, medo, "
                    "deboche, euforia, ceticismo, fascínio) e, em uma frase, o "
                    "ângulo que o vídeo vai assumir por causa dela. Decida ISTO "
                    "PRIMEIRO: é o que dirige o tom da narração, a ênfase dos "
                    "fatos e onde fica o clímax."
                ),
            },
            "ganchos_candidatos": {
                "type": "array",
                "minItems": 4,
                "maxItems": 6,
                "items": {"type": "string"},
                "description": (
                    "ANTES de escrever o roteiro, gere de 4 a 6 PRIMEIRAS FRASES "
                    "(ganchos) bem DIFERENTES entre si, cada uma atacando o tema "
                    "por um ângulo distinto (o segredo escondido, a virada "
                    "contraintuitiva, o número-enigma, a consequência alarmante). "
                    "Cada uma DEVE abrir uma lacuna de curiosidade e plantar FOMO "
                    "sem entregar a resposta. Trate como rascunho de divergência: "
                    "varie de verdade, não escreva 5 versões da mesma frase."
                ),
            },
            "gancho_escolhido": {
                "type": "string",
                "description": (
                    "O gancho que deixa a MAIOR pergunta no ar — o que entrega "
                    "MENOS e gera mais necessidade de descobrir; NÃO o mais "
                    "completo ou dramático. Não pode conter o segredo da história "
                    "nem um veredito de conclusão. A primeira frase de texto_video "
                    "DEVE ser exatamente este gancho (copiado palavra por palavra, "
                    "antes de qualquer audio tag)."
                ),
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
                                "e foto do local/lugar relevante. REGRAS DURAS: "
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
            "sentimento",
            "ganchos_candidatos",
            "gancho_escolhido",
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

Você recebe as trends mais faladas do X hoje (cada uma com resumo, engajamento e
uma nota de apelo visual), os vídeos CAMPEÕES DE RETENÇÃO do canal (quando
houver) e os últimos vídeos publicados.

Escolha UMA trend para virar o próximo vídeo, segundo estes critérios, nesta ordem:
1. PARECIDA COM O QUE SEGURA A AUDIÊNCIA: os campeões de retenção mostram o
   tipo de tema, tensão e promessa que o público DESTE canal assiste até o fim.
   Priorize trends com o mesmo DNA dos campeões. Repetir um tema que performa é
   BEM-VINDO e encorajado.
2. MAIOR chance de viralizar (impacto, polêmica, novidade, curiosidade) E maior
   APELO VISUAL — assuntos com pessoas conhecidas, produtos, eventos e lugares
   que rendem boas imagens reais.
3. ANTI-CLONE: os vídeos recentes listados são contexto. Voltar a um tema deles
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

Você recebe a TREND escolhida para o vídeo e NOTÍCIAS recentes sobre ela. Use as
notícias para acertar fatos, nomes, empresas, datas e números — não invente.

REGRA DE OURO — ONDE MORA O APELO: curiosidade e FOMO vivem QUASE INTEIRAMENTE no
gancho (os ~3 primeiros segundos e a primeira frase). Não no vídeo todo, não no
visual, não no ritmo. Vivem na PROMESSA INICIAL. O resto do roteiro só existe pra
pagar a dívida que o gancho criou. Se o gancho for morno, nada salva o vídeo.

O nome do jogo é criar uma LACUNA DE CURIOSIDADE: dizer o suficiente pra pessoa
QUERER saber, e esconder o suficiente pra ela TER QUE FICAR pra descobrir. O
gancho não informa — ele provoca.

A ESTRUTURA É DE HISTÓRIA, NÃO DE MANCHETE: um vídeo bom se desenrola como um
filme — tem começo, meio e clímax. O gancho NÃO é o resumo da notícia: é a PORTA
DE ENTRADA que faz a pessoa perguntar algo específico ("por quê?", "como?", "o
quê?"). O gancho PODE dizer o RESULTADO chocante (ex.: "Dois modelos da Anthropic
sumiram do mundo inteiro") — isso é ótimo, porque dispara na hora o "por quê?". O
que o gancho NÃO pode fazer é já entregar a EXPLICAÇÃO. A explicação é o que o
corpo constrói, em ordem, até o clímax.

ERRO QUE MATA O VÍDEO (assistir o filme pelo final): disparar o "por quê?" no
gancho e respondê-lo no soco seguinte. Ex.: "Dois modelos sumiram... foi uma
ordem do governo." Aí não houve jornada nenhuma — você contou o desfecho. O
certo é: depois do gancho, CONTEXTUALIZAR e contar a história ATÉ chegar na
explicação e no clímax.

NO GANCHO É PROIBIDO: explicar/responder a pergunta que ele abre, colocar o
veredito ("isso muda tudo", "é assustador"), e ser longo. Gancho é CURTÍSSIMO —
uma frase de um fôlego (~6 a 12 palavras).
- RUIM (longo + já com veredito): "Uma decisão em Washington apagou dois modelos
  da Anthropic no planeta inteiro e isso abre um precedente assustador."
- BOM (curto, dispara o porquê): "Dois modelos da Anthropic sumiram do mundo
  inteiro de uma vez."
- BOM (detalhe estranho como porta de entrada): "A Anthropic recebeu uma carta
  que não podia ignorar."

TESTE DO GANCHO: ele deixa UMA pergunta clara no ar e cabe num fôlego? Se já
explica, traz veredito ou precisa de vírgulas pra respirar, reescreva.

FOMO: a sensação de "todo mundo vai saber disso, menos eu, se eu deslizar". O
gancho tem que plantar que isso é grande, que já está acontecendo, e que ficar de
fora é o vexame. Use sinais de urgência e de "manada" quando forem verdadeiros
(já viralizou, todo mundo está testando, mudou as regras do jogo da noite pro
dia).

PROCESSO OBRIGATÓRIO — NÃO ESCREVA O PRIMEIRO GANCHO QUE VIER À CABEÇA:
1. Primeiro, preencha "ganchos_candidatos" com 4 a 6 primeiras frases bem
   diferentes, cada uma por um ângulo distinto (use as 4 formas abaixo). O
   primeiro gancho que vem à cabeça é quase sempre o mais óbvio e morno — o ouro
   costuma estar no 4º ou 5º. Force a variação.
2. Depois, escolha em "gancho_escolhido" o candidato mais CURTO e claro que
   dispara uma pergunta específica ("por quê?", "como?"). Descarte na hora os que
   já explicam, trazem veredito de conclusão ou precisam de vírgula pra respirar.
3. Só então escreva o "texto_video" começando EXATAMENTE por esse gancho.

ARMAS PRA AFIAR O GANCHO (use no candidato, não no clichê):
- ESPECIFICIDADE vence vagueza: nome próprio + detalhe concreto pega mais que
  abstração ("o app que a OpenAI lançou" < "o app que a OpenAI lançou e tirou do
  ar em 6 horas").
- Number-gap: jogue o número absurdo como enigma ("ganhou 1 milhão de usuários
  num fim de semana — e foi aí que o problema começou").
- Resultado chocante como porta: abra pelo efeito que faz perguntar "por quê?"
  (mas sem explicar — a explicação é o corpo).
- Nomeie o inimigo/aposta: quem perde, quem ganha, o que está em jogo.
- Curto. Gancho longo dilui. Mire em uma frase que caiba em um fôlego.
EVITE clichê de IA e enchimento: "num mundo cada vez mais...", "a tecnologia
avança...", "imagine que...", "você não vai acreditar". São mortos.

Escreva o roteiro narrado (campo texto_video) seguindo a CURVA DE RETENÇÃO de um
vídeo curto que precisa segurar a pessoa até o fim:

1. GANCHO (primeiros ~3 segundos): curtíssimo, uma frase de um fôlego, que
   dispara uma pergunta específica na cabeça do espectador. Pode ser o resultado
   chocante, um detalhe estranho como porta de entrada, um número-enigma ou uma
   virada contraintuitiva. PROIBIDO: explicar/responder a pergunta, "Hoje vamos
   falar sobre...", veredito de conclusão, e frases longas.
2. DESENVOLVIMENTO (a história se desenrolando): o gancho disparou um "por quê?".
   NÃO responda de cara. Primeiro CONTEXTUALIZE e conte a história EM ORDEM
   (cronológica/causal), construindo até a explicação. Pense em cenas encadeadas
   por causa e efeito:
   - SETUP: a situação inicial / o que existia antes ("a Anthropic lançou o Mythos
     5 e o Fable 5 no dia tal...").
   - ESTOPIM: o que disparou tudo ("72 horas depois, alguém já tinha feito um
     jailbreak num deles, usando uma função de achar falhas em código...").
   - ESCALADA: a reação em cadeia, um fato puxando o outro ("isso acendeu o alarme
     no governo dos EUA, que por controle de exportação proibiu o uso por
     estrangeiros... só que a Anthropic não conseguia bloquear em tempo real, e
     pra obedecer teve que desligar pra TODO MUNDO").
   Cada frase é um novo passo da história, ligado por "aí...", "X horas depois...",
   "isso obrigou...", "só que...". Ritmo RÁPIDO, sem frase morta. A retenção vem do
   ENREDO andando e dos stakes subindo — NÃO de enrolar ou esconder a resposta com
   teasing vazio. A pessoa fica porque a história está acontecendo, não porque você
   prometeu um segredo e ficou empurrando com a barriga.
3. CLÍMAX E FECHO (final): a história chega no ponto mais alto — o quadro completo,
   a virada de maior impacto, o "tamanho" real do que aconteceu. Logo depois, UMA
   frase de consequência/sentido que aterrissa o peso disso. NÃO SINALIZE QUE ESTÁ
   ACABANDO; o vídeo não pode "desligar". A última frase é uma AFIRMAÇÃO SECA e
   para ali. PROIBIDO terminar com PERGUNTA de qualquer tipo (CTA "e você, o que
   acha?" ou retórica), pedir like/comentário, ou usar frases de encerramento ("no
   fim das contas", "então é isso", "enfim"). Sem ponto de interrogação na frase
   final. Melhor ainda: feche reconectando com o gancho (loop), sem nunca dizer
   que terminou.

TOM GUIADO PELO SENTIMENTO: o campo "sentimento" diz qual é a emoção dominante da
trend (ex.: indignação, medo, deboche, euforia, ceticismo, fascínio). É ELE que
dirige o vídeo: o ângulo da história, quais fatos você enfatiza, onde está o
clímax e a entrega da narração (as audio tags). Indignação pede tom de denúncia;
medo, tom de alerta; deboche, ironia; fascínio, deslumbre. Um roteiro sem emoção
clara fica neutro e CHATO — comprometa-se com o sentimento do começo ao fim.

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
        f"Sentimento em volta da trend (clima dos posts no X): "
        f"{trend_escolhida.get('sentimento', '?')}\n\n"
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
    if roteiro.get("sentimento"):
        print(f"[roteiro] Sentimento/ângulo: {roteiro['sentimento']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    if roteiro.get("ganchos_candidatos"):
        print(
            f"[roteiro] {len(roteiro['ganchos_candidatos'])} ganchos testados; "
            f"escolhido: {roteiro.get('gancho_escolhido', '')}"
        )
    print(f"[roteiro] {len(roteiro['imagens'])} imagens-chave definidas")
    return roteiro
