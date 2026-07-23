"""Seleção da trend do dia e geração de título, descrição e roteiro do vídeo.

Duas etapas:
1. `selecionar_trend` — escolha guiada SOMENTE pela audiência (diretriz de
   2026-07-18: sem pesos nem filtros editoriais): o modelo recebe as
   candidatas do dia, os últimos vídeos publicados COM as métricas reais
   (views/likes da Data API) e os campeões de retenção, e escolhe a trend com
   a maior chance de performar com o público DESTE canal. Duas regras duras,
   aplicadas em código: o teto de MAX_MACROTEMA_SEGUIDOS vídeos seguidos do
   mesmo macrotema (antes da seleção) e a verificação de vídeo repetido
   (depois dela): uma chamada ao GPT confere se a escolhida cobriria o mesmo
   fato de um vídeo publicado nas últimas JANELA_REPETICAO_HORAS — se sim, a
   candidata sai da disputa e a seleção refaz (com 3-4 execuções/dia sobre a
   mesma janela de posts do X, a ressalva só no prompt deixava passar o mesmo
   fato reformulado). Devolve também uma consulta de notícias para enriquecer
   o material.
2. `gerar_roteiro` — com a trend escolhida + notícias do Firecrawl, escreve o
   roteiro em enquadramento de ANÁLISE/EDUCACIONAL (formato explicativo), em
   tom adulto e inteligente (ritmo de fala natural, vocabulário preciso de
   telejornal, estrutura HOOK → FATO → IMPLICAÇÃO → CORTE em loop), SEMPRE
   citando as fontes (contas do X e veículos das notícias do Firecrawl),
   dentro de uma FAIXA dura de palavras (piso e teto derivados de
   VIDEO_DURACAO — o teto sozinho deixava o vídeo sair com metade da
   duração-alvo) e define de 8 a 10 imagens-chave.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from openai import OpenAI

from .classificacao import MACROTEMAS, MACROTEMAS_DESCRICAO
from .config import Config

# Ritmo real médio da narração do ElevenLabs (medido nas narrações do canal:
# ~2,1 a 2,5 palavras faladas por segundo, já sem os silêncios). Converte a
# duração-alvo do .env (VIDEO_DURACAO) no teto de palavras do roteiro.
PALAVRAS_POR_SEGUNDO = 2.3
# Piso de palavras como fração do teto: o teto sozinho deixava o modelo
# entregar metade das palavras e o vídeo sair com metade da duração-alvo.
FRACAO_MINIMA = 0.85
# Tolerância sobre o teto de palavras antes de pedir ao modelo para encurtar.
FOLGA_PALAVRAS = 1.15
# Teto de vídeos SEGUIDOS do mesmo macrotema (diretriz 2026-07-18): a seleção
# segue somente a audiência, mas o mesmo macrotema não pode emendar mais que
# isso — é a única regra de variabilidade do canal.
MAX_MACROTEMA_SEGUIDOS = 4
# Janela da verificação de vídeo repetido: vídeo publicado há menos que isto
# cobre a mesma janela de posts do X das execuções seguintes (JANELA_HORAS=24
# + folga), então a candidata só passa se o resumo dela tiver fato novo. Mais
# antigo que isso, qualquer desenvolvimento já é naturalmente novo.
JANELA_REPETICAO_HORAS = 36

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
                    "A trend escolhida entre as listadas: a com a maior chance "
                    "de performar com a audiência DESTE canal, a julgar pelas "
                    "métricas reais dos vídeos recentes e dos campeões de "
                    "retenção."
                ),
            },
            "motivo": {
                "type": "string",
                "description": (
                    "Uma frase justificando a escolha COM BASE nas métricas "
                    "reais do canal (que vídeos parecidos performaram e como)."
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
                    "caracteres. Direto e factual: ator + ação concreta, com "
                    "pelo menos uma coisa palpável (número, pessoa, dinheiro, "
                    "lugar, ação física). TESTE DO LEIGO: o título tem que ser "
                    "entendido por quem NUNCA ouviu falar da empresa ou do "
                    "modelo — no máximo 1 nome próprio, e só se universalmente "
                    "conhecido (Trump, Google, Irã); nome de nicho (modelo de "
                    "IA, lab, startup, sigla) fica FORA do título: traduza "
                    "para o efeito concreto em gente, dinheiro ou ação. "
                    "PROIBIDO cauda de suspense ('— e o detalhe muda tudo', "
                    "'here's why it matters', 'e agora?'): esconder o fato de "
                    "quem não conhece o assunto não gera clique, gera deslize. "
                    "O título promete EXATAMENTE o que o vídeo entrega — "
                    "clickbait sem payload é proibido."
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
                    "instruções. Ritmo de fala natural (frases de 8 a 16 "
                    "palavras, teto 20, alternando curtas de impacto com mais "
                    "cheias), vocabulário preciso de telejornal — tom adulto "
                    "e inteligente, nunca infantil nem robótico. "
                    "Enquadramento explicativo (análise/educacional) e "
                    "citação de fonte obrigatória: o fato central é atribuído "
                    "nominalmente ao veículo ou à conta do X de onde veio "
                    "(somente fontes das listas recebidas). "
                    "Estrutura obrigatória: HOOK (a primeira frase = campo "
                    "hook) → FATO (o que aconteceu, coisa concreta primeiro; "
                    "se o assunto central for de nicho, a primeira frase do "
                    "FATO ancora o assunto em algo que o leigo conhece — 'a "
                    "empresa por trás do ChatGPT') → "
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
                                "Logo, logomarca ou logotipo é PROIBIDO em "
                                "qualquer consulta (a marca sozinha não é "
                                "cena); planilha/documento/slide/gráfico "
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

ESQUEMA_REPETICAO = {
    "name": "verificacao_video_repetido",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "mesmo_fato": {
                "type": "boolean",
                "description": (
                    "true SOMENTE se a pauta candidata cobre o mesmo fato "
                    "central de um dos vídeos já publicados, sem nenhum "
                    "desenvolvimento novo nomeável no resumo dela."
                ),
            },
            "video_repetido": {
                "type": "string",
                "description": (
                    "Título do vídeo publicado que já cobre este fato "
                    "(string vazia quando mesmo_fato é false)."
                ),
            },
        },
        "required": ["mesmo_fato", "video_repetido"],
    },
}

INSTRUCOES_REPETICAO = """\
Você é o verificador anti-repetição de um canal de vídeos curtos de notícias.
Você recebe UMA pauta candidata (com resumo) e os vídeos JÁ PUBLICADOS pelo
canal nas últimas horas (título, descrição e data/hora), e responde se a
candidata renderia um vídeo repetido.

