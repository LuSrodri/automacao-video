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
   duração-alvo). Ao final, a AUDITORIA
   PRÓ-LEIGO (`_auditar_leigo`, chamada própria ao GPT) confere título,
   descrição e narração contra as regras de leigo (nome de nicho, jargão,
   teaser/frase vazia na descrição, âncora ausente) e reprova com UMA
   reescrita — as regras só no prompt vazavam ("Kimi K3", "GPUs" em título;
   "veja o que mudou" em descrição).

FORMATO LONGO (`--long-take`, cfg.formato == "longo"): as duas etapas trocam
de prompt e de esquema, mantendo a mesma mecânica. A seleção passa a exigir
pauta que renda análise das quatro óticas (geopolítica, tecnologia/IA,
negócios, mercado de trabalho) com payload para quem procura emprego, e
prefere trends com mais posts com clipe; o roteiro segue a estrutura em cinco
blocos (abertura, o que aconteceu, as quatro óticas, o que muda para quem
trabalha, síntese + o que observar), sem loop e sem CTA, dentro da faixa dura
de 90 a 120 segundos; e a auditoria ganha regras próprias (fontes nominais,
payload de carreira, as quatro óticas, nada dependendo de texto na tela). As
regras duras (teto de macrotema, veto a repetição) comparam só com os vídeos
LONGOS já publicados — Short e análise são conteúdos diferentes.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from openai import OpenAI

from .classificacao import MACROTEMAS, MACROTEMAS_DESCRICAO
from .config import AVISO_DADOS_EXTERNOS, LONGO_MAX_S, LONGO_MIN_S, Config

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
# No formato longo a janela é maior: o cron dispara menos vezes por dia e
# refazer a MESMA análise no dia seguinte é pior do que refazer uma manchete.
JANELA_REPETICAO_HORAS_LONGO = 72
# Formato LONGO: a faixa de palavras sai da FAIXA DURA de duração do formato
# (90 a 120s), não de VIDEO_DURACAO. A margem existe porque o ritmo real do TTS
# varia ~10% de narração para narração — sem ela o vídeo estoura a faixa
# pedida por três ou quatro segundos de fala.
MARGEM_LONGO_S = 4
# Duração (s) a partir da qual um vídeo já publicado no canal conta como
# LONGO. As regras duras do formato longo (teto de macrotema e veto a vídeo
# repetido) olham só para os vídeos longos: senão a rajada de Shorts do dia
# bloquearia todo vídeo longo, e a análise de um fato que virou Short há três
# horas é conteúdo novo — outro formato, outra profundidade, outro público.
DURACAO_MINIMA_LONGO = 75

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
                    "relevantes no final. É o RESUMO DO PAYLOAD, não teaser: "
                    "entrega o fato central concreto (número, nome, ação) com "
                    "a fonte nominal, e a implicação. Mesmo TESTE DO LEIGO do "
                    "título: nome de nicho (modelo de IA, lab, startup, "
                    "sigla) vira o efeito concreto. PROIBIDO: cauda de "
                    "suspense e CTA ('veja o que mudou', 'saiba mais', 'e "
                    "agora?') e frase de analista vazia ('virou um teste "
                    "sobre confiança', 'a saída segue em aberto')."
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
        },
        "required": [
            "tema",
            "hook",
            "implicacao",
            "titulo",
            "descricao",
            "texto_video",
        ],
    },
}

ESQUEMA_ROTEIRO_LONGO = {
    "name": "roteiro_video_longo",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "tema": {
                "type": "string",
                "description": "O acontecimento contemporâneo analisado no vídeo.",
            },
            "hook": {
                "type": "string",
                "description": (
                    "A frase de abertura (0-5s): o fato concreto mais forte JÁ "
                    "amarrado ao bolso/emprego de quem assiste. Máximo 14 "
                    "palavras, sem preâmbulo, sem data, sem nome de "
                    "instituição na primeira posição. A primeira frase de "
                    "texto_video DEVE ser exatamente esta (copiada palavra por "
                    "palavra, antes de qualquer audio tag)."
                ),
            },
            "tese": {
                "type": "string",
                "description": (
                    "Em uma frase: a leitura que costura as quatro óticas "
                    "(geopolítica, tecnologia/IA, mercado de trabalho e "
                    "negócios) sobre este acontecimento. É o fio condutor do "
                    "vídeo inteiro — decida antes de escrever a narração."
                ),
            },
            "impacto_carreira": {
                "type": "string",
                "description": (
                    "O payload central do vídeo, em 1 a 2 frases: o que este "
                    "acontecimento muda CONCRETAMENTE para quem procura "
                    "emprego ou está em transição de carreira — que setor, que "
                    "tipo de vaga, que habilidade, que prazo. Nada de conselho "
                    "genérico de coach ('se reinvente', 'esteja preparado')."
                ),
            },
            "o_que_observar": {
                "type": "string",
                "description": (
                    "O próximo marco concreto a acompanhar (decisão, balanço, "
                    "data, número que sai em breve) — fecha o vídeo sem CTA."
                ),
            },
            "titulo": {
                "type": "string",
                "description": (
                    "Título do vídeo, no idioma definido nas instruções, até 90 "
                    "caracteres. Direto e factual: ator + ação concreta, com "
                    "pelo menos uma coisa palpável (número, pessoa, dinheiro, "
                    "lugar) e, quando couber sem ficar artificial, o ângulo de "
                    "trabalho/carreira. TESTE DO LEIGO: entendível por quem "
                    "NUNCA ouviu falar da empresa ou do modelo — nome de nicho "
                    "(modelo de IA, lab, startup, sigla) fica FORA do título: "
                    "traduza para o efeito concreto em gente, dinheiro ou "
                    "ação. PROIBIDO cauda de suspense ('— e o detalhe muda "
                    "tudo', 'here's why it matters', 'e agora?'). O título "
                    "promete EXATAMENTE o que o vídeo entrega."
                ),
            },
            "descricao": {
                "type": "string",
                "description": (
                    "Descrição do vídeo no idioma definido nas instruções, "
                    "2 a 4 frases em um único parágrafo, com hashtags "
                    "relevantes no final. É o RESUMO DO PAYLOAD, não teaser: "
                    "entrega o fato central concreto (número, nome, ação) com "
                    "a fonte nominal, a leitura que une as quatro óticas e o "
                    "impacto prático no mercado de trabalho. Mesmo TESTE DO "
                    "LEIGO do título. PROIBIDO: cauda de suspense, CTA ('veja "
                    "o que mudou', 'saiba mais') e frase de analista vazia."
                ),
            },
            "texto_video": {
                "type": "string",
                "description": (
                    "Texto/roteiro narrado do vídeo, no idioma definido nas "
                    "instruções, seguindo a ESTRUTURA EM BLOCOS das "
                    "instruções (ABERTURA → O QUE ACONTECEU → AS QUATRO "
                    "ÓTICAS → O QUE ISSO MUDA PARA QUEM TRABALHA → SÍNTESE E "
                    "O QUE OBSERVAR). Ritmo de fala natural (frases de 8 a 18 "
                    "palavras, teto 22), vocabulário preciso de telejornal, "
                    "tom adulto de analista que respeita o espectador. Toda "
                    "afirmação central atribuída nominalmente à fonte "
                    "(veículo de notícias ou conta do X), somente fontes das "
                    "listas recebidas. O vídeo NÃO tem legendas nem texto na "
                    "tela: a narração precisa se sustentar sozinha, sem "
                    "'como você vê aqui' nem referência a imagem."
                ),
            },
        },
        "required": [
            "tema",
            "hook",
            "tese",
            "impacto_carreira",
            "o_que_observar",
            "titulo",
            "descricao",
            "texto_video",
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

ESQUEMA_AUDITORIA_LEIGO = {
    "name": "auditoria_pro_leigo",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "aprovado": {
                "type": "boolean",
                "description": (
                    "true somente quando título, descrição e narração passam "
                    "em TODAS as regras (zero problemas)."
                ),
            },
            "problemas": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Cada violação encontrada, citando o termo/frase exato e "
                    "a regra que ele fura (lista vazia quando aprovado)."
                ),
            },
        },
        "required": ["aprovado", "problemas"],
    },
}

INSTRUCOES_AUDITORIA_LEIGO = """\
Você é o auditor pró-leigo de um canal de vídeos curtos de notícias. Você
recebe o título, a descrição e a narração de um vídeo e verifica as regras
abaixo. O espectador é um adulto leigo que NUNCA ouviu falar de modelos de
IA, labs, startups e siglas de nicho — Trump, Google, Irã, iPhone, Elon Musk
ele conhece; Grok, Kimi K3, Anthropic, CENTCOM, GPU ele NÃO conhece.

CALIBRAGEM (vale para as três partes):
- Nome próprio UNIVERSALMENTE conhecido (países, Trump, Google, Elon Musk,
  ChatGPT, iPhone...) é permitido em qualquer quantidade — nunca é problema.
  O que reprova é nome de NICHO (modelo de IA, lab, startup, app pouco
  conhecido, sigla militar/técnica) sem tradução para o efeito concreto.
- Termos do dia a dia NÃO são jargão: inteligência artificial, IA/AI, app,
  site, robô, chip, e tudo que um adulto ouve num telejornal (bilhões,
  míssil, sanção, falência, petróleo).
- As hashtags no final da descrição não entram na auditoria.

TÍTULO:
1. Teste do leigo: entendível por quem nunca ouviu falar da empresa/modelo.
   Nome de nicho ou jargão técnico REPROVA — deve virar o efeito concreto em
   gente, dinheiro ou ação.
2. Sem cauda de suspense ("— e o detalhe muda tudo", "here's why it
   matters", "e agora?").
DESCRIÇÃO:
3. Entrega o fato central concreto com a fonte nominal — não é teaser.
   REPROVA: CTA/suspense ("veja o que mudou", "saiba mais") e frase de
   analista vazia ("virou um teste sobre confiança", "a saída segue em
   aberto", "entrou numa fase mais perigosa" sem fato).
4. Mesmo teste do leigo do título (nome de nicho vira efeito concreto).
NARRAÇÃO:
5. Jargão técnico ou sigla de nicho sem explicação de meia frase REPROVA
   (audio tags entre colchetes não são jargão).
6. Se o assunto CENTRAL é de nicho, a primeira frase depois do hook precisa
   ancorar em algo que o leigo conhece ("a empresa por trás do ChatGPT", "o
   maior rival do ChatGPT"); sem âncora REPROVA. Assunto universalmente
   conhecido não precisa de âncora.
7. No máximo 1 nome próprio de nicho no vídeo inteiro (veículo ou conta do X
   citado como FONTE não conta; nome universalmente conhecido não conta).

Liste em "problemas" cada violação com o termo/frase exato citado. NÃO
invente problema: o que segue as regras passa, e "aprovado" = true com zero
problemas.\
"""