"mesmo_fato" = true SOMENTE quando a candidata cobre o MESMO fato central de
um vídeo listado, sem nenhum desenvolvimento novo NOMEÁVEL no resumo dela.
Desenvolvimento novo é coisa concreta que o vídeo publicado não tinha: novo
ataque, nova declaração, novo número, nova decisão, novo envolvido.
- O mesmo fato reescrito com outras palavras É repetição ("EUA fazem 12ª
  noite seguida de ataques" vs "EUA fazem 12 noites seguidas de ataques").
- O mesmo assunto/conflito com desenvolvimento novo NÃO é repetição
  (cobertura contínua é bem-vinda: a 13ª noite de ataques depois de um vídeo
  sobre a 12ª é vídeo novo).
Responda somente com o JSON pedido.\
"""

ESQUEMA_MACROTEMAS_RECENTES = {
    "name": "macrotemas_videos_recentes",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "macrotemas": {
                "type": "array",
                "items": {"type": "string", "enum": MACROTEMAS},
                "description": (
                    "O macrotema de cada vídeo, na MESMA ordem da lista "
                    "recebida (um item por vídeo)."
                ),
            }
        },
        "required": ["macrotemas"],
    },
}

INSTRUCOES_MACROTEMAS = """\
Classifique cada vídeo publicado (título + descrição) em UM macrotema:
{macrotemas}
Responda somente com o JSON pedido, com um macrotema por vídeo, na mesma ordem
da lista recebida.\
""".format(macrotemas=MACROTEMAS_DESCRICAO)

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
Você é editor de um canal de vídeos curtos (YouTube Shorts) de notícias
quentes.

Você recebe as trends mais faladas do X hoje (cada uma com resumo, macrotema e
imagem mental), os vídeos CAMPEÕES DE RETENÇÃO do canal (quando houver) e os
últimos vídeos publicados COM as métricas reais de audiência (views e likes).
Todo vídeo do canal é EXPLICATIVO — análise ou educacional —, então prefira,
em empate, a candidata que rende a melhor explicação (um acontecimento com
causa, mecanismo e consequência claros).

CRITÉRIO ÚNICO — O QUE A AUDIÊNCIA ESTÁ ASSISTINDO: escolha a trend com a
maior chance de performar com a audiência DESTE canal, e a régua são os
NÚMEROS listados, não opinião editorial. Os vídeos recentes com MAIS views e
os campeões de retenção mostram o tipo de tema, tensão e promessa que este
público clica e assiste até o fim; os vídeos recentes com POUCAS views mostram
o que ele ignora. Compare cada candidata com esses dois grupos e escolha a que
mais se parece com o que está performando. Repetir o tipo de conteúdo que está
dando certo é BEM-VINDO e encorajado — não aplique preferência própria por
tema "nobre", equilíbrio de pauta ou variedade (a variabilidade do canal já é
garantida por uma regra automática fora desta escolha: no máximo 4 vídeos
seguidos do mesmo macrotema).

Única ressalva: não escolha uma candidata que renderia um vídeo IDÊNTICO a um
já publicado, sem nenhum fato novo. Cobertura contínua do mesmo assunto com
desenvolvimento novo (novo ataque, nova declaração, novo número) é bem-vinda —
é exatamente o que a audiência está acompanhando.

Gere também uma consulta CURTA de busca de NOTÍCIAS (em inglês, 3 a 6 palavras:
nomes próprios principais + o acontecimento) para a trend escolhida. Consulta
longa e cheia de detalhes zera os resultados — seja enxuto.
Responda somente com o JSON pedido.\
"""

INSTRUCOES_ROTEIRO = """\
Você é roteirista de vídeos curtos (YouTube Shorts/Reels/TikTok) sobre
geopolítica, inteligência (espionagem, defesa, OSINT), inteligência artificial
e tecnologia. {foco}

Você recebe a TREND escolhida (com a IMAGEM MENTAL que ela evoca), os POSTS DO
X que originaram a trend e NOTÍCIAS recentes sobre ela. Use as notícias para
acertar fatos, nomes, empresas, datas e números — não invente.

ENQUADRAMENTO — SEMPRE análise ou educacional, em formato EXPLICATIVO: o vídeo
explica o que aconteceu, como e por que importa — nunca é um grito de manchete
sem explicação, nunca é opinião militante. A estrutura abaixo (HOOK → FATO →
IMPLICAÇÃO → CORTE) já é o formato explicativo: o FATO mostra o acontecimento
e o mecanismo por trás dele, a IMPLICAÇÃO é a análise (a consequência que o
espectador leva para casa). Explicar NÃO é palestrar: o tom continua de
jornalista afiado, não de professor.

FONTES — OBRIGATÓRIO citar a fonte na narração: todo fato central do vídeo é
atribuído a quem o publicou — o veículo de notícias ("segundo a Reuters", "o
Financial Times revelou") ou a conta do X ("no post de @sentdefender", "Elon
Musk postou"). Cite SOMENTE fontes que estão nas listas recebidas (posts do X
e notícias); cite pelo menos uma, no ponto onde o fato dela entra, embutida na
frase — nunca em bloco de leitura de créditos. Nome de veículo ou de conta
citado como fonte NÃO conta no teto de nomes próprios desconhecidos.

PÚBLICO — A REGRA QUE MANDA EM TODAS AS OUTRAS: escreva para um ADULTO leigo
(o espectador real do canal: homem de 25 a 54 anos, curioso por tecnologia,
sem formação técnica) assistindo com METADE da atenção. O espectador de Shorts
é passivo: se UMA frase exigir esforço ou conhecimento prévio para entender,
ele desliza para o próximo vídeo.

TOM: adulto e inteligente — como um jornalista afiado contando um furo a um
amigo esperto, com autoridade seca. O espectador é leigo, NÃO é burro:
escrever simples é remover barreiras (jargão, sigla, contexto obscuro), nunca
rebaixar o texto. PROIBIDO tom didático de professor, entusiasmo fofo, moral
da história e qualquer frase que soaria natural num desenho animado. Se a
frase parece escrita para criança, reescreva como um âncora de telejornal
falaria num corte de 30 segundos.

FRASES: ritmo de fala natural, de âncora bom de texto — mire em 8 a 16
palavras por frase, teto de 20. Alterne frases curtas de impacto (3 a 6
palavras) com frases mais cheias que carregam o fato: a frase curta só tem
força depois de uma longa. PROIBIDO metralhadora de frases mínimas em
sequência — soa robótico e infantil. Uma ideia central por frase. (Audio tags
entre colchetes não contam como palavras.)

VOCABULÁRIO: preciso e adulto — a palavra certa, nunca a palavra mais boba.
Tudo que um adulto ouve num telejornal ou usa numa conversa de bar está
liberado (bilhões, falência, processo, espionagem, monopólio, resgate...).
PROIBIDO continua sendo: jargão técnico de nicho, sigla sem explicação e
conceito que exige formação para entender. Se o fato depende de um conceito
(tarifa, benchmark, protocolo), não o infantilize: entregue o efeito concreto
em meia frase ("tarifa — o imposto que encarece o produto importado") e siga.

ESTRUTURA OBRIGATÓRIA (narração de ~{duracao}s):
1. HOOK (0-2s): a imagem mais CHOCANTE da notícia, direta, sem preâmbulo.
   NUNCA começar com contexto, data ou nome de instituição. O hook decide o
   "viewed vs swiped": metade do público desliza no primeiro segundo — esta
   frase e a primeira imagem valem mais que todo o resto do vídeo.
2. FATO (até a metade do vídeo): o que aconteceu, em ordem "coisa concreta
   primeiro, detalhe depois". Cada frase mostra uma cena que dá para VER de
   olhos fechados.
   ÂNCORA PARA LEIGO: se o assunto CENTRAL do vídeo não é universalmente
   conhecido (empresa, modelo de IA, app, pessoa de nicho), a PRIMEIRA frase
   do FATO — logo depois do hook, nunca antes dele — amarra o assunto em algo
   que o espectador já conhece: "a empresa por trás do ChatGPT", "o maior
   rival do ChatGPT", "a dona do Instagram". Meia frase embutida na
   narrativa (no máximo duas frases se o assunto for muito distante do dia a
   dia), NUNCA tom de aula ou de glossário. Assunto que todo mundo conhece
   (Trump, guerra, Google, iPhone) NÃO leva âncora — vá direto ao fato:
   âncora desnecessária é preâmbulo, e preâmbulo derruba retenção.
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
- Frases de analista vazias: "no cenário geopolítico", "especialistas
  afirmam", "o mercado reagiu" e afins — e "segundo fontes" SEM nomear a
  fonte (a citação obrigatória é sempre nominal: veículo ou conta do X).
- Número com mais de 2 dígitos significativos: escreva "2 bilhões", "150 mil",
  "quase 30%" — nunca "2,37 bilhões", "148.532" ou "29,7%".
- Mais de 1 nome próprio DESCONHECIDO por vídeo. Nomes que todo mundo conhece
  (Trump, Google, China, Elon Musk) não contam, nem veículo/conta citado como
  fonte; o segundo nome obscuro vira "um chefe da empresa", "um general", "o
  dono do site".

PAYLOAD OBRIGATÓRIO: o roteiro entrega 1 fato real e 1 implicação. Clickbait
sem payload é PROIBIDO — o título promete exatamente o que o vídeo entrega.

TÍTULO — medido nos números do canal: título autossuficiente rende o DOBRO de
views do título com nome de nicho, e os 10 maiores vídeos do canal têm título
direto e factual, sem cauda de suspense. Regras: (1) ator + ação concreta,
com uma coisa palpável (número, pessoa, dinheiro, lugar); (2) TESTE DO LEIGO:
entendível por quem nunca ouviu falar da empresa/modelo — no máximo 1 nome
próprio, só se universalmente conhecido; nome de modelo/lab/startup vira o
efeito concreto ("Rodar IA ficou 10x mais barato", nunca "Anthropic baixou o
preço dos agents"); (3) PROIBIDO cauda de suspense ("— e o detalhe muda
tudo", "here's why it matters", "e agora?").

DURAÇÃO — a narração deve PREENCHER {duracao} segundos: escreva entre
{palavras_min} e {palavras} palavras faladas no texto_video (audio tags entre
colchetes não contam). Os DOIS limites são DUROS: estourar alonga o vídeo e
derruba a retenção; ficar abaixo do mínimo entrega um vídeo raso e curto
demais, que o algoritmo distribui menos. Se faltar espaço, corte detalhes do
FATO — nunca o hook, a implicação única nem o corte final. Se sobrar espaço,
acrescente um detalhe concreto ao FATO (número, nome, cena) — nunca encha
linguiça.

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
- LOGO: PROIBIDO. Nenhuma consulta pode pedir logo, logomarca ou logotipo —
  a marca sozinha não é cena e consultas com essas palavras são descartadas em
  código (o momento fica sem imagem própria). Quando o momento não tiver cena
  óbvia, busque a pessoa envolvida em ação, o produto em uso, a sede/prédio
  com movimento ou o evento — nunca a marca.
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
            f"   Macrotema: {t.get('macrotema', '?')}\n"
            f"   Posts coletados sobre o assunto: {t.get('num_posts', '?')}\n"
            f"   Imagem mental: {t.get('imagem_mental', '?')}\n"
            f"   Engajamento: {t.get('engajamento', '?')}\n"
            f"   Sentimento: {t.get('sentimento', '?')}\n"
            f"   Apelo visual: {t.get('apelo_visual', '?')}"
        )
    return "\n".join(linhas)


def _resumo_recentes(
    videos_recentes: list[dict] | None, macrotemas: list[str] | None = None
) -> str:
    if not videos_recentes:
        return ""
    linhas = []
    for i, v in enumerate(videos_recentes):
        macro = (
            f" [macrotema: {macrotemas[i]}]"
            if macrotemas and i < len(macrotemas)
            else ""
        )
        metricas = f" — {v.get('views', '?')} views, {v.get('likes', '?')} likes"
        linhas.append(
            f"- ({v.get('data') or '?'}) {v.get('titulo', '')}{macro}{metricas}"
        )
    return (
        "\n\nÚltimos vídeos publicados neste canal, do mais recente para o mais "
        "antigo, com as métricas REAIS de audiência (os mais novos ainda estão "
        "acumulando views — compare vídeos de idade parecida). Esta lista é a "
        "régua do que o público deste canal assiste e do que ele ignora:\n"
        + "\n".join(linhas)
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


def _macrotemas_recentes(
    cliente: OpenAI, cfg: Config, videos_recentes: list[dict]
) -> list[str]:
    """Classifica o macrotema de cada vídeo recente do canal (1 chamada).

    A sequência inicial da lista (do mais recente para trás) alimenta o teto
    de MAX_MACROTEMA_SEGUIDOS vídeos seguidos do mesmo macrotema; a lista
    inteira entra no prompt de seleção como contexto. Falha ABORTA
    (fail-fast): sem os macrotemas não existe o teto, e rodar sem ele é o que
    deixa o canal virar monotemático sem ninguém perceber.
    """
    linhas = [
        f"{i}. {v.get('titulo', '')} — {(v.get('descricao') or '')[:200]}"
        for i, v in enumerate(videos_recentes, 1)
    ]
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_MACROTEMAS},
                {"role": "user", "content": "Vídeos publicados:\n" + "\n".join(linhas)},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_MACROTEMAS_RECENTES,
            },
        )
        macros = json.loads(resposta.choices[0].message.content)["macrotemas"]
    except Exception as erro:  # noqa: BLE001 — sem macrotemas não há rotação
        raise SystemExit(
            "Classificação de macrotema dos vídeos recentes falhou (OpenAI) — "
            f"sem ela não existe a rotação de macrotemas; abortando: {erro}"
        ) from erro

    macros = [m if m in MACROTEMAS else "outro" for m in macros]
    macros = macros[: len(videos_recentes)]
    macros += ["outro"] * (len(videos_recentes) - len(macros))
    return macros


def _recentes_na_janela(
    videos_recentes: list[dict] | None, horas: int
) -> list[dict]:
    """Vídeos publicados há menos de `horas` (data/hora UTC da Data API)."""
    corte = datetime.now(timezone.utc) - timedelta(hours=horas)
    dentro = []
    for v in videos_recentes or []:
        try:
            publicado = datetime.fromisoformat(v.get("data") or "").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            dentro.append(v)  # data ilegível: melhor verificar do que deixar passar
            continue
        if publicado >= corte:
            dentro.append(v)
    return dentro


def _candidata_por_nome(candidatas: list[dict], nome: str) -> dict:
    """A trend escolhida pela seleção (por nome, com folga p/ paráfrase)."""
    alvo = nome.strip().lower()
    for t in candidatas:
        if t["trend"].strip().lower() == alvo:
            return t
    for t in candidatas:
        candidato = t["trend"].strip().lower()
        if candidato and (candidato in alvo or alvo in candidato):
            return t
    return candidatas[0]


def _video_repetido(
    cliente: OpenAI, cfg: Config, trend: dict, recentes: list[dict]
) -> str | None:
    """Título do vídeo já publicado que a trend repetiria, ou None.

    Verificação em chamada própria ao GPT porque a ressalva embutida no
    prompt de seleção não segurou na prática: com 3-4 execuções/dia sobre a
    mesma janela de posts do X, o modelo tratava o mesmo fato reformulado
    como desenvolvimento novo. Falha ABORTA (fail-fast): sem a verificação o
    canal volta a publicar o mesmo vídeo duas vezes.
    """
    if not recentes:
        return None
    linhas = [
        f"- ({v.get('data', '?')} UTC) {v.get('titulo', '')}\n"
        f"  Descrição: {(v.get('descricao') or '').strip()[:300]}"
        for v in recentes
    ]
    conteudo = (
        f"PAUTA CANDIDATA: {trend.get('trend', '')}\n"
        f"Resumo: {trend.get('resumo', '')}\n\n"
        f"VÍDEOS PUBLICADOS NAS ÚLTIMAS {JANELA_REPETICAO_HORAS} HORAS:\n"
        + "\n".join(linhas)
    )
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES_REPETICAO},
                {"role": "user", "content": conteudo},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ESQUEMA_REPETICAO,
            },
        )
        veredito = json.loads(resposta.choices[0].message.content)
    except Exception as erro:  # noqa: BLE001 — sem a verificação voltam os clones
        raise SystemExit(
            "Verificação de vídeo repetido falhou (OpenAI) — sem ela o canal "
            f"volta a publicar o mesmo fato duas vezes; abortando: {erro}"
        ) from erro
    if not veredito["mesmo_fato"]:
        return None
    return veredito.get("video_repetido") or recentes[0].get("titulo", "")


def _macrotema_no_teto(macros_recentes: list[str]) -> str | None:
    """Macrotema que atingiu o teto de vídeos seguidos, se houver.

    Conta a sequência inicial (do vídeo mais recente para trás) de vídeos com
    o mesmo macrotema; se ela chegou a MAX_MACROTEMA_SEGUIDOS, esse macrotema
    está bloqueado no próximo vídeo.
    """
    if not macros_recentes:
        return None
    seguidos = 0
    for m in macros_recentes:
        if m != macros_recentes[0]:
            break
        seguidos += 1
    return macros_recentes[0] if seguidos >= MAX_MACROTEMA_SEGUIDOS else None


def selecionar_trend(
    cfg: Config,
    trends: list[dict],
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
) -> dict:
    """Escolhe a trend guiada SOMENTE pelo que a audiência está assistindo.

    Diretriz de 2026-07-18: sem pesos nem filtros editoriais. O prompt entrega
    ao modelo os últimos vídeos publicados COM as métricas reais (views/likes)
    e os campeões de retenção (``youtube.top_retencao``), e o critério é um só
    — a maior chance de performar com a audiência DESTE canal.

    Duas regras duras, APLICADAS aqui e não só pedidas no prompt:
    1. O mesmo macrotema não emenda mais de MAX_MACROTEMA_SEGUIDOS vídeos
       seguidos. Quando os últimos MAX_MACROTEMA_SEGUIDOS publicados são
       todos do mesmo macrotema, as candidatas dele saem da disputa ANTES da
       seleção.
    2. Vídeo repetido é vetado: a escolhida passa por uma verificação
       (``_video_repetido``) contra os vídeos publicados nas últimas
       JANELA_REPETICAO_HORAS; se ela cobriria o mesmo fato sem
       desenvolvimento novo, sai da disputa e a seleção refaz com as
       restantes.
    Se qualquer uma das regras zerar as candidatas do dia, aborta — melhor
    uma execução sem vídeo do que canal monotemático ou vídeo clonado.
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)
    macros_recentes = (
        _macrotemas_recentes(cliente, cfg, videos_recentes) if videos_recentes else []
    )

    candidatas = list(trends)
    macro_bloqueado = _macrotema_no_teto(macros_recentes)
    if macro_bloqueado:
        candidatas = [
            t for t in candidatas
            if t.get("macrotema", "outro") != macro_bloqueado
        ]
        print(
            f"[veto] Os últimos {MAX_MACROTEMA_SEGUIDOS} vídeos publicados são "
            f"todos '{macro_bloqueado}' — teto de macrotemas seguidos "
            f"atingido; candidatas desse macrotema fora da disputa "
            f"({len(candidatas)} de {len(trends)} seguem)."
        )
        if not candidatas:
            raise SystemExit(
                f"Todas as candidatas de hoje são '{macro_bloqueado}' e o teto "
                f"de {MAX_MACROTEMA_SEGUIDOS} vídeos seguidos desse macrotema "
                "foi atingido — sem vídeo hoje, para o canal não virar "
                "monotemático."
            )

    recentes_janela = _recentes_na_janela(videos_recentes, JANELA_REPETICAO_HORAS)
    while True:
        conteudo = (
            "Trends mais faladas do X hoje:\n"
            + _resumo_trends(candidatas)
            + _resumo_campeoes(campeoes)
            + _resumo_recentes(videos_recentes, macros_recentes)
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

        escolhida = _candidata_por_nome(candidatas, selecao["trend"])
        repetido = _video_repetido(cliente, cfg, escolhida, recentes_janela)
        if not repetido:
            break
        candidatas = [t for t in candidatas if t is not escolhida]
        print(
            f"[veto] '{escolhida['trend']}' cobriria o mesmo fato do vídeo já "
            f"publicado '{repetido}' — candidata fora da disputa; refazendo a "
            f"seleção ({len(candidatas)} seguem)."
        )
        if not candidatas:
            raise SystemExit(
                "Todas as candidatas de hoje repetiriam vídeos publicados nas "
                f"últimas {JANELA_REPETICAO_HORAS}h — execução sem vídeo "
                "(melhor do que publicar clone)."
            )

    print(f"[roteiro] Trend escolhida: {selecao['trend']}")
    print(f"[roteiro] Motivo: {selecao['motivo']}")
    return selecao


def _resumo_noticias(noticias: list[dict]) -> str:
    if not noticias:
        return "(nenhuma notícia recuperada — baseie-se no resumo da trend.)"
    linhas = []
    for n in noticias:
        data = f" ({n['data']})" if n.get("data") else ""
        veiculo = urlparse(n.get("url", "")).netloc.removeprefix("www.")
        fonte = f" [fonte: {veiculo}]" if veiculo else ""
        linhas.append(f"- {n['titulo']}{data}{fonte}: {n.get('resumo', '')}")
    return "\n".join(linhas)


def _fontes_x(urls: list[str]) -> str:
    """Lista as contas do X por trás dos posts da trend (fontes citáveis)."""
    if not urls:
        return "(nenhum post do X associado à trend.)"
    linhas = []
    for u in urls:
        usuario = urlparse(u).path.strip("/").split("/")[0]
        conta = f"@{usuario}" if usuario else "(conta desconhecida)"
        linhas.append(f"- {conta}: {u}")
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
        "POSTS DO X QUE ORIGINARAM A TREND (fontes citáveis na narração):\n"
        + _fontes_x(trend_escolhida.get("posts") or [])
        + "\n\nNOTÍCIAS RECENTES SOBRE A TREND (o veículo entre colchetes é a "
        "fonte citável):\n" + _resumo_noticias(noticias)
    )

    limite = int(cfg.video_duracao * PALAVRAS_POR_SEGUNDO)
    minimo = int(limite * FRACAO_MINIMA)
    instrucoes = INSTRUCOES_ROTEIRO.format(
        foco=FOCO_USA if cfg.publico == "usa" else FOCO_BRASIL,
        duracao=cfg.video_duracao,
        palavras=limite,
        palavras_min=minimo,
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

    # Faixa de palavras: o TTS cobra por caractere e vídeo longo mata a
    # retenção; vídeo curto demais sai com metade da duração-alvo e o YouTube
    # distribui menos. Fora da faixa, UMA nova tentativa pedindo ajuste.
    palavras = _contar_palavras(roteiro["texto_video"])
    if palavras > limite * FOLGA_PALAVRAS or palavras < minimo:
        estourou = palavras > limite * FOLGA_PALAVRAS
        print(
            f"[roteiro] texto_video com {palavras} palavras faladas "
            f"(faixa {minimo}-{limite}); pedindo versão "
            f"{'mais curta' if estourou else 'mais completa'}..."
        )
        pedido = (
            (
                f"O texto_video ficou com {palavras} palavras faladas; "
                f"o máximo é {limite}. Reescreva o JSON completo "
                "cortando detalhes do FATO (mantenha o hook, a "
                "implicação única e o corte final em tensão) até caber "
                "no limite"
            )
            if estourou
            else (
                f"O texto_video ficou com {palavras} palavras faladas; "
                f"o mínimo é {minimo} (a narração precisa preencher "
                f"{cfg.video_duracao} segundos). Reescreva o JSON completo "
                "acrescentando detalhes CONCRETOS ao FATO (número, nome, "
                "cena — sem encher linguiça; mantenha o hook, a implicação "
                "única e o corte final em tensão) até entrar na faixa de "
                f"{minimo} a {limite} palavras"
            )
        ) + (
            ", e ajuste os trechos das imagens para continuarem "
            "substrings exatas do novo texto_video."
        )
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
                {"role": "assistant", "content": resposta.choices[0].message.content},
                {"role": "user", "content": pedido},
            ],
            response_format={"type": "json_schema", "json_schema": ESQUEMA_ROTEIRO},
        )
        ajustado = json.loads(resposta.choices[0].message.content)
        _aparar_hook_final(ajustado)
        ajustadas = _contar_palavras(ajustado["texto_video"])
        if (ajustadas < palavras) if estourou else (ajustadas > palavras):
            roteiro = ajustado
        palavras = _contar_palavras(roteiro["texto_video"])
    print(f"[roteiro] {palavras} palavras faladas (faixa {minimo}-{limite})")
    print(f"[roteiro] Tema do dia: {roteiro['tema']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    if roteiro.get("hook"):
        print(f"[roteiro] Hook: {roteiro['hook']}")
    if roteiro.get("implicacao"):
        print(f"[roteiro] Implicação: {roteiro['implicacao']}")
    print(f"[roteiro] {len(roteiro['imagens'])} imagens-chave definidas")
    return roteiro