INSTRUCOES_AUDITORIA_LEIGO_LONGO = """\
Você é o auditor de um canal de vídeos de ANÁLISE de 90 a 120 segundos, feitos
para um adulto leigo que está procurando emprego ou em transição de carreira.
Você recebe o título, a descrição e a narração de um vídeo e verifica as
regras abaixo. O espectador conhece Trump, Google, Irã, iPhone, Elon Musk; ele
NÃO conhece Grok, Kimi K3, Anthropic, CENTCOM, GPU.

CALIBRAGEM (vale para as três partes):
- Nome próprio UNIVERSALMENTE conhecido é permitido em qualquer quantidade —
  nunca é problema. O que reprova é nome de NICHO (modelo de IA, lab, startup,
  app pouco conhecido, sigla militar/técnica) sem tradução.
- Termos do dia a dia NÃO são jargão: inteligência artificial, IA/AI, app,
  chip, robô, e tudo que se ouve num telejornal (bilhões, míssil, sanção,
  falência, demissão em massa, tarifa).
- As hashtags no final da descrição não entram na auditoria.
- Audio tags entre colchetes não entram na auditoria.

TÍTULO:
1. Teste do leigo: entendível por quem nunca ouviu falar da empresa/modelo.
   Nome de nicho ou jargão técnico REPROVA — deve virar o efeito concreto.
2. Sem cauda de suspense ("— e o detalhe muda tudo", "here's why it matters").
DESCRIÇÃO:
3. Entrega o fato central concreto com a fonte nominal e o impacto prático —
   não é teaser. REPROVA: CTA/suspense e frase de analista vazia ("virou um
   teste sobre confiança", "a saída segue em aberto").
4. Mesmo teste do leigo do título.
NARRAÇÃO:
5. Nome de nicho ou sigla sem tradução de meia frase na PRIMEIRA vez que
   aparece REPROVA. Mais de três nomes de nicho no vídeo inteiro REPROVA
   (veículo ou conta do X citado como FONTE não conta).
6. Pelo menos DUAS fontes nominais (veículo ou conta do X) ao longo da
   narração; "segundo fontes" sem nome REPROVA.
7. PAYLOAD DE CARREIRA: o vídeo precisa dizer, com fato concreto, o que o
   acontecimento muda para quem procura emprego ou muda de área (setor,
   função, habilidade, prazo, número). Conselho de coach ("se reinvente",
   "esteja preparado", "invista em você") e futurologia sem base REPROVAM.
8. AS QUATRO ÓTICAS: geopolítica, tecnologia/IA, negócios e mercado de
   trabalho precisam aparecer, costuradas por causa e efeito. Ótica ausente
   ou lista de tópicos soltos REPROVA.
9. Nenhuma frase pode depender de texto na tela ("como você vê aqui", "no
   gráfico") — o vídeo não tem legendas.
10. Fechamento: síntese + próximo marco a observar. CTA falado, pedido de
   inscrição ou despedida REPROVAM.

Liste em "problemas" cada violação com o termo/frase exato citado. NÃO invente
problema: o que segue as regras passa, e "aprovado" = true com zero problemas.\
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

FORMATO DO CANAL: o vídeo é montado SOMENTE com os clipes de vídeo anexados
aos posts do X da trend (até 3 clipes; nenhuma foto estática). Todas as
candidatas listadas têm pelo menos 1 post com clipe, mas em empate prefira a
que tem MAIS clipes e o material em vídeo mais forte (veja "apelo visual").

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

INSTRUCOES_SELECAO_LONGO = """\
Você é editor de um canal de vídeos de ANÁLISE (formato longo, 16:9, cerca de
{duracao} segundos) sobre os grandes acontecimentos contemporâneos.

Você recebe as trends mais faladas do X hoje (cada uma com resumo, macrotema e
imagem mental), os vídeos CAMPEÕES DE RETENÇÃO do canal e os últimos vídeos
publicados COM as métricas reais de audiência (views e likes). Atenção: essas
métricas são dos vídeos CURTOS do canal — use-as como régua do que este
público responde (tema, tensão, promessa), não como molde de formato.

O QUE O VÍDEO LONGO É: uma análise educacional que explica um acontecimento
atual cruzando QUATRO ÓTICAS — geopolítica, tecnologia e IA, mercado de
trabalho e negócios — e entrega valor prático para o espectador principal:
o adulto que está PROCURANDO EMPREGO ou EM TRANSIÇÃO DE CARREIRA e quer
entender para onde o mundo (e o trabalho dele) está indo.

CRITÉRIOS, nesta ordem:
1. RENDE ANÁLISE DAS QUATRO ÓTICAS: o acontecimento tem causa, mecanismo e
   consequência claros e toca — mesmo que indiretamente — dinheiro, empresas,
   poder entre países e trabalho. Fato isolado e sem desdobramento (uma treta
   de rede social, um vídeo curioso) NÃO vira vídeo longo, por mais quente que
   esteja.
2. PAYLOAD DE CARREIRA: dá para dizer, com fato e não com achismo, o que isso
   muda para quem procura emprego ou está mudando de área (setor que contrata
   ou corta, habilidade que passa a valer, prazo). Prefira acontecimentos com
   números de dinheiro, investimento, vagas, contratos ou regulação.
3. AUDIÊNCIA: entre as candidatas que passam em 1 e 2, escolha a que mais se
   parece com o que o público DESTE canal assiste, segundo os números
   listados. Repetir o tipo de assunto que performa é bem-vindo.
4. MATERIAL EM VÍDEO: o vídeo é montado SOMENTE com os clipes anexados aos
   posts do X da trend (até {max_clipes} clipes, nenhuma foto estática). Em
   empate, vence a candidata com MAIS posts com clipe.

Não escolha uma candidata que renderia uma análise IDÊNTICA a um vídeo longo
já publicado, sem nenhum fato novo.

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

DESCRIÇÃO — resumo do payload, não teaser: 1 a 3 frases que ENTREGAM o fato
central (com número/nome concreto e a fonte nominal) e a implicação, seguidas
das hashtags. Mesmo teste do leigo do título: nome de nicho vira o efeito
concreto. PROIBIDO na descrição: cauda de suspense e CTA ("veja o que mudou
nas últimas horas", "saiba mais", "e agora?"), frase de analista vazia
("virou um teste sobre confiança e transparência", "a saída segue em
aberto") e rumor apresentado como fato.

DURAÇÃO — a narração deve PREENCHER {duracao} segundos: escreva entre
{palavras_min} e {palavras} palavras faladas no texto_video (audio tags entre
colchetes não contam). Os DOIS limites são DUROS: estourar alonga o vídeo e
derruba a retenção; ficar abaixo do mínimo entrega um vídeo raso e curto
demais, que o algoritmo distribui menos. Se faltar espaço, corte detalhes do
FATO — nunca o hook, a implicação única nem o corte final. Se sobrar espaço,
acrescente um detalhe concreto ao FATO (número, nome, cena) — nunca encha
linguiça.

MATERIAL VISUAL — o vídeo é montado SOMENTE com os clipes de vídeo anexados
aos posts do X da trend (nada de foto estática nem imagem de banco). Você não
escolhe os clipes — um editor de cortes casa cada um com a narração depois —
mas escreva o texto SABENDO disso: descreva cenas que os posts da trend
documentam em vídeo, e lembre que o primeiro clipe + o hook decidem o "viewed
vs swiped".

NARRAÇÃO EXPRESSIVA — insira audio tags do ElevenLabs v3 no texto_video:
palavras em inglês entre colchetes, imediatamente antes do trecho que modificam.
Exemplos: [excited], [curious], [whispers], [surprised], [sighs], [laughs],
[short pause]. Use de 8 a 12 tags, variando a emoção conforme o conteúdo (elas
não são faladas nem aparecem nas legendas). A pontuação também guia a entrega:
reticências para suspense, MAIÚSCULAS para ênfase pontual.

Responda somente com o JSON pedido.\
"""


INSTRUCOES_ROTEIRO_LONGO = """\
Você é roteirista de vídeos de ANÁLISE (formato longo, 16:9, {duracao}
segundos) que explicam os grandes acontecimentos contemporâneos cruzando
quatro óticas: GEOPOLÍTICA, TECNOLOGIA E IA, MERCADO DE TRABALHO e NEGÓCIOS.
{foco}

Você recebe a TREND escolhida (com a IMAGEM MENTAL que ela evoca), os POSTS DO
X que originaram a trend e NOTÍCIAS recentes sobre ela. Use as notícias para
acertar fatos, nomes, empresas, datas e números — não invente nada. Fato que
não está no material recebido não entra no vídeo.

ESPECTADOR — A REGRA QUE MANDA EM TODAS AS OUTRAS: um adulto leigo (25 a 54
anos, sem formação técnica) que está PROCURANDO EMPREGO ou EM TRANSIÇÃO DE
CARREIRA. Ele não assiste por curiosidade: ele quer entender para onde o
mundo está indo porque a vida profissional dele depende disso. Todo bloco do
vídeo precisa render alguma coisa para essa pessoa — informação que ela usa
para decidir onde investir tempo, para que setor olhar, o que está morrendo e
o que está nascendo.

VALOR ACIMA DE TUDO: densidade de informação REAL. Cada frase carrega um fato,
um número, um nome ou uma relação de causa e efeito. Enrolação, frase de
efeito e generalidade são o defeito mais grave possível neste formato — em
{duracao} segundos o espectador perdoa densidade, nunca vazio.

SEM LEGENDAS E SEM TEXTO NA TELA: a narração precisa se sustentar sozinha.
PROIBIDO "como você vê aqui", "na imagem", "no gráfico", ou qualquer frase que
dependa de algo escrito na tela.

FONTES — OBRIGATÓRIO citar nominalmente: cada afirmação central é atribuída a
quem a publicou — o veículo ("segundo a Reuters", "o Financial Times revelou")
ou a conta do X ("no post de @sentdefender"). Cite SOMENTE fontes das listas
recebidas, pelo menos DUAS ao longo do vídeo, embutidas na frase — nunca em
bloco de créditos. "Segundo fontes", sem nome, continua proibido. Nome de
veículo ou de conta citado como fonte não conta como nome próprio de nicho.

TOM: analista adulto e afiado — jornalismo econômico de bom nível, não
palestra motivacional e não aula. Autoridade seca, sem entusiasmo fofo, sem
moral da história, sem "nós" professoral. O espectador é leigo, não é burro:
escrever simples é remover barreiras (jargão, sigla, contexto obscuro), nunca
rebaixar o texto.

FRASES: ritmo de fala natural — mire em 8 a 18 palavras por frase, teto de 22.
Alterne frases curtas de impacto com frases cheias que carregam o fato. Uma
ideia central por frase. (Audio tags entre colchetes não contam como palavras.)

VOCABULÁRIO: preciso e adulto. Tudo que se ouve num telejornal está liberado
(bilhões, sanção, demissão em massa, monopólio, tarifa, recessão). Nome de
nicho (modelo de IA, lab, startup, sigla técnica ou militar) é permitido — no
máximo TRÊS no vídeo inteiro — mas SEMPRE traduzido em meia frase na primeira
vez que aparece ("a empresa por trás do ChatGPT", "o imposto que encarece o
produto importado"). Sem a tradução, não use o nome.

ESTRUTURA OBRIGATÓRIA — cinco blocos, nesta ordem, sem anunciar a estrutura
(PROIBIDO "neste vídeo vamos ver três pontos"):
1. ABERTURA (0-8s): o HOOK (campo hook, primeira frase do texto, palavra por
   palavra) — o fato concreto mais forte já amarrado ao bolso ou ao emprego de
   quem assiste — seguido de UMA frase que promete o que o espectador leva do
   vídeo. Nada de contexto histórico, data ou nome de instituição na abertura.
2. O QUE ACONTECEU (~20s): o acontecimento em ordem "coisa concreta primeiro,
   detalhe depois", com número real, quem fez, quando, e a FONTE nominal. Se o
   assunto central for de nicho, a primeira frase deste bloco ancora em algo
   que o leigo conhece.
3. AS QUATRO ÓTICAS (~40s, o corpo do vídeo): explique o acontecimento por
   GEOPOLÍTICA (quem ganha e quem perde poder), TECNOLOGIA E IA (o que a
   tecnologia tem a ver com isso, o que ela permite ou destrói), NEGÓCIOS
   (dinheiro, empresas, investimento, quem paga a conta) e MERCADO DE TRABALHO
   (o que acontece com as vagas). Duas a quatro frases por ótica, ENCADEADAS
   por causa e efeito ("por isso", "o efeito disso", "e aí entra o dinheiro")
   — nunca uma lista de tópicos soltos. Cada ótica carrega pelo menos um dado
   concreto do material recebido. A ordem interna pode mudar se a lógica do
   fato pedir, mas as quatro precisam estar lá, costuradas pela sua TESE.
4. O QUE ISSO MUDA PARA QUEM TRABALHA (~25s): o payload. Concreto e
   verificável: que setor contrata ou corta, que tipo de função entra na
   linha de tiro, que habilidade passa a valer, em que prazo, com que número.
   PROIBIDO conselho de coach ("se reinvente", "esteja preparado", "invista em
   você") e futurologia sem base no material recebido.
5. SÍNTESE E O QUE OBSERVAR (últimos ~10s): uma frase que amarra a tese e uma
   que aponta o PRÓXIMO MARCO concreto a acompanhar (decisão, balanço, data,
   número que sai em breve). Sem CTA, sem pedido de inscrição, sem despedida,
   sem moral da história.

RETENÇÃO: a cada ~25 segundos abra um mini-gancho que puxa para o bloco
seguinte ("o número que interessa não é esse", "e é aqui que isso encosta no
seu emprego"). O vídeo não roda em loop: ele fecha — mas fecha entregando,
nunca com suspense vazio.

PROIBIDO NO TEXTO:
- Frases de analista vazias: "no cenário geopolítico", "especialistas
  afirmam", "o mercado reagiu", "só o tempo dirá".
- Número com mais de 2 dígitos significativos: "2 bilhões", "150 mil", "quase
  30%" — nunca "2,37 bilhões", "148.532" ou "29,7%".
- Opinião militante, torcida política e previsão inventada. Cenário só entra
  se estiver no material recebido e for apresentado como cenário.

PAYLOAD OBRIGATÓRIO: o roteiro entrega o fato, as quatro leituras e uma
consequência prática para o trabalho — tudo ancorado no material recebido.

TÍTULO — medido nos números do canal: título autossuficiente rende o dobro de
views do título com nome de nicho. Regras: (1) ator + ação concreta, com uma
coisa palpável (número, pessoa, dinheiro, lugar) e, quando couber com
naturalidade, o ângulo de trabalho/carreira; (2) TESTE DO LEIGO: entendível
por quem nunca ouviu falar da empresa/modelo — nome de nicho vira o efeito
concreto; (3) PROIBIDO cauda de suspense ("— e o detalhe muda tudo", "here's
why it matters", "e agora?").

DESCRIÇÃO — resumo do payload, não teaser: 2 a 4 frases que entregam o fato
central (com número/nome concreto e a fonte nominal), a leitura que une as
quatro óticas e o impacto prático no mercado de trabalho, seguidas das
hashtags. Mesmo teste do leigo do título. PROIBIDO CTA, cauda de suspense e
frase de analista vazia.

DURAÇÃO — a narração deve PREENCHER {duracao} segundos: escreva entre
{palavras_min} e {palavras} palavras faladas no texto_video (audio tags entre
colchetes não contam). Os DOIS limites são DUROS — o formato do canal é de 90
a 120 segundos. Se faltar espaço, corte detalhe secundário do bloco 2 ou 3 —
nunca o hook, o bloco 4 (o payload de carreira) nem o fechamento. Se sobrar
espaço, acrescente dado concreto do material recebido (número, nome, cena),
nunca encha linguiça.

MATERIAL VISUAL — o vídeo é montado SOMENTE com os clipes de vídeo anexados
aos posts do X da trend (até {max_clipes} clipes, nada de foto estática nem
imagem de banco). Você não escolhe os clipes — um editor de cortes casa cada um
com a narração depois — mas escreva sabendo disso: fale de cenas que os posts
documentam em vídeo, e lembre que o primeiro clipe + o hook decidem quem fica.

NARRAÇÃO EXPRESSIVA — insira audio tags do ElevenLabs v3 no texto_video:
palavras em inglês entre colchetes, imediatamente antes do trecho que
modificam. Exemplos: [serious], [curious], [emphatic], [short pause],
[thoughtful], [surprised]. Use de 15 a 25 tags ao longo do texto, variando
conforme o conteúdo (elas não são faladas). A pontuação também guia a entrega:
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
            f"   Posts com clipe de vídeo nativo: {t.get('posts_com_video', '?')}\n"
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


def _somente_longos(videos_recentes: list[dict] | None) -> list[dict]:
    """Os vídeos publicados que são do formato LONGO (>= DURACAO_MINIMA_LONGO).

    As regras duras do formato longo comparam com os vídeos longos do canal, e
    não com a rajada de Shorts do dia: um Short de 30s sobre um fato e uma
    análise de 2 minutos sobre o mesmo fato são conteúdos diferentes. Vídeo sem
    duração conhecida fica de fora (o canal só passa a ter longos agora).
    """
    return [
        v
        for v in videos_recentes or []
        if (v.get("duracao_s") or 0) >= DURACAO_MINIMA_LONGO
    ]


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
    cliente: OpenAI,
    cfg: Config,
    trend: dict,
    recentes: list[dict],
    janela_horas: int = JANELA_REPETICAO_HORAS,
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
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"PAUTA CANDIDATA: {trend.get('trend', '')}\n"
        f"Resumo: {trend.get('resumo', '')}\n\n"
        f"VÍDEOS PUBLICADOS NAS ÚLTIMAS {janela_horas} HORAS:\n"
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
    return veredito.get("video_repetido") or "um vídeo publicado nas últimas horas"


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

    Regras duras, APLICADAS aqui e não só pedidas no prompt:
    0. Candidata sem nenhum post com clipe de vídeo nativo sai da disputa
       antes de tudo: o formato do canal é montado só com clipes do X.
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
    longo = cfg.formato == "longo"
    macros_recentes = (
        _macrotemas_recentes(cliente, cfg, videos_recentes) if videos_recentes else []
    )

    # As regras duras (teto de macrotema e veto a vídeo repetido) do formato
    # longo comparam só com os vídeos LONGOS do canal; o prompt continua
    # recebendo a lista inteira, que é a régua de audiência.
    if longo:
        indices = [
            i
            for i, v in enumerate(videos_recentes or [])
            if (v.get("duracao_s") or 0) >= DURACAO_MINIMA_LONGO
        ]
        recentes_regras = [(videos_recentes or [])[i] for i in indices]
        macros_regras = [
            macros_recentes[i] for i in indices if i < len(macros_recentes)
        ]
        print(
            f"[longo] {len(recentes_regras)} vídeo(s) longo(s) já publicados "
            "servem de base para o teto de macrotema e o veto a repetição."
        )
    else:
        recentes_regras = list(videos_recentes or [])
        macros_regras = macros_recentes

    # O formato do canal é montado só com clipes dos posts do X: candidata
    # sem nenhum post com vídeo nativo não tem material e sai da disputa.
    candidatas = [t for t in trends if t.get("posts_com_video")]
    if len(candidatas) < len(trends):
        print(
            f"[veto] {len(trends) - len(candidatas)} candidata(s) sem nenhum "
            f"post com vídeo nativo fora da disputa ({len(candidatas)} de "
            f"{len(trends)} seguem)."
        )
    if not candidatas:
        raise SystemExit(
            "Nenhuma candidata de hoje tem post com clipe de vídeo nativo — o "
            "formato do canal é montado só com clipes do X; execução sem vídeo."
        )

    # No formato longo um único clipe teria que segurar dois minutos de tela:
    # preferimos as candidatas com pelo menos dois posts com clipe, mas sem
    # zerar a disputa quando o dia inteiro só tem trends de um clipe.
    if longo:
        com_material = [t for t in candidatas if (t.get("posts_com_video") or 0) >= 2]
        if com_material:
            if len(com_material) < len(candidatas):
                print(
                    f"[longo] {len(candidatas) - len(com_material)} candidata(s) "
                    "com um só post com clipe fora da disputa (2 minutos de "
                    f"tela pedem mais material; {len(com_material)} seguem)."
                )
            candidatas = com_material
        else:
            print(
                "[aviso] Nenhuma candidata de hoje tem 2+ posts com clipe; "
                "seguindo com as de clipe único (o clipe vai repetir bastante)."
            )

    macro_bloqueado = _macrotema_no_teto(macros_regras)
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

    janela_repeticao = (
        JANELA_REPETICAO_HORAS_LONGO if longo else JANELA_REPETICAO_HORAS
    )
    recentes_janela = _recentes_na_janela(recentes_regras, janela_repeticao)
    instrucoes_selecao = (
        INSTRUCOES_SELECAO_LONGO.format(
            duracao=cfg.video_duracao, max_clipes=cfg.max_clipes
        )
        if longo
        else INSTRUCOES_SELECAO
    )
    while True:
        conteudo = (
            AVISO_DADOS_EXTERNOS
            + "\n\nTrends mais faladas do X hoje:\n"
            + _resumo_trends(candidatas)
            + _resumo_campeoes(campeoes)
            + _resumo_recentes(videos_recentes, macros_recentes)
        )
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes_selecao},
                {"role": "user", "content": conteudo},
            ],
            response_format={"type": "json_schema", "json_schema": ESQUEMA_SELECAO},
        )
        selecao = json.loads(resposta.choices[0].message.content)

        escolhida = _candidata_por_nome(candidatas, selecao["trend"])
        repetido = _video_repetido(
            cliente, cfg, escolhida, recentes_janela, janela_repeticao
        )
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
                f"últimas {janela_repeticao}h — execução sem vídeo "
                "(melhor do que publicar clone)."
            )

    # O OBJETO da trend escolhida segue junto: re-localizar a trend por nome
    # em cada etapa (com lógicas de match diferentes) deixava o roteiro sair
    # de um stub e as mídias virem de outra trend quando o modelo parafraseava
    # o nome — daqui em diante todo mundo usa este objeto.
    selecao["trend_obj"] = escolhida
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


def _resumo_estilo(
    videos_recentes: list[dict] | None,
    campeoes: list[dict] | None,
    formato: str = "curto",
) -> str:
    """Referência de estilo para o ROTEIRISTA: o que a audiência responde.

    Os campeões e as métricas já guiam a SELEÇÃO da pauta; esta seção fecha o
    ciclo uma etapa adiante — o roteirista calibra título, hook e promessa
    pelo que o público deste canal comprovadamente clica e assiste.
    """
    com_views = sorted(
        [v for v in videos_recentes or [] if v.get("views") is not None],
        key=lambda v: v["views"],
        reverse=True,
    )
    top = com_views[:6]
    flop = [v for v in com_views[-4:] if v not in top] if len(com_views) > 6 else []
    if not top and not campeoes:
        return ""
    partes = [
        "\n\nREFERÊNCIA DE ESTILO DA AUDIÊNCIA — títulos reais deste canal e "
        "como performaram. Calibre o TIPO de título, hook e promessa pelo que "
        "funciona; NUNCA copie um título nem repita o assunto deles:"
    ]
    if formato == "longo":
        partes.append(
            "(São vídeos CURTOS do canal: servem de régua do que este público "
            "clica, não de molde para a profundidade do vídeo longo.)"
        )
    if top:
        partes.append("Títulos com MAIS views:")
        partes += [f"- {v.get('titulo', '')} ({v['views']} views)" for v in top]
    if flop:
        partes.append("Títulos com MENOS views (o que o público ignora):")
        partes += [f"- {v.get('titulo', '')} ({v['views']} views)" for v in flop]
    if campeoes:
        partes.append(
            "Campeões de retenção (o público assiste até o fim vídeos assim):"
        )
        partes += [
            f"- {c.get('titulo', '')} "
            f"(assistem em média {c.get('retencao_media', '?')}% do vídeo)"
            for c in campeoes
        ]
    return "\n".join(partes)


def _faixa_palavras(cfg: Config) -> tuple[int, int]:
    """Piso e teto de palavras faladas do roteiro, conforme o formato.

    No formato curto a faixa sai de VIDEO_DURACAO (teto pela duração-alvo,
    piso em FRACAO_MINIMA dela). No formato longo ela sai da FAIXA DURA do
    próprio formato (90 a 120s), com MARGEM_LONGO_S de folga em cada ponta
    para absorver a variação de ritmo do TTS.
    """
    if cfg.formato == "longo":
        return (
            int((LONGO_MIN_S + MARGEM_LONGO_S) * PALAVRAS_POR_SEGUNDO),
            int((LONGO_MAX_S - MARGEM_LONGO_S) * PALAVRAS_POR_SEGUNDO),
        )
    limite = int(cfg.video_duracao * PALAVRAS_POR_SEGUNDO)
    return int(limite * FRACAO_MINIMA), limite


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


def _auditar_leigo(cliente: OpenAI, cfg: Config, roteiro: dict) -> list[str]:
    """Violações pró-leigo no título, na descrição e na narração (vazia = ok).

    Auditoria em chamada própria porque as regras só no prompt do roteirista
    vazavam ("Kimi K3", "GPUs" no título; "veja o que mudou" na descrição) —
    regra de comportamento nunca fica só em prompt.
    """
    conteudo = (
        f"TÍTULO: {roteiro.get('titulo', '')}\n\n"
        f"DESCRIÇÃO: {roteiro.get('descricao', '')}\n\n"
        f"NARRAÇÃO:\n{roteiro.get('texto_video', '')}"
    )
    instrucoes = (
        INSTRUCOES_AUDITORIA_LEIGO_LONGO
        if cfg.formato == "longo"
        else INSTRUCOES_AUDITORIA_LEIGO
    )
    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": conteudo},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": ESQUEMA_AUDITORIA_LEIGO,
        },
    )
    veredito = json.loads(resposta.choices[0].message.content)
    if veredito["aprovado"]:
        return []
    return [p for p in veredito.get("problemas", []) if p.strip()]


def gerar_roteiro(
    cfg: Config,
    selecao: dict,
    trends: list[dict],
    noticias: list[dict],
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
) -> dict:
    """Gera o roteiro completo da trend escolhida, enriquecido com notícias."""
    cliente = OpenAI(api_key=cfg.openai_api_key)

    # A seleção devolve o objeto da trend escolhida em "trend_obj"; o match
    # por nome fica só como reserva (chamadas antigas/testes sem o objeto).
    trend_escolhida = selecao.get("trend_obj") or next(
        (t for t in trends if t["trend"] == selecao["trend"]),
        {"trend": selecao["trend"], "resumo": selecao.get("motivo", "")},
    )

    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"TREND ESCOLHIDA: {trend_escolhida['trend']}\n"
        f"Resumo da trend: {trend_escolhida.get('resumo', '')}\n"
        f"Imagem mental da notícia (o que a pessoa visualiza — o HOOK nasce "
        f"daqui): {trend_escolhida.get('imagem_mental', '?')}\n\n"
        "POSTS DO X QUE ORIGINARAM A TREND (fontes citáveis na narração):\n"
        + _fontes_x(trend_escolhida.get("posts") or [])
        + "\n\nNOTÍCIAS RECENTES SOBRE A TREND (o veículo entre colchetes é a "
        "fonte citável):\n" + _resumo_noticias(noticias)
        + _resumo_estilo(videos_recentes, campeoes, cfg.formato)
    )

    longo = cfg.formato == "longo"
    minimo, limite = _faixa_palavras(cfg)
    # No formato longo o teto já vem com margem embutida (a faixa de 90-120s é
    # dura), então não há folga extra sobre ele.
    folga = 1.0 if longo else FOLGA_PALAVRAS
    esquema = ESQUEMA_ROTEIRO_LONGO if longo else ESQUEMA_ROTEIRO
    modelo_instrucoes = INSTRUCOES_ROTEIRO_LONGO if longo else INSTRUCOES_ROTEIRO
    formatacao = {
        "foco": FOCO_USA if cfg.publico == "usa" else FOCO_BRASIL,
        "duracao": cfg.video_duracao,
        "palavras": limite,
        "palavras_min": minimo,
    }
    if longo:
        formatacao["max_clipes"] = cfg.max_clipes
    instrucoes = modelo_instrucoes.format(**formatacao)

    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {"role": "system", "content": instrucoes},
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": esquema},
    )

    roteiro = json.loads(resposta.choices[0].message.content)
    _aparar_hook_final(roteiro)

    # Faixa de palavras: o TTS cobra por caractere e vídeo longo mata a
    # retenção; vídeo curto demais sai com metade da duração-alvo e o YouTube
    # distribui menos. Fora da faixa, UMA nova tentativa pedindo ajuste.
    palavras = _contar_palavras(roteiro["texto_video"])
    if palavras > limite * folga or palavras < minimo:
        estourou = palavras > limite * folga
        print(
            f"[roteiro] texto_video com {palavras} palavras faladas "
            f"(faixa {minimo}-{limite}); pedindo versão "
            f"{'mais curta' if estourou else 'mais completa'}..."
        )
        preservar = (
            "mantenha o hook, as quatro óticas, o payload de carreira e o "
            "fechamento com o que observar"
            if longo
            else "mantenha o hook, a implicação única e o corte final em tensão"
        )
        cortar = (
            "cortando detalhe secundário dos blocos O QUE ACONTECEU e AS "
            "QUATRO ÓTICAS"
            if longo
            else "cortando detalhes do FATO"
        )
        acrescentar = (
            "acrescentando dado CONCRETO do material recebido (número, nome, "
            "empresa, prazo) às quatro óticas"
            if longo
            else "acrescentando detalhes CONCRETOS ao FATO (número, nome, cena)"
        )
        pedido = (
            (
                f"O texto_video ficou com {palavras} palavras faladas; "
                f"o máximo é {limite}. Reescreva o JSON completo "
                f"{cortar} ({preservar}) até caber no limite"
            )
            if estourou
            else (
                f"O texto_video ficou com {palavras} palavras faladas; "
                f"o mínimo é {minimo} (a narração precisa preencher "
                f"{cfg.video_duracao} segundos). Reescreva o JSON completo "
                f"{acrescentar} — sem encher linguiça; {preservar} — até "
                f"entrar na faixa de {minimo} a {limite} palavras"
            )
        ) + "."
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
                {"role": "assistant", "content": resposta.choices[0].message.content},
                {"role": "user", "content": pedido},
            ],
            response_format={"type": "json_schema", "json_schema": esquema},
        )
        ajustado = json.loads(resposta.choices[0].message.content)
        _aparar_hook_final(ajustado)
        ajustadas = _contar_palavras(ajustado["texto_video"])

        # Aceita a versão ajustada somente se ela ficou MAIS PERTO da faixa —
        # "melhorou na direção pedida" deixava passar um texto que despencou
        # para o outro lado (ex.: de 120 palavras acima do teto para 50,
        # abaixo do piso).
        def _dist_faixa(n: int) -> int:
            return max(minimo - n, n - int(limite * folga), 0)

        if _dist_faixa(ajustadas) < _dist_faixa(palavras):
            roteiro = ajustado
        palavras = _contar_palavras(roteiro["texto_video"])

    # Auditoria pró-leigo (título + descrição + narração) com UMA reescrita:
    # aprova, ou lista as violações e pede o JSON corrigido; a nova versão só
    # substitui a original se reduzir os problemas.
    problemas = _auditar_leigo(cliente, cfg, roteiro)
    if problemas:
        print(f"[roteiro] Auditoria pró-leigo reprovou ({len(problemas)}):")
        for p in problemas:
            print(f"  - {p}")
        pedido = (
            "A auditoria reprovou o roteiro pelos problemas listados abaixo. "
            "Reescreva o JSON completo corrigindo TODOS eles: nome de nicho "
            "vira o efeito concreto ou ganha tradução de meia frase; a "
            "descrição entrega o fato com a fonte, sem teaser nem frase "
            "vazia; jargão ganha explicação de meia frase ou sai"
            + (
                "; as quatro óticas e o payload de carreira concreto precisam "
                "estar no texto, e o vídeo fecha com o próximo marco a "
                "observar, sem CTA. "
                if longo
                else "; assunto de nicho ganha âncora logo após o hook. "
            )
            + "Mantenha o texto_video na faixa de "
            f"{minimo} a {limite} palavras faladas.\nProblemas:\n- "
            + "\n- ".join(problemas)
        )
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": conteudo},
                {
                    "role": "assistant",
                    "content": json.dumps(roteiro, ensure_ascii=False),
                },
                {"role": "user", "content": pedido},
            ],
            response_format={"type": "json_schema", "json_schema": esquema},
        )
        corrigido = json.loads(resposta.choices[0].message.content)
        _aparar_hook_final(corrigido)
        restantes = _auditar_leigo(cliente, cfg, corrigido)
        if len(restantes) < len(problemas):
            roteiro = corrigido
            problemas = restantes
        if problemas:
            print(
                f"[aviso] Auditoria pró-leigo ainda aponta {len(problemas)} "
                "problema(s) após a reescrita; seguindo com a melhor versão."
            )
        else:
            print("[roteiro] Reescrita aprovada pela auditoria pró-leigo.")
        palavras = _contar_palavras(roteiro["texto_video"])

    print(f"[roteiro] {palavras} palavras faladas (faixa {minimo}-{limite})")
    print(f"[roteiro] Tema do dia: {roteiro['tema']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    if roteiro.get("hook"):
        print(f"[roteiro] Hook: {roteiro['hook']}")
    if roteiro.get("implicacao"):
        print(f"[roteiro] Implicação: {roteiro['implicacao']}")
    if roteiro.get("tese"):
        print(f"[roteiro] Tese: {roteiro['tese']}")
    if roteiro.get("impacto_carreira"):
        print(f"[roteiro] Impacto na carreira: {roteiro['impacto_carreira']}")
    if roteiro.get("o_que_observar"):
        print(f"[roteiro] O que observar: {roteiro['o_que_observar']}")
    return roteiro
