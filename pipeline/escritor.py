"""Seleção da trend do dia e geração de título, descrição e roteiro do vídeo.

Duas etapas:
1. `selecionar_trend` — escolha guiada SOMENTE pela audiência (diretriz de
   2026-07-18: sem pesos nem filtros editoriais): o modelo recebe as
   candidatas do dia, os últimos vídeos publicados COM as métricas reais
   (views/likes da Data API) e a régua de ENGAJAMENTO do canal, e escolhe a
   trend com a maior chance de performar com o público DESTE canal. As métricas de cada
   vídeo recente vão para o prompt NORMALIZADAS PELA IDADE (views por hora ao
   lado das views brutas): views brutas medem idade tanto quanto qualidade, e
   comparar um vídeo de 7 dias com um de 3 horas fazia o tema do último pico
   parecer eterno — era assim que um ciclo de notícia já morto continuava
   sendo escolhido (ver `_resumo_recentes`). Duas regras duras, aplicadas em
   código e não só pedidas no prompt: (a) a verificação de vídeo repetido
   (depois da seleção): uma chamada ao GPT confere se a escolhida cobriria o mesmo
   fato de um vídeo publicado nas últimas JANELA_REPETICAO_HORAS — se sim, a
   candidata sai da disputa e a seleção refaz (com 3-4 execuções/dia sobre a
   mesma janela de posts do X, a ressalva só no prompt deixava passar o mesmo
   fato reformulado); e (b) só nos SHORTS, o RODÍZIO DE TEMAS (2026-08-04): as
   candidatas do macrotema do Short anterior saem da disputa antes da escolha,
   de modo que cada Short saia de um tema diferente do anterior. Devolve também
   uma consulta curta do assunto, usada pela busca aberta de clipes do formato
   longo. A régua de audiência prioriza RETENÇÃO (quanto do vídeo quem abriu
   assistiu): os vídeos publicados que seguraram RETENCAO_MINIMA% ou mais
   entram no prompt marcados como ALTA RETENÇÃO, e é com o ASSUNTO deles que a
   candidata escolhida precisa se parecer (2026-08-16, corrigido em
   2026-08-17: a régua media o gancho e a semelhança era livre).
2. `gerar_roteiro` — com a trend escolhida e os posts do X, escreve o
   roteiro em enquadramento de ANÁLISE/EDUCACIONAL (formato explicativo), em
   tom adulto e inteligente (ritmo de fala natural, vocabulário preciso de
   telejornal, estrutura PREVIEW → CONTEXTUALIZAÇÃO → ACONTECIMENTO →
   CONSEQUÊNCIA → CONCLUSÃO, com a conclusão entregando o que o preview
   prometeu e emendando de volta nele no reinício — o loop), SEMPRE
   citando as fontes (as contas do X que trouxeram o fato, e o veículo que elas
   citam), dentro de uma FAIXA dura de palavras (piso e teto derivados de
   VIDEO_DURACAO — o teto sozinho deixava o vídeo sair com metade da
   duração-alvo). Ao final, a AUDITORIA
   PRÓ-LEIGO (`_auditar_leigo`, chamada própria ao GPT) confere título,
   descrição e narração contra as regras de leigo (nome de nicho, jargão,
   teaser/frase vazia na descrição, âncora ausente) e reprova com UMA
   reescrita — as regras só no prompt vazavam ("Kimi K3", "GPUs" em título;
   "veja o que mudou" em descrição).

SEO e GEO (2026-08-07): a seleção devolve também uma `consulta_youtube` (no
idioma do canal, linguagem de espectador), com a qual `seo.panorama_do_dia`
lê da YouTube Data API os vídeos que OUTROS canais publicaram sobre o mesmo
fato nas últimas horas. Esse panorama entra no material do roteirista ao lado
da régua interna do canal, e com ele o roteiro passa a devolver dois campos
novos: `tags` (que iam VAZIAS no upload desde sempre — o pipeline sempre leu
`roteiro.get("tags")` e o esquema nunca teve o campo) e `resposta_curta` (a
frase autossuficiente que a descrição publica num par P:/R:, para ser citável
por buscador com IA). No formato longo cada tópico ganha ainda uma `citacao`
literal, que vira o carimbo de tempo dos capítulos.

O SHORT ABRE COM PREVIEW, não mais com pergunta (2026-08-25, a pedido do
usuário). A PERGUNTA ESQUISITA saiu da narração do Short pelo mesmo caminho
que já tinha feito na do longo: ela continua existindo como campo `pergunta`,
mas só alimenta o par P:/R: da descrição — ninguém a ouve. No lugar dela entrou
o `preview`: uma frase de até 14 palavras que diz, na cara, o que o vídeo vai
entregar, SEM dar o número e a fonte que o bloco do ACONTECIMENTO dá — preview
que entrega tudo na primeira frase deixa o resto do vídeo sem motivo. A ordem
passou a ser PREVIEW → CONTEXTUALIZAÇÃO → ACONTECIMENTO, e o resto do formato
não mudou: consequência única, conclusão em disputa e o LOOP, que agora emenda
de volta no preview. A faixa de duração e a de palavras seguem as mesmas.

FORMATO LONGO (`--long-take`, cfg.formato == "longo"): as duas etapas trocam
de prompt e de esquema, mantendo a mesma mecânica. A seleção passa a exigir
pauta que renda EXATAMENTE TOPICOS_MAX tópicos (três recortes diferentes do
mesmo fato, tipicamente pelas quatro óticas do canal — tecnologia/IA,
negócios, mercado de trabalho, mercado financeiro), e prefere trends com mais
posts com clipe; e a auditoria ganha regras próprias (fontes nominais, os
tópicos, a análise, nada dependendo de texto na tela). A regra dura (veto a
repetição) compara só com os vídeos LONGOS já publicados — Short e análise são
conteúdos diferentes.

O ROTEIRO LONGO É O DESENHO DA MONTAGEM (2026-08-25). O vídeo passou a ser
montado em QUATRO PARTES separadas, coladas no ffmpeg (montagem_longa.py):
abertura + uma parte por pauta. Isso torna DURAS três coisas que antes eram
preferências do prompt, e as três são conferidas em código antes de a narração
ser paga (`_conferir_estrutura_longa`):

  - EXATAMENTE três tópicos. Não é mais uma faixa: três tópicos são três
    partes, três manchetes e três clipes distintos.
  - a `citacao` de CADA tópico existe LITERALMENTE em `texto_video`. Ela deixou
    de ser só o carimbo do capítulo: é o ponto em que o vídeo é PARTIDO. Sem
    ela não há onde cortar, e o roteiro volta para reescrita.
  - a `citacao` do PRIMEIRO tópico chega até ABERTURA_MAX_PALAVRAS palavras do
    começo (2026-08-26). A abertura não tem duração própria — ela é o que vier
    ANTES dessa citação —, então essa citação é o tamanho dela. Sem esta regra
    a citação podia ser copiada do meio do bloco do tópico 1, e a abertura
    engolia a pauta: foi o vídeo publicado no canal US em 26/08, com 45,4s de
    abertura contra os ~10s do desenho.

A ESTRUTURA DO LONGO DEIXOU DE SER A DO SHORT em 2026-08-24, a pedido do
usuário, que descreveu o resultado anterior como "roteiro e montagem confusos".
Saiu a PERGUNTA ESQUISITA de abertura (que continua existindo como campo, mas
só para o par P:/R: da descrição — ela não é mais falada) e saiu o bloco único
de payload de carreira no fim. Entraram: (1) a PAUTA FALADA, no máximo 18
palavras, dizendo em voz alta o que o vídeo vai tratar, na ordem — junto da
contextualização geral ela forma a ABERTURA, a primeira parte do vídeo, que
tem que caber em ~10 segundos — MEDIDOS desde 26/08, aqui em palavras e em
`manchetes.planejar_partes` em segundos do áudio final; (2) TRÊS BATIDAS por
pauta — contextualização, acontecimento factual e ANÁLISE (campo `analise`),
que é a batida que não pode faltar; (3) o FECHO como SÍNTESE (campo `sintese`), costurando as três análises
em vez de repetir uma delas. A frase de VIRADA entre pautas ganhou peso:
o pipeline abre uma PAUSA de silêncio antes dela (ver silencio.py), corta o
vídeo ali e troca manchete e clipe, então ela precisa ser autossuficiente.

ECONOMIA MICRO SAIU DO ROTEIRO em 2026-08-25, a pedido do usuário. O campo
`bolso` ("o que isso faz no seu dinheiro / no seu bolso") virou `analise`, e a
batida (c) de cada pauta passou a ser o que o FATO muda — quem ganha, quem
perde, que precedente abre —, nunca preço, salário, imposto, tarifa ou conta de
quem assiste. As menções que sobraram no arquivo são PROIBIÇÕES no prompt e na
auditoria; não reintroduzir a leitura de bolso sem pedido explícito.

As QUATRO ÓTICAS deixaram de ser uma cota em 2026-08-04: elas continuam sendo a
fonte natural dos tópicos, mas o roteiro pode trocar uma delas por outro
recorte (regulação, concorrente, usuário, precedente) quando o fato não tem
aquela leitura de verdade — forçar uma leitura que não existe produzia
exatamente a frase de analista vazia que a auditoria reprova.
"""

import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from openai import OpenAI

from .classificacao import MACROTEMAS, MACROTEMAS_DESCRICAO
from .config import (
    AVISO_DADOS_EXTERNOS,
    LONGO_ABERTURA_MAX_S,
    LONGO_ABERTURA_S,
    LONGO_MAX_S,
    LONGO_MIN_POSTS_VIDEO,
    LONGO_NUM_TRENDS,
    LONGO_MIN_S,
    ENGAJAMENTO_MINIMO,
    RETENCAO_MINIMA,
    Config,
)
from .cortes import localizar_citacao
from .seo import limpar_tags, resumo_para_prompt

# Ritmo da narração em palavras por segundo do ÁUDIO FINAL, a VELOCIDADE
# NORMAL (1.0x). "Final" é o ponto todo: é o áudio DEPOIS da aceleração e
# DEPOIS do corte de silêncios (silencio.py) — exatamente o que o piso duro de
# duração mede em main.py. A versão anterior media o áudio BRUTO e por isso
# ignorava o corte de silêncio, que come de 4% a 19% da narração; com a
# velocidade multiplicando por fora, o orçamento de palavras errava para baixo
# em ~20% e o Short caía sistematicamente abaixo do piso de 50s.
#
# RECALIBRADO em 2026-08-05 sobre as 10 narrações reais dos crons do Render
# (8 Shorts + 2 longos, os dois canais), dividindo palavras faladas pela
# duração final e normalizando pela velocidade de cada formato:
#
#   curto (1.25x): 2,47 a 3,07 palavras/s, média 2,74
#   longo (1.00x): 2,73 a 2,92 palavras/s, média 2,82
#
# Os dois formatos convergem, então uma constante só serve para ambos. O valor
# anterior (2,2) ficava abaixo de TODAS as medições.
PALAVRAS_POR_SEGUNDO = 2.76
# Piso de palavras como fração do teto: o teto sozinho deixava o modelo
# entregar metade das palavras e o vídeo sair com metade da duração-alvo.
FRACAO_MINIMA = 0.85
# Ritmo mais LENTO já medido numa narração real do formato longo: 2,4
# palavras/s, no vídeo do canal US de 26/08 (361 palavras faladas em 147,9s de
# fala). Fica abaixo da faixa registrada em PALAVRAS_POR_SEGUNDO, que é uma
# MÉDIA — e média não serve para converter um TETO. Aqui o erro barato é
# reprovar um roteiro que ainda não custou nada, e o caro é deixar passar um
# texto que, falado devagar, estoura o teto depois da narração já paga.
RITMO_LENTO_MEDIDO = 2.4
# Teto de palavras da ABERTURA (pauta falada + contextualização geral), usado na
# conferência que roda ANTES da narração. É o teto em segundos convertido pelo
# ritmo lento: passar aqui garante passar na conferência do áudio final
# (manchetes.planejar_partes), que é a que vale.
ABERTURA_MAX_PALAVRAS = int(LONGO_ABERTURA_MAX_S * RITMO_LENTO_MEDIDO)
# Tolerância sobre o teto de palavras antes de pedir ao modelo para encurtar.
FOLGA_PALAVRAS = 1.15
# Tentativas de ajuste da faixa de palavras (2026-08-04). Era UMA só, e uma só
# não segurava: os Shorts do canal americano vinham saindo com 17 a 35 segundos
# contra uma duração-alvo de 60 — o modelo entregava metade das palavras, a
# única tentativa de correção também ficava curta, e o vídeo ia ao ar assim.
# Chamada de texto é a etapa mais barata do pipeline; insistir aqui custa muito
# menos do que abortar depois da narração no piso duro de duração.
TENTATIVAS_FAIXA_PALAVRAS = 3
# Teto de vídeos SEGUIDOS do mesmo macrotema: REMOVIDO em 2026-07-28. Ele valia
# 4 e era a única regra de variabilidade do canal, mas o custo apareceu nos
# números: as três sequências conferidas no canal BR mostram o mesmo padrão —
# 4 vídeos de guerra somando 55 mil views e, no 5º, o teto forçando a troca
# para a melhor candidata do macrotema SOBRANDO, que rendeu 258 views. Desde
# 14/07 foram 10 vídeos assim, 2.296 views somadas (18% da produção, 0,6% do
# resultado). O teto não escolhia o segundo melhor tema: escolhia o melhor de
# um macrotema que a audiência ignora. A variabilidade passa a ser decidida
# pela própria seleção guiada pela audiência, que agora enxerga o ciclo
# esfriando pelas views por hora (ver `_resumo_recentes`).
# Janela da verificação de vídeo repetido: vídeo publicado há menos que isto
# cobre a mesma janela de posts do X das execuções seguintes (JANELA_HORAS=24
# + folga), então a candidata só passa se o resumo dela tiver fato novo. Mais
# antigo que isso, qualquer desenvolvimento já é naturalmente novo.
JANELA_REPETICAO_HORAS = 36
# No formato longo a janela é maior: o cron dispara menos vezes por dia e
# refazer a MESMA análise no dia seguinte é pior do que refazer uma manchete.
JANELA_REPETICAO_HORAS_LONGO = 72
# Formato LONGO: a faixa de palavras sai da FAIXA DURA de duração do formato
# (120 a 150s), não de VIDEO_DURACAO. A margem é ASSIMÉTRICA e puxa a faixa
# para DENTRO em cima e para CIMA embaixo, porque as duas pontas custam coisas
# diferentes: estourar o teto só encarece o TTS, enquanto furar o piso de 120s
# está proibido e aborta a execução em main.py depois da narração já paga.
#
# A margem de baixo subiu de 6 para 10 em 2026-08-05, junto com a recalibração
# de PALAVRAS_POR_SEGUNDO: ela precisa cobrir a narração mais RÁPIDA (é a que
# fura o piso), e com 6 o piso caía em 119s na ponta rápida das duas medições
# de formato longo — reprovando por 1 segundo. São só duas medições, então a
# margem aqui é mais generosa que a do Short de propósito.
MARGEM_LONGO_MIN_S = 10  # mira acima do piso
MARGEM_LONGO_MAX_S = 6  # mira abaixo do teto
# Duração (s) a partir da qual um vídeo já publicado no canal conta como
# LONGO. A regra dura do formato longo (veto a vídeo
# repetido) olha só para os vídeos longos: senão a rajada de Shorts do dia
# bloquearia todo vídeo longo, e a análise de um fato que virou Short há três
# horas é conteúdo novo — outro formato, outra profundidade, outro público.
# Fica acima do teto prático do Short e abaixo do piso do longo (50 e 120s):
# qualquer valor nessa janela separa os dois formatos sem ambiguidade, e 90
# ainda reconhece como longos os vídeos publicados na faixa antiga (90-120s).
DURACAO_MINIMA_LONGO = 90
# TÓPICOS do formato longo: EXATAMENTE TRÊS (2026-08-25, desenho do usuário).
#
# Deixou de ser uma faixa (era 3 a 5, de 2026-08-04) porque o vídeo longo passou
# a ter uma ESTRUTURA FIXA DE QUATRO PARTES, montadas separadamente e coladas no
# ffmpeg (ver montagem_longa.py): a abertura mais uma parte por pauta. Quatro
# partes são três trocas de manchete e três clipes distintos — um por pauta —, e
# nada disso admite um número variável de tópicos. Roteiro que não vier com três
# é reescrito; se insistir, a execução aborta antes de pagar a narração.
#
# As quatro óticas do canal (tecnologia/IA, negócios, trabalho, mercado)
# continuam sendo a fonte natural dos tópicos — nunca foram uma cota.
# TOPICOS_MIN sumiu junto com a faixa: com três fixos, mínimo e máximo eram o
# mesmo número, e manter dois nomes para ele só criaria a chance de um dia
# divergirem.
TOPICOS_MAX = 3
# RODÍZIO DE TEMAS DOS SHORTS REMOVIDO (2026-08-29, pedido do usuário:
# "remova completamente o rodizio de temas"). Ele existiu de 2026-08-04 a
# 2026-08-29 e tirava da disputa as candidatas do macrotema do Short anterior,
# para que dois Shorts seguidos não saíssem do mesmo tema.
#
# MEDIDO no dia da remoção, execução BR das 18h: a triagem aprovou material de
# 2 das 6 candidatas ("Photon Matrix" e "Mini Pi Plus", ambas hardware-chips) e
# o rodízio derrubou as duas, porque hardware-chips era o tema do Short
# anterior. Sobraram só candidatas de clipe já reprovado, as três tentativas
# morreram nelas e a execução abortou sem publicar. O rodízio não cedeu porque
# a cessão dele só olha se SOBROU candidata, não se sobrou candidata com
# imagem.
#
# Com isso volta a valer, sem exceção, o que a remoção de 2026-07-28 já havia
# estabelecido: nenhum teto de macrotema seguido: quem troca de assunto é o
# sinal de audiência normalizado pela idade (views/h), que mostra o ciclo
# esfriando sem precisar vetar ninguém.

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
            "consulta_clipes": {
                "type": "string",
                "description": (
                    "Consulta CURTA do assunto em inglês: 3 a 6 palavras, só os "
                    "nomes próprios principais + o acontecimento central (ex.: "
                    "'Anthropic Claude global outage'). É com ela que o formato "
                    "longo procura clipes do fato fora das contas seguidas. NÃO "
                    "empilhe detalhes, sintomas, códigos de erro nem sinônimos — "
                    "consulta longa demais zera os resultados."
                ),
            },
            "consulta_youtube": {
                "type": "string",
                "description": (
                    "Consulta de busca do YouTube, NO IDIOMA DO CANAL definido "
                    "nas instruções: 2 a 5 palavras, como uma PESSOA "
                    "procuraria este assunto na barra de busca (ex.: 'demissões "
                    "inteligência artificial', 'nvidia corte preço chip'). É com "
                    "ela que o pipeline descobre que outros vídeos sobre este "
                    "fato já saíram hoje. Não é a mesma coisa que a consulta de "
                    "clipes: aqui é linguagem de espectador, não de agência."
                ),
            },
        },
        "required": [
            "trend",
            "motivo",
            "consulta_clipes",
            "consulta_youtube",
        ],
    },
}

# TAGS do vídeo (2026-08-07). Elas SEMPRE existiram na chamada de publicação
# (`publicar(..., tags=roteiro.get("tags"))`) e NUNCA no esquema do roteiro —
# ou seja, todo vídeo do canal subiu com a lista de tags vazia desde o começo.
# É o único campo de metadados do YouTube em que cabe o nome próprio que o
# título proíbe: tag não é lida pelo espectador, então o teste do leigo não se
# aplica, e é por "Claude 4.5", "H200" ou "layoff" que procura quem já conhece
# o assunto.
TAGS_PROPRIEDADE = {
    "type": "array",
    "description": (
        "De 8 a 15 termos de BUSCA no idioma do canal, do mais específico para "
        "o mais geral, SEM '#'. Aqui NÃO vale o teste do leigo do título: é "
        "onde entram os nomes próprios, modelos, siglas e produtos que o "
        "título teve de traduzir. Use os termos do vocabulário de tags da "
        "concorrência de hoje quando descreverem de verdade este vídeo. "
        "PROIBIDO: tag que não tem relação com o conteúdo, nome de canal "
        "concorrente e repetição do mesmo termo com outra caixa."
    ),
    "items": {"type": "string"},
}

# GEO (Generative Engine Optimization): a frase que um motor de resposta com IA
# consegue CITAR sem ter assistido ao vídeo. A descrição escrita para gente
# depende do vídeo ("isso significa que...") e por isso não é extraível; esta
# repete o sujeito, o número, a data e a fonte dentro da própria frase.
RESPOSTA_CURTA_PROPRIEDADE = {
    "type": "string",
    "description": (
        "UMA frase, no idioma do canal, até 30 palavras, que RESPONDE o campo "
        "`pergunta` e se sustenta sozinha fora do vídeo. Nomeia "
        "por extenso quem fez o quê, com o número, a data e a fonte "
        "('A Nvidia cortou o preço do H200 em 40% em 5 de agosto, segundo a "
        "Reuters'). PROIBIDO começar com 'isso', 'ele', 'a empresa' ou "
        "qualquer referência que só faça sentido depois de assistir; "
        "proibido prometer sem responder; proibido dado que a narração não "
        "diz."
    ),
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
            "preview": {
                "type": "string",
                "description": (
                    "O PREVIEW de abertura (0-2s): a frase que diz, na cara, o "
                    "que este vídeo vai entregar — o assunto e o que está em "
                    "jogo nele, em coisa concreta (gente, dinheiro, ação). "
                    "'A empresa mais valiosa do mundo perdeu uma fábrica "
                    "inteira numa noite.' 'Um robô de contratação saiu do ar e "
                    "travou meio milhão de currículos.' Máximo 14 palavras. Ele "
                    "PROMETE sem ENTREGAR: o número exato, a data e a fonte são "
                    "do bloco do ACONTECIMENTO, e antecipá-los aqui deixa o "
                    "resto do vídeo sem motivo para existir. PROIBIDO: pergunta "
                    "de qualquer tipo; preâmbulo de youtuber ('neste vídeo você "
                    "vai ver', 'vamos falar sobre', 'fica até o final'); "
                    "promessa abstrata, sem coisa concreta dentro ('nada será "
                    "como antes'); cauda de suspense ('e o que veio depois muda "
                    "tudo'); e abrir por data, contexto ou nome de "
                    "instituição. A primeira frase de texto_video DEVE ser "
                    "exatamente esta (copiada palavra por palavra, antes de "
                    "qualquer audio tag)."
                ),
            },
            "pergunta": {
                "type": "string",
                "description": (
                    "A pergunta que o vídeo responde, para a DESCRIÇÃO (par "
                    "P:/R: que os buscadores com IA extraem) — NÃO é falada na "
                    "narração. Concreta e específica, no máximo 14 palavras, "
                    "respondida por `resposta_curta`."
                ),
            },
            "consequencia": {
                "type": "string",
                "description": (
                    "A CONSEQUÊNCIA concreta que o vídeo entrega — o que muda "
                    "para quem trabalha, investe ou usa aquilo ('isso significa "
                    "que...'). Uma só, decidida antes de escrever o texto_video."
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
                    "Estrutura obrigatória em CINCO blocos: "
                    "1) PREVIEW (a primeira frase = campo preview) "
                    "→ 2) CONTEXTUALIZAÇÃO (o que é isso e por que o preview "
                    "faz sentido; se o assunto for de nicho, é aqui que ele é "
                    "amarrado em algo que o leigo conhece — 'a empresa por trás "
                    "do ChatGPT') → 3) ACONTECIMENTO (o que aconteceu de "
                    "fato, com número, nome e mecanismo, na fonte citada) → "
                    "4) CONSEQUÊNCIA (o que isso muda para quem trabalha, "
                    "investe ou usa aquilo) → 5) CONCLUSÃO (a ENTREGA do que o "
                    "preview prometeu, em uma frase seca — sem moral da "
                    "história e sem CTA falado). A conclusão é o CORTE: ela "
                    "fecha de um jeito que emenda de volta no preview "
                    "quando o vídeo reinicia (o Short roda em loop). A última "
                    "frase deve ser NOVA: é PROIBIDO repetir o preview (ou "
                    "qualquer frase anterior) palavra por palavra — quem "
                    "repete o preview é o reinício do loop, não o texto. Essa "
                    "última frase carrega A DISPUTA: um FATO do próprio vídeo "
                    "que deixa duas leituras defensáveis em pé (quem está "
                    "certo, quem paga a conta, se valeu a pena), de modo que "
                    "quem assiste termine com uma opinião na ponta da língua. "
                    "PROIBIDO virar isca: nada de pergunta ao espectador "
                    "('você concorda?'), nada de opinião do canal, nada de "
                    "pedir comentário — é fato com tensão, não convite."
                ),
            },
            "resposta_curta": RESPOSTA_CURTA_PROPRIEDADE,
            "tags": TAGS_PROPRIEDADE,
        },
        "required": [
            "tema",
            "preview",
            "pergunta",
            "consequencia",
            "titulo",
            "descricao",
            "resposta_curta",
            "tags",
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
            "pauta_falada": {
                "type": "string",
                "description": (
                    "A PAUTA DO VÍDEO, dita em voz alta na abertura: a lista "
                    "do que o vídeo vai tratar, em NO MÁXIMO 18 palavras (cerca "
                    "de 6 segundos de fala). Nomeia os tópicos na MESMA ORDEM "
                    "em que aparecem, cada um pela coisa concreta ('drones a "
                    "1.900 quilômetros, um navio sem tripulação que atirou, e o "
                    "gás que o Irã achou'). É a PRIMEIRA COISA de texto_video, "
                    "copiada caractere por caractere, antes de qualquer audio "
                    "tag. PROIBIDO 'neste vídeo você vai ver', 'vamos falar "
                    "sobre', 'fique até o final' — comece pela coisa. Enquanto "
                    "ela é falada, um painel na tela lista os três títulos."
                ),
            },
            "pergunta": {
                "type": "string",
                "description": (
                    "A pergunta que o vídeo responde, para a DESCRIÇÃO (par "
                    "P:/R: que os buscadores com IA extraem) — NÃO é falada na "
                    "narração. Concreta e específica, no máximo 14 palavras, "
                    "respondida por `resposta_curta`."
                ),
            },
            "tese": {
                "type": "string",
                "description": (
                    "Em uma frase: a leitura que costura os tópicos do vídeo "
                    "sobre este acontecimento. É o fio condutor do vídeo "
                    "inteiro — decida antes de escrever a narração."
                ),
            },
            "topicos": {
                "type": "array",
                "description": (
                    f"EXATAMENTE {TOPICOS_MAX} TÓPICOS que o vídeo cobre, "
                    "na ordem em que aparecem na narração — nem mais, nem "
                    "menos: o vídeo é montado em quatro partes (abertura + uma "
                    "por tópico) e um número diferente de três QUEBRA a "
                    "montagem. Cada tópico é um recorte DIFERENTE do mesmo "
                    "acontecimento, com dado próprio — não é uma repetição do "
                    "anterior com outras palavras. As quatro óticas do canal "
                    "(tecnologia e IA, negócios, mercado de trabalho, mercado "
                    "financeiro) são a fonte natural dos tópicos, mas não são "
                    "uma cota: cubra o recorte que o material sustenta (a "
                    "regulação, o concorrente, o usuário, o precedente) em vez "
                    "de inventar um."
                ),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "titulo": {
                            "type": "string",
                            "description": (
                                "O tópico em até 6 palavras (ex.: 'quem paga a "
                                "conta do data center'). VAI APARECER ESCRITO "
                                "NA TELA, em caixa alta, como a manchete deste "
                                "trecho — e no índice da abertura. Diga a "
                                "COISA (fato, número, quem paga), nunca a "
                                "categoria ('impactos', 'contexto', "
                                "'análise'), e sem ponto final."
                            ),
                        },
                        "dado": {
                            "type": "string",
                            "description": (
                                "O dado concreto do material recebido que "
                                "sustenta este tópico (número, nome, empresa, "
                                "prazo) e a fonte nominal dele."
                            ),
                        },
                        "analise": {
                            "type": "string",
                            "description": (
                                "A ANÁLISE deste tópico, em 1 frase: o que o "
                                "fato MUDA na prática — quem ganha, quem "
                                "perde, o que deixa de ser possível, que "
                                "precedente abre, o que passa a valer a partir "
                                "de agora. Concreta e amarrada ao dado deste "
                                "tópico. PROIBIDO conselho genérico de coach, "
                                "futurologia sem base no material e qualquer "
                                "leitura de preço, salário, imposto, tarifa ou "
                                "conta do espectador."
                            ),
                        },
                        "citacao": {
                            "type": "string",
                            "description": (
                                "Trecho LITERAL de texto_video (5 a 12 "
                                "palavras, copiado caractere por caractere, "
                                "sem audio tags) onde este tópico COMEÇA na "
                                "narração. Do SEGUNDO tópico em diante é a "
                                "FRASE DE VIRADA que fecha o anterior e nomeia "
                                "este. NO PRIMEIRO TÓPICO NÃO HÁ VIRADA (não "
                                "existe tópico anterior): copie as PRIMEIRAS "
                                "palavras do bloco dele, a frase logo depois "
                                "da contextualização geral da abertura — e "
                                "nunca uma frase do meio ou do fim do bloco, "
                                "porque tudo que ficar antes dela vira a "
                                "ABERTURA do vídeo e ela tem um teto de "
                                "segundos. É o CORTE do "
                                "vídeo: o pipeline parte o vídeo em quatro "
                                "partes exatamente aqui, abre a pausa de "
                                "silêncio, troca a manchete na tela e troca o "
                                "clipe. Também vira o carimbo de tempo do "
                                "capítulo na descrição. Trecho que não existir "
                                "LITERALMENTE em texto_video quebra a montagem "
                                "e o roteiro é devolvido para reescrita — "
                                "copie, não parafraseie."
                            ),
                        },
                    },
                    "required": ["titulo", "dado", "analise", "citacao"],
                },
            },
            "sintese": {
                "type": "string",
                "description": (
                    "O FECHO do vídeo, em 1 a 2 frases: a linha que une as "
                    "análises dos três tópicos numa só — o que a soma deles "
                    "diz sobre o que está mudando. NÃO repete a análise de um "
                    "tópico: costura as três. Nada de conselho genérico de "
                    "coach ('se reinvente', 'esteja preparado') e nada de "
                    "leitura de preço, salário ou conta do espectador."
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
                    "caracteres. ABRE PELO TÓPICO 1: é ele que a CAPA do vídeo "
                    "mostra e é ele que o espectador ouve nos primeiros "
                    "segundos, então o título tem que prometer a MESMA coisa "
                    "que a capa — capa anunciando um assunto e título "
                    "anunciando outro entrega um vídeo diferente do que a "
                    "pessoa clicou. Os outros dois tópicos entram depois, na "
                    "ordem, se couberem. Direto e factual: ator + ação "
                    "concreta, com "
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
                    "a fonte nominal, a leitura que une os tópicos e o "
                    "impacto prático no mercado de trabalho. Mesmo TESTE DO "
                    "LEIGO do título. PROIBIDO: cauda de suspense, CTA ('veja "
                    "o que mudou', 'saiba mais') e frase de analista vazia."
                ),
            },
            "texto_video": {
                "type": "string",
                "description": (
                    "Texto/roteiro narrado do vídeo, no idioma definido nas "
                    "instruções, seguindo a ESTRUTURA das instruções: PAUTA "
                    "FALADA (o campo `pauta_falada`, copiado como início do "
                    "texto) → CONTEXTUALIZAÇÃO GERAL → AS TRÊS PAUTAS, cada uma "
                    "com CONTEXTUALIZAÇÃO + ACONTECIMENTO FACTUAL + ANÁLISE (o "
                    "campo `analise` do tópico), separadas por uma FRASE DE "
                    "VIRADA → FECHO (a `sintese` mais o que observar). A "
                    "abertura (pauta falada + contextualização geral) tem que "
                    "caber em CERCA DE 10 SEGUNDOS de fala, porque ela é a "
                    "primeira das quatro partes do vídeo. Ritmo de fala natural (frases de 8 a 18 "
                    "palavras, teto 22), vocabulário preciso de telejornal, "
                    "tom adulto de analista que respeita o espectador. Toda "
                    "afirmação central atribuída nominalmente à fonte "
                    "(a conta do X, ou o veículo que ela cita), somente fontes das "
                    "listas recebidas. Cada tópico a partir do segundo abre com "
                    "uma FRASE DE VIRADA curta que fecha o anterior e nomeia o "
                    "próximo. O vídeo NÃO tem legendas, e as manchetes na tela "
                    "só repetem o que a narração já disse: ela precisa se "
                    "sustentar sozinha, sem 'como você vê aqui' nem referência "
                    "a imagem."
                ),
            },
            "resposta_curta": RESPOSTA_CURTA_PROPRIEDADE,
            "tags": TAGS_PROPRIEDADE,
        },
        "required": [
            "tema",
            "pauta_falada",
            "pergunta",
            "tese",
            "topicos",
            "sintese",
            "o_que_observar",
            "titulo",
            "descricao",
            "resposta_curta",
            "tags",
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
Você é o auditor pró-leigo de um canal de vídeos curtos de análise, sem recorte
temático (qualquer assunto pode virar vídeo). Você recebe o título, a descrição
e a narração de um vídeo e verifica as regras abaixo. O espectador
é um adulto leigo que NUNCA ouviu falar de modelos de IA, labs, startups e
siglas de nicho — Google, iPhone, Elon Musk, ChatGPT ele conhece; Grok, Kimi
K3, Anthropic, EBITDA, GPU ele NÃO conhece.

CALIBRAGEM (vale para as três partes):
- Nome próprio UNIVERSALMENTE conhecido (países, Google, Elon Musk, ChatGPT,
  iPhone...) é permitido em qualquer quantidade — nunca é problema.
  O que reprova é nome de NICHO (modelo de IA, lab, startup, app pouco
  conhecido, sigla técnica ou financeira) sem tradução para o efeito concreto.
- Termos do dia a dia NÃO são jargão: inteligência artificial, IA/AI, app,
  site, robô, chip, e tudo que um adulto ouve num telejornal (bilhões, juros,
  demissão, falência, bolsa).
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
6. A PRIMEIRA frase é o PREVIEW: em no máximo 14 palavras, e com coisa
   concreta dentro (número, gente, dinheiro, ação), ela diz o que o vídeo vai
   entregar. REPROVAM: abrir por PERGUNTA de qualquer tipo; preâmbulo de
   youtuber ("neste vídeo você vai ver", "vamos falar sobre", "fica até o
   final"); promessa abstrata, sem coisa concreta ("nada será como antes");
   cauda de suspense ("e o que veio depois muda tudo"); e abrir por data,
   contexto ou nome de instituição.
7. A narração ENTREGA o que o preview prometeu antes de acabar, com o fato
   concreto. Promessa que fica sem entrega no texto REPROVA — e REPROVA
   também o preview que já entrega tudo (número exato, data e fonte na
   primeira frase), porque ele deixa o resto do vídeo sem motivo.
8. Bloco de CONTEXTUALIZAÇÃO logo depois do preview: se o assunto CENTRAL é de
   nicho, ele precisa ser ancorado em algo que o leigo conhece ("a empresa por
   trás do ChatGPT"); sem âncora REPROVA. Assunto universalmente conhecido não
   precisa de âncora.
9. No máximo 1 nome próprio de nicho no vídeo inteiro (veículo ou conta do X
   citado como FONTE não conta; nome universalmente conhecido não conta).
10. Nenhuma frase pode depender do que está na tela ("como você vê no
   gráfico", "veja a tabela") — a narração tem que se sustentar de olhos
   fechados.

Liste em "problemas" cada violação com o termo/frase exato citado. NÃO
invente problema: o que segue as regras passa, e "aprovado" = true com zero
problemas.\
"""

INSTRUCOES_AUDITORIA_LEIGO_LONGO = """\
Você é o auditor de um canal de vídeos de ANÁLISE de 90 a 120 segundos, feitos
para um adulto leigo que está procurando emprego ou em transição de carreira.
Você recebe o título, a descrição e a narração de um vídeo e verifica as
regras abaixo. O espectador conhece Google, iPhone, Elon Musk, ChatGPT; ele
NÃO conhece Grok, Kimi K3, Anthropic, EBITDA, GPU.

CALIBRAGEM (vale para as três partes):
- Nome próprio UNIVERSALMENTE conhecido é permitido em qualquer quantidade —
  nunca é problema. O que reprova é nome de NICHO (modelo de IA, lab, startup,
  app pouco conhecido, sigla técnica ou financeira) sem tradução.
- Termos do dia a dia NÃO são jargão: inteligência artificial, IA/AI, app,
  chip, robô, e tudo que se ouve num telejornal (bilhões, juros, inflação,
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
7. PAYLOAD DE ANÁLISE: cada pauta precisa dizer, com fato concreto, o que o
   acontecimento MUDA — quem ganha, quem perde, que precedente abre, o que
   deixa de ser possível. Conselho de coach ("se reinvente", "esteja
   preparado", "invista em você") e futurologia sem base REPROVAM. REPROVA
   também qualquer leitura de ECONOMIA MICRO do espectador (preço, salário,
   imposto, tarifa, conta, "o seu bolso", "o seu dinheiro"): ela saiu do canal.
8. OS TÓPICOS: a narração precisa cobrir EXATAMENTE {topicos_max} recortes
   DIFERENTES do acontecimento, cada um com dado próprio e costurados
   por causa e efeito. REPROVAM: número de tópicos diferente de
   {topicos_max}; dois tópicos
   que dizem a mesma coisa com outras palavras; tópico sem nenhum dado
   concreto; e lista de bullets falados no lugar do encadeamento.
8b. A VIRADA DE PAUTA: cada tópico a partir do segundo abre com uma frase
   curta e AUTOSSUFICIENTE que fecha o anterior e nomeia o próximo — o
   pipeline abre uma pausa de silêncio antes dela. REPROVAM: virar de assunto
   no meio de um parágrafo, sem nenhuma marca; virada que não diz do que se
   trata ("mas tem mais", "e não para por aí"); e numerar em voz alta
   ("segundo ponto", "tópico três", "primeiro", "por último").
8c. AS TRÊS BATIDAS: cada pauta traz contextualização, depois o acontecimento
   factual com número e fonte, depois a análise do que muda — nesta ordem.
   REPROVA a pauta que pula a contextualização e começa no número.
9. Nenhuma frase pode depender de texto na tela ("como você vê aqui", "no
   gráfico") — as manchetes na tela só repetem o que a narração já disse, e o
   vídeo não tem legendas.
10. A ABERTURA é a PAUTA FALADA: as primeiras palavras da narração dizem, em
   no máximo 18 palavras, o que o vídeo vai tratar, nomeando os assuntos na
   mesma ordem em que eles aparecem depois. Somada à contextualização geral,
   ela tem que caber em {abertura_palavras} palavras faladas (~{abertura_s:.0f}
   segundos) — é a primeira das quatro partes do vídeo, e o que vem depois dela
   já é a primeira pauta. CONTE as palavras da abertura antes de julgar.
   REPROVAM: abrir por outra coisa; preâmbulo de youtuber
   ("neste vídeo você vai ver", "vamos falar sobre", "fica até o final"); ordem
   que não bate com a das pautas; e abertura acima do teto de palavras.
11. Fechamento: síntese que costura as análises das pautas + próximo
   marco a observar. REPROVAM: CTA falado, pedido de inscrição, despedida, e
   fecho que só repete a análise de uma das pautas.
12. O TÍTULO ABRE PELO TÓPICO 1. A capa do vídeo é montada a partir da pauta 1
   e do clipe dela, então um título que abre por outro tópico promete uma coisa
   e a capa promete outra. REPROVA o título que começa pelo tópico 2 ou 3, ou
   que não nomeia o tópico 1 em lugar nenhum.

Liste em "problemas" cada violação com o termo/frase exato citado. NÃO invente
problema: o que segue as regras passa, e "aprovado" = true com zero problemas.\
""".format(
    topicos_max=TOPICOS_MAX,
    abertura_palavras=ABERTURA_MAX_PALAVRAS,
    abertura_s=LONGO_ABERTURA_S,
)

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
Você é editor de um canal de vídeos curtos (YouTube Shorts) de ANÁLISE, SEM
RECORTE TEMÁTICO: qualquer assunto pode virar vídeo — tecnologia, IA, negócios,
trabalho, mercado, ciência, saúde, política, mundo, esporte, cultura, crime,
clima, consumo. Nenhum tema é vetado e nenhum é obrigatório.

Você recebe as trends mais faladas do X hoje (cada uma com resumo, macrotema,
imagem mental, VALOR INFORMATIVO e URGÊNCIA), os vídeos CAMPEÕES DE RETENÇÃO do
canal (quando houver) e os últimos vídeos publicados COM as métricas reais de
audiência (views e likes). Todo vídeo do canal é EXPLICATIVO — análise ou
educacional: ele explica o que aconteceu, como funciona e o que muda. Prefira,
portanto, a candidata que rende a melhor explicação (um acontecimento com
causa, mecanismo e consequência claros) e descarte a que só rende manchete.

VALOR DA INFORMAÇÃO — o primeiro corte: entre as candidatas, prefira sempre a
que entrega informação que ainda NÃO é conhecimento comum. Nesta ordem: (1)
vazamento, documento interno, memorando ou número inédito; (2) exclusivo ou
primeira mão; (3) urgência real (marcada como "agora" ou "hoje", ou com prazo
apertando); (4) número concreto de dinheiro, vagas, preço ou prazo. Candidata
marcada como "apenas repercussão, sem fato novo" só vence se TODAS as outras
também forem — repercussão de algo que a audiência já viu ontem é o pior vídeo
possível, por mais quente que esteja o assunto.

FORMATO DO CANAL: o vídeo é montado SOMENTE com os clipes de vídeo anexados
aos posts do X da trend (até 3 clipes; nenhuma foto estática). Todas as
candidatas listadas têm pelo menos 1 post com clipe, mas em empate prefira a
que tem MAIS clipes e o material em vídeo mais forte (veja "apelo visual").

AUDIÊNCIA — O QUE DECIDE ENTRE AS ELEGÍVEIS: escolha a trend com a
maior chance de performar com a audiência DESTE canal, e a régua são os
NÚMEROS listados, não opinião editorial. Os vídeos com o maior VIEWS/H e os
vídeos de ALTO ENGAJAMENTO mostram o tipo de tema, tensão e promessa que este
público clica e assiste até o fim; os de VIEWS/H baixo mostram o que ele
ignora. Compare cada candidata com esses dois grupos e escolha a que mais se
parece com o que está performando. NÃO aplique preferência própria por tema
"nobre" nem equilíbrio de pauta: escolha entre as candidatas que você recebeu a
que os números apontam, e nada mais.

RETENÇÃO ACIMA DE TUDO NA RÉGUA — {piso}% OU MAIS: a métrica que manda é a
RETENÇÃO, quanto do vídeo quem abriu assistiu. Os vídeos marcados como ALTA
RETENÇÃO na lista de campeões seguraram {piso}% ou mais — são eles o molde.

A SEMELHANÇA QUE VALE É A DE ASSUNTO, e só ela. Não é semelhança de formato, de
estrutura de roteiro, de gancho ou de "energia" do título — é DO QUE O VÍDEO
FALA. Leia os assuntos dos vídeos marcados como ALTA RETENÇÃO, veja de que
temas eles tratam, e escolha a candidata cujo ASSUNTO cai no mesmo território.
Uma candidata de tema alheio a tudo que está nessa lista é a pior escolha
possível, por mais atual ou impressionante que ela pareça: o canal já provou em
que assunto a audiência dele fica, e é nesse assunto que o próximo vídeo tem de
estar. Trate os vídeos abaixo de {piso}% como contraexemplo, mesmo quando
tiverem muitas views: views sem retenção é alcance que o feed empurrou e o
espectador recusou.

O RODÍZIO DE TEMAS JÁ FOI APLICADO ANTES DE VOCÊ: as candidatas do tema do
Short anterior já foram removidas da lista pelo pipeline, porque o canal
intercala os temas dos Shorts. Você não precisa (nem deve) gerenciar variedade:
todas as candidatas que chegaram até aqui já estão liberadas nesse quesito, e
entre elas o critério volta a ser só a audiência.

CICLO DE NOTÍCIA ESFRIA — E É VOCÊ QUEM TEM QUE PERCEBER: um assunto quente
(uma onda de demissões, um lançamento, uma queda de mercado) domina o canal por
dias e depois morre, normalmente quando o próprio fato se resolve (acordo,
recuo, número final divulgado). O
sinal de morte está na lista, e é UM só: os vídeos MAIS RECENTES daquele
macrotema com VIEWS/H bem abaixo dos mais antigos do MESMO macrotema. Quando
isso aparecer, o pico antigo já não vale de régua — ele só está no topo das
views acumuladas porque está no ar há mais tempo. Nesse caso escolha o
macrotema com o melhor VIEWS/H RECENTE, mesmo que as views acumuladas dele
sejam menores. O erro que se quer evitar aqui é continuar publicando o assunto
de ontem porque o vídeo de ontem tem o maior número absoluto da lista.

Única ressalva: não escolha uma candidata que renderia um vídeo IDÊNTICO a um
já publicado, sem nenhum fato novo. Cobertura contínua do mesmo assunto com
desenvolvimento novo (novo ataque, nova declaração, novo número) é bem-vinda —
é exatamente o que a audiência está acompanhando.

Gere também uma consulta CURTA do assunto (em inglês, 3 a 6 palavras: nomes
próprios principais + o acontecimento) para a trend escolhida. Ela é o que a
busca aberta de clipes usa no formato longo. Consulta longa e cheia de detalhes
zera os resultados — seja enxuto.

E uma consulta de busca do YOUTUBE, no IDIOMA DO CANAL, com 2 a 5 palavras, do
jeito que um espectador digitaria na barra de busca. Ela serve para descobrir
que outros vídeos sobre este fato já saíram hoje — então use o nome PÚBLICO do
assunto, não o jargão do comunicado.
Responda somente com o JSON pedido.\
"""

INSTRUCOES_SELECAO_LONGO = """\
Você é editor de um canal de vídeos de ANÁLISE (formato longo, 16:9, cerca de
{duracao} segundos) sobre os grandes acontecimentos contemporâneos, SEM RECORTE
TEMÁTICO: qualquer assunto pode virar vídeo, e nenhum tema é vetado.

Você recebe as trends mais faladas do X hoje (cada uma com resumo, macrotema e
imagem mental), os vídeos CAMPEÕES DE RETENÇÃO do canal e os últimos vídeos
publicados COM as métricas reais de audiência (views acumuladas, VIEWS/H e
likes). Atenção: essas métricas são majoritariamente dos vídeos CURTOS do
canal — use-as como régua do que este público responde (tema, tensão,
promessa), não como molde de formato. Compare sempre pelo VIEWS/H: as views
acumuladas medem há quanto tempo o vídeo está no ar tanto quanto medem
qualidade, e o assunto de um ciclo já encerrado costuma exibir o maior número
absoluto da lista muito depois de ter esfriado.

O QUE O VÍDEO LONGO É: uma análise educacional que explica um acontecimento
atual cobrindo EXATAMENTE {topicos_max} TÓPICOS — recortes diferentes
do mesmo fato (quem faz, quem paga, quem ganha, quem perde, o que vem depois) —
e entrega valor prático para o espectador principal: o adulto que quer entender
para onde o mundo está indo e o que isso muda na vida dele.

CRITÉRIOS, nesta ordem:
1. VALOR DA INFORMAÇÃO: prefira a candidata que entrega o que ainda não é
   conhecimento comum — vazamento, documento, número inédito, exclusivo ou
   prazo apertando (os campos VALOR INFORMATIVO e URGÊNCIA de cada candidata).
   Candidata marcada como "apenas repercussão, sem fato novo" só vence se todas
   as outras também forem.
2. RENDE {topicos_max} TÓPICOS: o acontecimento tem causa, mecanismo e
   consequência claros e dá pano para {topicos_max} recortes
   diferentes com dado próprio (empresa, dinheiro, trabalho, mercado,
   regulação, concorrente, precedente). Fato isolado e sem desdobramento (uma
   treta de rede social, um vídeo curioso) NÃO vira vídeo longo, por mais
   quente que esteja: ele rende um tópico e depois só repetição.
3. PAYLOAD DE ANÁLISE: dá para dizer, com fato e não com achismo, o que este
   acontecimento MUDA — quem ganha, quem perde, que precedente abre, o que
   deixa de ser possível. O ângulo de trabalho e carreira (setor que contrata
   ou corta, habilidade que passa a valer, prazo) é um dos recortes válidos,
   nunca uma cota, e NÃO é leitura de bolso do espectador — preço, salário,
   imposto e tarifa saíram do canal em 2026-08-25. Prefira acontecimentos com
   números de dinheiro, investimento, vagas, contratos ou regulação.
4. AUDIÊNCIA: entre as candidatas que passam nos anteriores, escolha a que mais se
   parece com o que o público DESTE canal assiste, segundo os números
   listados. A métrica que manda é o GANCHO — a porcentagem de quem abriu e
   FICOU em vez de deslizar: os vídeos marcados como ALTO ENGAJAMENTO seguraram
   {piso}% ou mais de quem abriu e são o molde; os abaixo disso são
   contraexemplo, por mais views que tenham. Repetir o tipo de assunto que
   performa é bem-vindo.
5. MATERIAL EM VÍDEO: o vídeo é montado SOMENTE com os clipes anexados aos
   posts do X da trend (até {max_clipes} clipes, nenhuma foto estática). Em
   empate, vence a candidata com MAIS posts com clipe.

Não escolha uma candidata que renderia uma análise IDÊNTICA a um vídeo longo
já publicado, sem nenhum fato novo.

Gere também uma consulta CURTA do assunto (em inglês, 3 a 6 palavras: nomes
próprios principais + o acontecimento) para a trend escolhida. Ela é o que a
busca aberta de clipes usa no formato longo. Consulta longa e cheia de detalhes
zera os resultados — seja enxuto.

E uma consulta de busca do YOUTUBE, no IDIOMA DO CANAL, com 2 a 5 palavras, do
jeito que um espectador digitaria na barra de busca. Ela serve para descobrir
que outros vídeos sobre este fato já saíram hoje — então use o nome PÚBLICO do
assunto, não o jargão do comunicado.
Responda somente com o JSON pedido.\
"""

# Regras de SEO e GEO (2026-08-07), iguais nos dois formatos. Ficam num
# constante próprio porque valem para os campos de METADADOS (tags, resposta
# curta, título e descrição diante da concorrência), que não mudam de um
# formato para o outro — o que muda é o vídeo, não a forma de ser encontrado.
#
# Este texto é concatenado DENTRO das instruções e passa pelo .format() delas:
# não escreva chave literal aqui.
INSTRUCOES_SEO_GEO = """\

SEO E GEO — o vídeo precisa ser ACHADO, por gente e por máquina. Dois campos
existem só para isso, e nenhum deles pode prometer o que o vídeo não entrega.

TAGS (campo tags) — de 8 a 15 termos de BUSCA, no idioma do canal, do mais
específico para o mais geral, sem '#'. Elas NÃO são lidas pelo espectador:
aqui não vale o teste do leigo do título, e é justamente onde entram os nomes
próprios que o título teve de traduzir (o modelo de IA, o laboratório, a
sigla, o produto, o ticker) — é por eles que procura quem já conhece o
assunto. Monte nesta ordem:
1. o nome exato do fato e das entidades envolvidas (empresa, produto, pessoa,
   o número que virou manchete);
2. os termos do VOCABULÁRIO DE TAGS do bloco de concorrência de hoje, quando
   descreverem de verdade ESTE vídeo — são as palavras com que o público está
   nomeando o assunto agora;
3. dois ou três termos amplos do nicho do canal.
PROIBIDO: tag sem relação com o conteúdo (tag enganosa derruba o alcance do
canal inteiro), nome de canal concorrente e o mesmo termo repetido com outra
caixa.

RESPOSTA CURTA (campo resposta_curta) — uma frase que responde o campo
`pergunta` e se sustenta SOZINHA, fora do vídeo. O par pergunta/resposta NÃO é
falado em nenhum dos dois formatos: ele existe só para a descrição, e é o
trecho que um buscador com IA extrai para responder quem perguntou aquilo.
Por isso ela NOMEIA o que a pergunta deixou subentendido em vez de usar
pronome: quem fez, o que fez, o número, a data e a fonte, tudo dentro da frase.
Teste: lida fora do vídeo, por quem não viu nada, ela ainda informa? Se
começar com 'isso', 'ele' ou 'a empresa', não passou.

TÍTULO E DESCRIÇÃO DIANTE DA CONCORRÊNCIA DE HOJE — quando o material trouxer
o bloco de vídeos já publicados sobre este assunto, ele é a lista do que vai
aparecer LADO A LADO com o nosso na busca. Leia-o para duas coisas:
(1) usar as PALAVRAS com que o público procura este fato — busca casa por
palavra, e chamar o fato por um nome que ninguém digita é sumir dele; e
(2) não repetir o ângulo que todos já ocuparam — se cinco títulos dizem a
mesma coisa, o nosso diz o que os cinco deixaram de fora (o número exato, quem
paga a conta, o efeito no emprego). Copiar título, frase ou nome de canal de
qualquer um deles é PROIBIDO.\
"""

INSTRUCOES_ROTEIRO = """\
Você é roteirista de vídeos curtos (YouTube Shorts) de ANÁLISE, sem recorte
temático: o assunto do vídeo é o que estiver acontecendo, seja ele qual for.
{foco}

Você recebe a TREND escolhida (com a IMAGEM MENTAL que ela evoca) e os POSTS DO
X que originaram a trend. Fatos, nomes, empresas, datas e números saem DAÍ —
não invente nada, e não use fato que não esteja no material recebido.

ENQUADRAMENTO — SEMPRE análise ou educacional, em formato EXPLICATIVO: o vídeo
explica o que aconteceu, como funciona e por que importa — nunca é um grito de
manchete sem explicação, nunca é opinião militante. O espectador tem que sair
do vídeo SABENDO alguma coisa que não sabia: um mecanismo, um número, uma
relação de causa e efeito. A estrutura em cinco blocos abaixo é justamente o
formato explicativo em ordem de aula bem dada — preview, contexto,
acontecimento, consequência, fecho. Explicar NÃO é palestrar: o tom
continua de jornalista afiado, não de professor.

FONTES — OBRIGATÓRIO citar a fonte na narração: todo fato central do vídeo é
atribuído a quem o publicou — a conta do X que trouxe o fato ("no post de
@unusual_whales", "Elon Musk postou") ou o veículo que a própria conta cita
("segundo a Reuters"). Cite SOMENTE fontes que estão na lista de posts
recebida; cite pelo menos uma, no ponto onde o fato dela entra, embutida na
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

ESTRUTURA OBRIGATÓRIA — CINCO BLOCOS (narração de ~{duracao}s):
1. PREVIEW (0-2s): abra DIZENDO o que este vídeo vai entregar. Uma frase que
   nomeia o assunto e o que está em jogo nele, em coisa concreta — gente,
   dinheiro, ação.
   "A empresa mais valiosa do mundo perdeu uma fábrica inteira numa noite."
   "Um robô de contratação saiu do ar e travou meio milhão de currículos."
   "Desligar um data center por um dia agora tem preço, e ele veio numa fatura."
   O gancho é a PROMESSA, não o estranhamento: metade do público desliza no
   primeiro segundo, e quem fica só fica porque já sabe o que ganha ficando.
   Por isso o preview PROMETE e NÃO ENTREGA: o número exato, a data e a fonte
   são do bloco 3, e antecipá-los aqui tira o motivo de assistir ao resto.
   REGRAS DURAS: máximo 14 palavras; sempre uma coisa concreta dentro (gente,
   dinheiro, ação, número redondo), nunca promessa abstrata ("o mercado nunca
   mais vai ser o mesmo"); PROIBIDO pergunta de qualquer tipo, preâmbulo de
   youtuber ("neste vídeo você vai ver", "vamos falar sobre", "fica até o
   final"), cauda de suspense ("e o que veio depois muda tudo") e abrir por
   data, contexto ou nome de instituição. O que o preview promete precisa
   estar REALMENTE no material recebido — promessa sem lastro é clickbait.
2. CONTEXTUALIZAÇÃO (2 a 3 frases): o mínimo que o leigo precisa para o
   preview fazer sentido — o que é essa empresa, esse mercado, esse número.
   Se o assunto CENTRAL não é universalmente conhecido (empresa, modelo de IA,
   app, pessoa de nicho), é AQUI que ele é amarrado em algo que o espectador já
   conhece: "a empresa por trás do ChatGPT", "a dona do Instagram". Meia frase
   embutida na narrativa, NUNCA tom de aula ou de glossário. Assunto que todo
   mundo conhece (Google, iPhone, Nubank) leva contexto curtíssimo — contexto
   desnecessário é preâmbulo, e preâmbulo derruba retenção.
3. ACONTECIMENTO (o miolo, o bloco mais longo): o que aconteceu de fato, em
   ordem "coisa concreta primeiro, detalhe depois", com número, nome e o
   MECANISMO (como funciona, por que isso produz aquilo). É aqui que a fonte é
   citada nominalmente. Cada frase mostra uma cena que dá para VER de olhos
   fechados.
4. CONSEQUÊNCIA: UMA única consequência concreta ("isso significa que...") —
   o que muda para quem trabalha, investe ou usa aquilo. Só uma: duas
   consequências confundem e a pessoa desliza.
5. CONCLUSÃO (últimos 2-3s): a ENTREGA do que o preview prometeu, fechada em
   uma frase seca. Sem moral da história, sem CTA falado, sem frase de
   encerramento.
   O Shorts REINICIA sozinho: a conclusão tem que desembocar naturalmente no
   preview quando o vídeo recomeça — quem fecha e emenda de volta na promessa
   da abertura faz a pessoa assistir de novo sem perceber, e replay multiplica
   a distribuição. FECHAR NÃO É REPETIR: é PROIBIDO copiar o preview (ou
   qualquer frase já dita) no final do texto.
   O LOOP VEM PRIMEIRO, mas dentro dele a conclusão tem um segundo trabalho:
   carregar A DISPUTA do assunto. Feche com o fato do vídeo sobre o qual
   duas pessoas razoáveis brigariam — quem está certo, quem paga a conta, se
   valeu a pena, quem saiu ganhando. É isso que faz a pessoa comentar e mandar
   o vídeo para alguém: ela termina com uma opinião formada e um interlocutor
   em mente. Exemplos do que é e do que não é:
   - suspense (fraco, ninguém comenta): "E a próxima empresa pode ser a maior
     de todas."
   - disputa (forte): "A conta foi de 2 bilhões, e quem pagou foram os 8 mil
     demitidos."
   O teste: se a frase não dá para discordar dela ou de quem ela responsabiliza,
   ela é só suspense — reescreva.
   PROIBIDO, e isto é regra dura: pergunta dirigida ao espectador ("você
   concorda?", "o que você faria?"), opinião do canal, e qualquer pedido de
   comentário, like ou compartilhamento. A disputa nasce do FATO estar na mesa,
   nunca de convite. Pedido explícito quebra o loop e derruba a retenção, que é
   a métrica que sustenta tudo.

PROIBIDO NO TEXTO:
- Frases de analista vazias: "no cenário atual", "especialistas afirmam", "o
  mercado reagiu" e afins — e "segundo fontes" SEM nomear a fonte (a citação
  obrigatória é sempre nominal: veículo ou conta do X).
- Número com mais de 2 dígitos significativos: escreva "2 bilhões", "150 mil",
  "quase 30%" — nunca "2,37 bilhões", "148.532" ou "29,7%".
- Mais de 1 nome próprio DESCONHECIDO por vídeo. Nomes que todo mundo conhece
  (Google, Apple, Elon Musk) não contam, nem veículo/conta citado como fonte;
  o segundo nome obscuro vira "um chefe da empresa", "um fundo americano", "o
  dono do site".

PAYLOAD OBRIGATÓRIO: o roteiro entrega o que o preview prometeu com 1 fato real
e 1 consequência. Clickbait sem payload é PROIBIDO — o título promete
exatamente o que o vídeo entrega, e o preview promete um fato que precisa
realmente vir.

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
central (com número/nome concreto e a fonte nominal) e a consequência, seguidas
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
ACONTECIMENTO — nunca o preview, a consequência única nem a conclusão. Se
sobrar espaço, acrescente um detalhe concreto ao ACONTECIMENTO (número, nome,
mecanismo) — nunca encha linguiça.

MATERIAL VISUAL — o corpo do vídeo é montado SOMENTE com os clipes de vídeo
anexados aos posts do X da trend (nada de foto estática ocupando a tela). Você
não escolhe os clipes — um editor de cortes casa cada um com a narração depois
— mas escreva o texto SABENDO disso: descreva cenas que os posts da trend
documentam em vídeo, e lembre que o primeiro clipe + o preview de abertura
decidem o "viewed vs swiped".
A TELA NÃO EXPLICA NADA POR VOCÊ. O vídeo é clipe do X, e mais nada — não
existe gráfico, tabela nem cartaz sobreposto (as figuras geradas saíram em
2026-08-24). Então todo dado tem que estar DITO: sempre que houver um número,
uma comparação (antes/depois, empresa A vs empresa B) ou uma lista curta no
material recebido, ESCREVA-A explicitamente na narração, com o valor e a
unidade — falado é o único jeito de o espectador receber. Pelo mesmo motivo, a
narração precisa se sustentar de olhos fechados: NUNCA escreva "como você vê no
gráfico", "veja a tabela" nem qualquer referência ao que está na tela.

NARRAÇÃO EXPRESSIVA — insira audio tags do ElevenLabs v3 no texto_video:
palavras em inglês entre colchetes, imediatamente antes do trecho que modificam.
Exemplos: [excited], [curious], [whispers], [surprised], [sighs], [laughs],
[short pause]. Use de 8 a 12 tags, variando a emoção conforme o conteúdo (elas
não são faladas nem aparecem nas legendas). A pontuação também guia a entrega:
reticências para suspense, MAIÚSCULAS para ênfase pontual.\
""" + INSTRUCOES_SEO_GEO + """

Responda somente com o JSON pedido.\
"""


INSTRUCOES_ROTEIRO_LONGO = """\
Você é roteirista de vídeos de ANÁLISE (formato longo, 16:9, {duracao}
segundos) que explicam os grandes acontecimentos contemporâneos cobrindo
EXATAMENTE {topicos_max} TÓPICOS. O canal NÃO tem recorte temático:
qualquer assunto pode virar vídeo, e o que decide o valor do vídeo é a
explicação, não o tema.
{foco}

Você recebe a TREND escolhida (com a IMAGEM MENTAL que ela evoca) e os POSTS DO
X que originaram a trend. Fatos, nomes, empresas, datas e números saem DAÍ —
não invente nada. Fato que não está no material recebido não entra no vídeo.

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

SEM LEGENDAS: a narração precisa se sustentar sozinha. O vídeo TEM manchetes
na tela (o título de cada tópico entra no canto inferior quando a pauta vira, e
um índice na abertura lista o que vem), mas elas só REPETEM o que você já
escreveu — quem ouve sem olhar não pode perder nada. PROIBIDO "como você vê
aqui", "na imagem", "no gráfico", "essa manchete", ou qualquer frase que dependa
de algo escrito na tela.

FONTES — OBRIGATÓRIO citar nominalmente: cada afirmação central é atribuída a
quem a publicou — a conta do X ("no post de @unusual_whales") ou o veículo que
ela cita ("segundo a Reuters"). Cite SOMENTE fontes da lista de posts recebida,
pelo menos DUAS ao longo do vídeo, embutidas na frase — nunca em bloco de
créditos. "Segundo fontes", sem nome, continua proibido. Nome de
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

ESTRUTURA OBRIGATÓRIA — a PAUTA FALADA e depois UMA PAUTA DE CADA VEZ:

1. PAUTA FALADA (0-6s, a primeira coisa do vídeo): diga em voz alta o que o
   vídeo vai tratar — o campo `pauta_falada`, copiado palavra por palavra como
   INÍCIO de texto_video. No máximo 18 palavras, nomeando os tópicos na mesma
   ordem em que eles virão, cada um pela coisa concreta: "drones a 1.900
   quilômetros, um navio sem tripulação que atirou, e o gás que o Irã achou".
   PROIBIDO preâmbulo de youtuber ("neste vídeo você vai ver", "vamos falar
   sobre", "fica até o final") — comece pela coisa. Enquanto você fala isso, os
   títulos dos tópicos aparecem na tela, um a um; por isso a ordem tem que
   bater com a de `topicos`.
2. CONTEXTUALIZAÇÃO GERAL (UMA frase): a frase que amarra os três — o que eles
   têm a ver entre si e por que valem juntos hoje. É a sua TESE dita em voz
   alta. Ela FECHA a abertura: a pauta falada mais esta frase são a primeira
   das quatro partes do vídeo, e juntas não passam de {abertura_palavras}
   palavras faladas (~{abertura_s:.0f} segundos de fala) — o pipeline MEDE isso
   e devolve o roteiro para reescrita se estourar. A frase seguinte já é o
   tópico 1, e é ela que você copia na `citacao` dele.
3. AS PAUTAS (o corpo do vídeo): cubra EXATAMENTE {topicos_max} TÓPICOS, os
   mesmos que você listou no campo `topicos` e na mesma ordem. Três, nem mais
   nem menos: o vídeo é montado em QUATRO PARTES separadas (esta abertura mais
   uma parte por pauta), cada pauta com o seu próprio clipe e a sua própria
   manchete na tela, e um número diferente de três não tem onde caber.
   QUANDO O MATERIAL TRAZ MAIS DE UM ACONTECIMENTO (a seleção manda três, e
   eles vêm numerados no resumo): cada acontecimento é UM TÓPICO, na ordem em
   que aparecem. Não force conexão factual entre eles — eles não são o mesmo
   fato —, mas encontre a LINHA que faz os três valerem juntos no mesmo vídeo:
   o que eles dizem, somados, sobre a semana de quem assiste. É essa linha que
   vira a sua TESE, e é ela que a abertura promete e a conclusão fecha.
   QUANDO O MATERIAL TRAZ UM ACONTECIMENTO SÓ: tópico é um recorte DIFERENTE
   dele, com dado próprio — não é o anterior repetido com outras palavras. Os
   recortes saem do PRÓPRIO fato: quem fez e por quê, quem paga a conta, quem
   ganha e quem perde, o que a regra ou a lei diz, o precedente histórico, o
   concorrente, o efeito no dinheiro, no trabalho ou no dia a dia de quem
   assiste, e o que vem depois.
   Nenhum deles é cota: cubra os que o material realmente sustenta, com dado,
   em vez de inventar um ângulo que não existe.

   CADA PAUTA TEM TRÊS BATIDAS, NESTA ORDEM, e nenhuma delas pode faltar:
   (a) CONTEXTUALIZAÇÃO — uma ou duas frases com o que o leigo precisa saber
       para o fato fazer sentido: quem são os envolvidos, o que existia antes,
       por que isso não era assim. Sem contexto o fato vira ruído.
   (b) ACONTECIMENTO FACTUAL — o que aconteceu, em ordem "coisa concreta
       primeiro, detalhe depois": número real, quem fez, quando, e a FONTE
       nominal. É o dado do campo `dado` deste tópico.
   (c) ANÁLISE — o campo `analise`: o que esse fato MUDA. Quem ganha e quem
       perde com ele, o que deixa de ser possível, que precedente ele abre, o
       que passa a valer daqui pra frente. É a batida mais importante das
       três: sem ela a pauta é notícia, não análise. PROIBIDO conselho de coach
       ("se reinvente", "esteja preparado", "invista em você"), futurologia sem
       base no material recebido e — regra dura deste canal — QUALQUER leitura
       de economia micro: nada de preço que sobe, salário, imposto, tarifa,
       conta de luz, "o seu bolso" ou "o seu dinheiro". A análise é do FATO,
       não da carteira de quem assiste.
   As três são ENCADEADAS por causa e efeito ("por isso", "o efeito disso", "o
   que muda a partir daqui") — nunca uma lista de bullets falados —, e todas as
   pautas são costuradas pela sua TESE.

   VIRADA DE PAUTA — OBRIGATÓRIA: cada tópico a partir do SEGUNDO abre com uma
   frase curta de VIRADA (no máximo 12 palavras) que FECHA o assunto anterior e
   NOMEIA o próximo, com o nome próprio ou o número que o identifica ("o
   dinheiro explica a pressa; a lei explica o resto", "quem paga essa conta é o
   consumidor americano"). Essa frase é o CORTE do vídeo, no sentido
   literal: o pipeline PARTE o vídeo exatamente ali, abre uma PAUSA de
   silêncio antes dela, troca a manchete na tela e troca o clipe. Por isso ela
   precisa ser autossuficiente — quem voltar a prestar atenção ali tem que
   saber do que se trata. Ela vira a `citacao` do tópico, copiada
   LITERALMENTE do texto. PROIBIDO virar de assunto no meio de um parágrafo, sem aviso — e
   PROIBIDO numerar em voz alta ("segundo ponto", "tópico três"): a virada é
   editorial, não é sumário falado.
4. FECHO (últimos ~12s): a SÍNTESE do campo `sintese` — a linha que une as
   análises das três pautas numa só, dita em uma ou duas frases secas —,
   mais uma frase apontando o PRÓXIMO MARCO concreto a acompanhar (decisão,
   balanço, data, número que sai em breve). NÃO repita a análise de uma pauta:
   o fecho costura, não recapitula. Sem CTA, sem pedido de inscrição, sem
   despedida, sem moral da história. Este formato NÃO roda em loop: ele fecha
   de verdade.

RETENÇÃO: a batida (c) de cada pauta é o próprio gancho — é ela que responde
"e daí?" antes de o espectador perguntar. O vídeo não roda em loop: ele
fecha, mas fecha entregando, nunca com suspense vazio.

PROIBIDO NO TEXTO:
- Frases de analista vazias: "no cenário atual", "especialistas afirmam", "o
  mercado reagiu", "só o tempo dirá".
- Número com mais de 2 dígitos significativos: "2 bilhões", "150 mil", "quase
  30%" — nunca "2,37 bilhões", "148.532" ou "29,7%".
- Opinião militante, torcida política e previsão inventada. Cenário só entra
  se estiver no material recebido e for apresentado como cenário.

PAYLOAD OBRIGATÓRIO: o roteiro entrega o fato, os {topicos_max} tópicos e,
DENTRO DE CADA UM, a análise do que aquilo muda — tudo ancorado no material
recebido.

TÍTULO — medido nos números do canal: título autossuficiente rende o dobro de
views do título com nome de nicho. Regras: (1) ator + ação concreta, com uma
coisa palpável (número, pessoa, dinheiro, lugar) e, quando couber com
naturalidade, o ângulo de trabalho/carreira; (2) TESTE DO LEIGO: entendível
por quem nunca ouviu falar da empresa/modelo — nome de nicho vira o efeito
concreto; (3) PROIBIDO cauda de suspense ("— e o detalhe muda tudo", "here's
why it matters", "e agora?").

DESCRIÇÃO — resumo do payload, não teaser: 2 a 4 frases que entregam o fato
central (com número/nome concreto e a fonte nominal), a leitura que une os
tópicos e o que o conjunto muda na prática, seguidas
das hashtags. Mesmo teste do leigo do título. PROIBIDO CTA, cauda de suspense e
frase de analista vazia.

DURAÇÃO — a narração deve PREENCHER {duracao} segundos: escreva entre
{palavras_min} e {palavras} palavras faladas no texto_video (audio tags entre
colchetes não contam). Os DOIS limites são DUROS — o formato do canal é de
{minimo_s} a {maximo_s} segundos, e vídeo abaixo de {minimo_s} segundos é
DESCARTADO pelo pipeline, não publicado. Texto curto demais é o erro mais caro
aqui: prefira errar para cima. Se faltar espaço, corte detalhe secundário do
a contextualização geral ou encurte a batida (a) de um tópico — nunca a pauta
falada, nunca a batida (c) de nenhuma pauta (a análise), nunca o fecho, e nunca
menos nem mais que {topicos_max} tópicos. Se sobrar espaço, acrescente dado
concreto do material recebido (número, nome, cena) às pautas que você já tem —
NÃO acrescente um quarto tópico, e nunca encha linguiça.

MATERIAL VISUAL — o corpo do vídeo é montado SOMENTE com os clipes de vídeo
anexados aos posts do X da trend (até {max_clipes} clipes, nada de foto
estática ocupando a tela). Você não escolhe os clipes — um editor de cortes casa
cada um com a narração depois — mas escreva sabendo disso: fale de cenas que os
posts documentam em vídeo, e lembre que o primeiro clipe + a pergunta de
abertura decidem quem fica.
A TELA NÃO EXPLICA NADA POR VOCÊ: o vídeo é clipe do X, sem gráfico, tabela ou
cartaz sobreposto (as figuras geradas saíram em 2026-08-24). Diga os números por
extenso na narração (valor e unidade), e sempre que houver comparação
(antes/depois, empresa A vs empresa B) ou uma sequência curta de itens,
ESCREVA-A — dado que você não falar o espectador não recebe. A regra "sem
referência ao que está na tela" continua valendo: nunca "como você vê no
gráfico".

NARRAÇÃO EXPRESSIVA — insira audio tags do ElevenLabs v3 no texto_video:
palavras em inglês entre colchetes, imediatamente antes do trecho que
modificam. Exemplos: [serious], [curious], [emphatic], [short pause],
[thoughtful], [surprised]. Use de 15 a 25 tags ao longo do texto, variando
conforme o conteúdo (elas não são faladas). A pontuação também guia a entrega:
reticências para suspense, MAIÚSCULAS para ênfase pontual.

CAPÍTULOS E MANCHETES — cada tópico traz uma CITAÇÃO literal do trecho de
texto_video em que ele começa (campo citacao): é a FRASE DE VIRADA daquele
tópico. O pipeline procura esse trecho no texto, converte em carimbo de tempo
pelo alinhamento da narração e usa isso duas vezes — publica os capítulos na
descrição (o que ativa os "momentos principais" do YouTube) e faz a MANCHETE
daquele tópico entrar na tela naquele segundo. Copie o trecho caractere por
caractere, do PRIMEIRO ponto em que o tópico entra, e nunca de dentro de uma
audio tag. Trecho que não existir no texto não vira capítulo NEM manchete — e
dois tópicos que começam quase no mesmo instante fazem o YouTube descartar o
bloco inteiro, então espalhe os tópicos pela narração.

TÍTULO DO TÓPICO (campo `titulo` de cada tópico) — ele vai APARECER ESCRITO na
tela, em caixa alta, como a manchete daquele trecho, e também no índice da
abertura. Escreva pensando nisso: até 6 palavras, sem ponto final, dizendo a
COISA (o fato, o número, quem paga) e não a categoria ("impactos", "contexto",
"análise" são títulos mortos). Ele precisa fazer sentido para quem só bateu o
olho na tela, sem ter ouvido a frase anterior.\
""" + INSTRUCOES_SEO_GEO + """

Responda somente com o JSON pedido.\
"""


def _linha_triagem(trend: dict) -> str:
    """Como o material da candidata se saiu na triagem, para o prompt.

    Existe porque a seleção decidia sem saber o que os clipes MOSTRAM: escolhia
    pela audiência e só depois do roteiro a auditoria descobria que o único
    clipe era busto falante, jogando fora a tentativa inteira. Agora o veredito
    chega antes (ver triagem.py) e a escolha pode preferir quem tem imagem que
    sobrevive ao veto. Candidata sem veredito não ganha linha nenhuma — o
    silêncio é honesto: não foi conferida.
    """
    aprovado = trend.get("clipe_aprovado")
    if aprovado is None:
        return ""
    if aprovado:
        return "   MATERIAL CONFERIDO: o clipe desta candidata PASSA no veto.\n"
    return (
        "   MATERIAL CONFERIDO: o clipe desta candidata É REPROVADO pelo veto "
        f"({trend.get('clipe_motivo') or 'sem motivo'}). Escolhê-la "
        "provavelmente termina a execução sem vídeo.\n"
    )


def _linha_material(trend: dict) -> str:
    """Quantos segundos de clipe a candidata tem, para o prompt de seleção.

    Só faz sentido no Short, e só desde 2026-08-28: com o loop fora da
    montagem, o material deixou de ser um detalhe de produção e virou o TETO do
    vídeo — uma pauta com 22 segundos de clipe rende um Short de 22 segundos,
    não o de 25 que o canal pede. A seleção precisa enxergar isso para preferir,
    entre duas candidatas parecidas, a que tem imagem para o formato inteiro.
    """
    segundos = trend.get("segundos_video")
    if not segundos:
        return ""
    return (
        f"   Material de vídeo: ~{float(segundos):.0f}s de clipe (é o TETO do "
        "tempo de tela desta pauta — o vídeo não repete clipe)\n"
    )


def _resumo_trends(trends: list[dict]) -> str:
    linhas = []
    for i, t in enumerate(trends, 1):
        linhas.append(
            f"{i}. {t['trend']}\n"
            f"   Resumo: {t['resumo']}\n"
            f"   Macrotema: {t.get('macrotema', '?')}\n"
            f"   Posts coletados sobre o assunto: {t.get('num_posts', '?')}\n"
            f"   Posts com clipe de vídeo nativo: {t.get('posts_com_video', '?')}\n"
            + _linha_material(t)
            + _linha_triagem(t)
            + f"   VALOR INFORMATIVO: {t.get('valor_informativo', '?')}\n"
            f"   URGÊNCIA: {t.get('urgencia', '?')}\n"
            f"   Imagem mental: {t.get('imagem_mental', '?')}\n"
            f"   Engajamento: {t.get('engajamento', '?')}\n"
            f"   Sentimento: {t.get('sentimento', '?')}\n"
            f"   Apelo visual: {t.get('apelo_visual', '?')}"
        )
    return "\n".join(linhas)


def _idade_horas(video: dict) -> float | None:
    """Horas desde a publicação (data UTC da Data API); None se ilegível."""
    try:
        publicado = datetime.fromisoformat(video.get("data") or "").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None
    horas = (datetime.now(timezone.utc) - publicado).total_seconds() / 3600
    return max(horas, 0.5)  # piso: vídeo recém-publicado não divide por ~zero


def _resumo_recentes(
    videos_recentes: list[dict] | None, macrotemas: list[str] | None = None
) -> str:
    """Bloco da régua de audiência, com as views NORMALIZADAS PELA IDADE.

    Views brutas medem idade tanto quanto qualidade: um vídeo de 7 dias com
    42 mil views e um de 3 horas com 322 não são comparáveis, e a lista chega
    ao modelo ordenada do mais novo para o mais velho — ou seja, tudo que é
    recente parece fracasso e tudo que é antigo parece campeão. O efeito
    prático medido no canal é inércia de pauta: o pico de um ciclo de notícia
    (guerra EUA-Irã, 20-25/07) continua sendo o maior número da lista por dias
    depois do assunto esfriar, e o modelo segue escolhendo o tema morto.

    Pedir a conta ao modelo em linguagem natural ("compare vídeos de idade
    parecida", que era a redação anterior) é frágil em cima de 100 linhas.
    Aqui a conta é feita em código: views/h ao lado das views brutas e a idade
    explícita em horas. É aritmética pura — nenhuma chamada de API a mais.
    """
    if not videos_recentes:
        return ""
    linhas = []
    for i, v in enumerate(videos_recentes):
        macro = (
            f" [macrotema: {macrotemas[i]}]"
            if macrotemas and i < len(macrotemas)
            else ""
        )
        views = v.get("views")
        horas = _idade_horas(v)
        if isinstance(views, int) and horas:
            idade = f"há {horas:.0f}h" if horas < 72 else f"há {horas / 24:.0f}d"
            ritmo = f", {views / horas:.0f} views/h"
        else:
            idade, ritmo = "idade ?", ""
        metricas = (
            f" — {views if views is not None else '?'} views{ritmo}, "
            f"{v.get('likes', '?')} likes"
        )
        linhas.append(f"- ({idade}) {v.get('titulo', '')}{macro}{metricas}")
    return (
        "\n\nÚltimos vídeos publicados neste canal, do mais recente para o mais "
        "antigo. Cada um traz as views ACUMULADAS e o ritmo em VIEWS POR HORA "
        "desde a publicação. Compare sempre pelo VIEWS/H, nunca pelas views "
        "acumuladas: as acumuladas medem há quanto tempo o vídeo está no ar "
        "tanto quanto medem qualidade, e por isso o vídeo antigo de um assunto "
        "já morto sempre exibe o maior número da lista. Esta é a régua do que "
        "o público deste canal assiste e do que ele ignora:\n"
        + "\n".join(linhas)
    )


# Tetos de texto do dossiê, por campeão. A lista de campeões não tem teto de
# quantidade (2026-08-22), então o que segura o tamanho do prompt é o tamanho de
# CADA entrada. Um Short de 25s transcreve em ~70 palavras, bem abaixo do teto;
# quem estoura é a DESCRIÇÃO publicada, que leva hashtags e links no fim.
MAX_DESCRICAO_CAMPEAO = 300


def _cortar(texto: str, teto: int) -> str:
    """Texto em uma linha, truncado com reticências."""
    limpo = " ".join((texto or "").split())
    return limpo if len(limpo) <= teto else limpo[:teto].rstrip() + "…"


def _bloco_dossie(campeao: dict) -> list[str]:
    """Linhas indentadas com o dossiê de UM campeão; vazio quando não há.

    Só o Short monta dossiê (ver referencia.py), e mesmo lá ele falha aberto
    vídeo a vídeo — então a ausência de qualquer campo aqui é normal e o bloco
    simplesmente encolhe. Nada neste formato depende de todos os campeões terem
    sido lidos.

    A CAPA vem da leitura da thumbnail. A NARRAÇÃO vinha da legenda publicada
    e SAIU em 2026-08-24: `captions.list` + `captions.download` custavam 250
    unidades de cota por campeão e sozinhos estouravam o balde diário da Data
    API (ver referencia.py). A thumbnail não consome cota nenhuma.
    """
    linhas = []
    descricao = _cortar(campeao.get("descricao", ""), MAX_DESCRICAO_CAMPEAO)
    if descricao:
        linhas.append(f"    DESCRIÇÃO: {descricao}")
    visual = campeao.get("visual") or {}
    if visual:
        partes = [
            visual.get("cena", ""),
            visual.get("composicao", ""),
            f'texto na capa: "{visual["texto"]}"' if visual.get("texto") else "",
        ]
        corpo = "; ".join(_cortar(x, 200) for x in partes if x)
        if corpo:
            linhas.append(f"    CAPA: {corpo}")
    return linhas


def _resumo_campeoes(
    campeoes: list[dict] | None, formato: str = "curto"
) -> str:
    """Bloco dos campeões, com a RETENÇÃO marcada contra o piso.

    O rótulo ALTA RETENÇÃO / abaixo do piso é escrito em CÓDIGO, e não deixado
    para o modelo comparar de cabeça: a régua é um número
    (``RETENCAO_MINIMA``), e regra numérica embutida em prosa é exatamente o
    tipo de instrução que se perde no meio de cem linhas de contexto. Assim o
    prompt só precisa dizer "use os marcados como molde".
    """
    if not campeoes:
        return ""
    # O Short mede ENGAJAMENTO e o longo, RETENÇÃO. Quem manda no rótulo é o
    # critério que selecionou a lista, senão o prompt destaca um número que a
    # régua não usou — que foi exatamente o erro de 2026-08-16.
    por_engajamento = formato == "curto"
    linhas = []
    for c in campeoes:
        retencao = c.get("retencao_media", 0)
        gancho = c.get("retencao_gancho")
        if por_engajamento:
            partes = [f"segura {gancho}% de quem abre" if gancho is not None else ""]
            marca = " [ALTO ENGAJAMENTO]"
        else:
            partes = [f"assistem em média {retencao}% do vídeo"]
            if gancho is not None:
                partes.append(f"gancho segura {gancho}% de quem abre")
            marca = (
                " [ALTA RETENÇÃO]"
                if retencao > RETENCAO_MINIMA
                else f" [abaixo do piso de {RETENCAO_MINIMA}%]"
            )
        partes.append(f"{c.get('views', '?')} views")
        corpo = "; ".join(x for x in partes if x)
        linhas.append(f"- {c.get('titulo', '')}{marca} ({corpo})")
        linhas += _bloco_dossie(c)
    tem_dossie = any(c.get("visual") for c in campeoes)
    if por_engajamento:
        cabecalho = (
            "\n\nOs vídeos deste canal que MAIS SEGURAM quem abre, do maior "
            f"para o menor (todos acima de {ENGAJAMENTO_MINIMO}% de "
            "engajamento: a fração de quem continuou assistindo em vez de "
            "deslizar para o próximo). É com o ASSUNTO DESSES que a candidata "
            "escolhida precisa se parecer"
        )
    else:
        cabecalho = (
            "\n\nVídeos deste canal ordenados por RETENÇÃO (quanto do vídeo "
            "quem abriu assistiu). Os marcados como ALTA RETENÇÃO seguraram "
            f"mais de {RETENCAO_MINIMA}% de retenção (foram REASSISTIDOS) — é "
            "com o ASSUNTO DESSES que a candidata escolhida precisa se parecer"
        )
    if tem_dossie:
        cabecalho += (
            ". De cada um vem também a DESCRIÇÃO publicada, a NARRAÇÃO (a "
            "legenda do próprio vídeo) e a CAPA que ele usou: use isso para "
            "reconhecer o TIPO de acontecimento que este público fica "
            "assistindo — não para copiar frase, título ou imagem"
        )
    return cabecalho + ":\n" + "\n".join(linhas)


def _macrotemas_recentes(
    cliente: OpenAI, cfg: Config, videos_recentes: list[dict]
) -> list[str]:
    """Classifica o macrotema de cada vídeo recente do canal (1 chamada).

    A lista entra no prompt de seleção como contexto: rotular cada vídeo
    publicado é o que deixa o modelo ler a régua por TEMA e não vídeo a vídeo
    ("os 20 'guerra' fazem 15 mil views, os 'tech' fazem 200"). Com o teto de
    macrotemas seguidos removido (2026-07-28), esse rótulo é a principal coisa
    que sustenta a decisão de trocar de assunto.

    Falha aqui FALHA ABERTA (aviso no log, lista vazia): enquanto existia o
    teto, sem os macrotemas não existia a regra e abortar se justificava —
    agora eles são contexto de prompt, e perder a anotação piora a escolha sem
    corromper regra nenhuma. Derrubar a execução (que já pagou a leitura do
    canal e vai pagar X e OpenAI) por um erro transitório da OpenAI custaria
    mais do que o contexto vale.
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
    except Exception as erro:  # noqa: BLE001 — só contexto de prompt; segue
        print(
            "[aviso] Classificação de macrotema dos vídeos recentes falhou "
            f"({erro}) — a seleção segue sem o rótulo por tema, lendo as "
            "métricas vídeo a vídeo."
        )
        return []

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


def selecionar_trends_longo(
    cfg: Config,
    trends: list[dict],
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
    excluir: list[dict] | None = None,
    quantas: int = LONGO_NUM_TRENDS,
) -> dict:
    """Escolhe `quantas` trends e devolve UMA seleção que as combina.

    O formato longo cobria um acontecimento só, dividido em 3 a 5 recortes, e
    por isso exigia 4 posts com clipe na MESMA candidata — corte que nunca
    passava: em 2026-08-18, com 57 clipes coletados, as 10 candidatas ficaram de
    fora. Vídeo do X se espalha por assuntos; não se concentra num.

    A troca (ideia do usuário) é cobrir TRÊS acontecimentos, um por tópico. Cada
    trend precisa trazer só o próprio clipe, e o piso de 3 aprovados passa a ser
    somado entre elas. A seleção de cada uma reusa `selecionar_trend` inteira —
    régua de audiência e anti-repetição seguem valendo, e cada escolha entra na
    lista de exclusão da seguinte.

    O retorno tem a forma de uma seleção comum (o resto do pipeline não muda),
    com `trend_obj` juntando os posts das três e `selecoes` guardando as
    originais para o roteiro saber quais são os assuntos.
    """
    escolhidas: list[dict] = []
    fora = list(excluir or [])
    for _ in range(max(quantas, 1)):
        restantes = [t for t in trends if t not in fora]
        if not restantes:
            break
        try:
            sel = selecionar_trend(
                cfg, trends, videos_recentes=videos_recentes,
                campeoes=campeoes, excluir=fora,
            )
        except SystemExit:
            break  # acabaram as candidatas com material; segue com o que houver
        escolhidas.append(sel)
        fora.append(sel["trend_obj"])

    if not escolhidas:
        raise SystemExit(
            "Nenhuma trend com clipe para o formato longo — o vídeo é montado "
            "só com clipes do X."
        )

    posts: list[str] = []
    com_video = 0
    for sel in escolhidas:
        obj = sel["trend_obj"]
        posts += [u for u in (obj.get("posts") or []) if u not in posts]
        com_video += obj.get("posts_com_video") or 0

    print(
        f"[longo] {len(escolhidas)} assunto(s) escolhido(s) para o vídeo "
        f"({com_video} posts com clipe somados):"
    )
    for i, sel in enumerate(escolhidas, 1):
        print(f"[longo]   {i}. {sel['trend']}")

    principal = escolhidas[0]
    return {
        **principal,
        "trend": " | ".join(s["trend"] for s in escolhidas),
        "motivo": " / ".join(s.get("motivo", "") for s in escolhidas),
        "trend_obj": {
            **principal["trend_obj"],
            "trend": " | ".join(s["trend"] for s in escolhidas),
            "resumo": "\n\n".join(
                f"{i}. {s['trend']}: {s['trend_obj'].get('resumo', '')}"
                for i, s in enumerate(escolhidas, 1)
            ),
            "posts": posts,
            "posts_com_video": com_video,
        },
        "selecoes": escolhidas,
        "assuntos": [s["trend"] for s in escolhidas],
    }


def selecionar_trend(
    cfg: Config,
    trends: list[dict],
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
    excluir: list[dict] | None = None,
) -> dict:
    """Escolhe a trend guiada SOMENTE pelo que a audiência está assistindo.

    Diretriz de 2026-07-18: sem pesos nem filtros editoriais. O prompt entrega
    ao modelo os últimos vídeos publicados COM as métricas reais (views/likes)
    e a régua de engajamento (``youtube.top_retencao``), e o critério é um só
    — a maior chance de performar com a audiência DESTE canal.

    Regras duras, APLICADAS aqui e não só pedidas no prompt:
    0. Candidata sem nenhum post com clipe de vídeo nativo sai da disputa
       antes de tudo: o formato do canal é montado só com clipes do X. No
       formato longo o corte é mais alto (LONGO_MIN_POSTS_VIDEO, derivado do
       piso da auditoria): candidata que não tem material para o piso não
       disputa, porque escolhê-la só gastaria roteiro e narração para abortar
       na auditoria — e ainda tiraria a vaga de uma candidata bem servida.
    1. Vídeo repetido é vetado: a escolhida passa por uma verificação
       (``_video_repetido``) contra os vídeos publicados nas últimas
       JANELA_REPETICAO_HORAS; se ela cobriria o mesmo fato sem
       desenvolvimento novo, sai da disputa e a seleção refaz com as
       restantes.
    2. Só no formato CURTO, RODÍZIO DE TEMAS (2026-08-04): as candidatas do
       macrotema do(s) último(s) Short publicado(s) saem da disputa, para que
       cada Short saia de um tema diferente do anterior
       (``_temas_a_evitar``). Este veto CEDE se zerar as candidatas — ver o
       comentário no ponto de aplicação.
    Se a regra 1 zerar as candidatas do dia, aborta — melhor uma execução sem
    vídeo do que vídeo clonado.

    `excluir` são as trends que já foram tentadas e não deram vídeo (material
    que não baixou, auditoria abaixo do piso). Elas saem da disputa antes de
    tudo, para que a nova seleção não devolva a mesma candidata que acabou de
    falhar — ver o laço de fallback em main.py.

    NENHUM teto de macrotema seguido: o de 2026-07-28 foi removido e o rodízio
    dos Shorts que o substituiu saiu em 2026-08-29. A defesa contra ficar preso
    a um assunto morto
    continua sendo o sinal de audiência normalizado pela idade — o vídeo de 3
    horas atrás com 40 views/h ao lado do de 7 dias atrás com 253 views/h diz
    ao modelo que o ciclo acabou, e ele troca de tema por conta própria.
    """
    cliente = OpenAI(api_key=cfg.openai_api_key)
    longo = cfg.formato == "longo"
    macros_recentes = (
        _macrotemas_recentes(cliente, cfg, videos_recentes) if videos_recentes else []
    )

    # O veto a vídeo repetido do formato longo compara só com os vídeos LONGOS
    # do canal; o prompt continua recebendo a lista inteira, que é a régua de
    # audiência.
    if longo:
        recentes_regras = [
            v
            for v in (videos_recentes or [])
            if (v.get("duracao_s") or 0) >= DURACAO_MINIMA_LONGO
        ]
        print(
            f"[longo] {len(recentes_regras)} vídeo(s) longo(s) já publicados "
            "servem de base para o veto a repetição."
        )
    else:
        recentes_regras = list(videos_recentes or [])

    # Candidatas já tentadas nesta execução (o material não deu vídeo) saem
    # antes de qualquer outra regra: reescolher a mesma trend gastaria roteiro
    # e notícias para falhar no mesmo ponto.
    if excluir:
        tentadas = {id(t) for t in excluir}
        nomes = {(t.get("trend") or "").strip().lower() for t in excluir}
        trends = [
            t for t in trends
            if id(t) not in tentadas
            and (t.get("trend") or "").strip().lower() not in nomes
        ]
        if not trends:
            raise SystemExit(
                f"As {len(excluir)} candidata(s) tentadas hoje não renderam "
                "material aproveitável e não sobrou nenhuma para tentar — "
                "execução sem vídeo."
            )

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

    # No formato longo, candidata sem material para o piso da auditoria não
    # entra na disputa. O portão é DERIVADO do piso (LONGO_MIN_POSTS_VIDEO):
    # antes ele era um 2 solto contra um piso de 3, e o que acontecia era pior
    # do que parece — a candidata de 2 clipes não só falhava, ela TIRAVA A VAGA
    # de uma candidata mais bem servida, e só descobria isso depois de gastar
    # roteiro, notícias e visão. Sem ninguém no portão a execução aborta aqui,
    # barato: seguir com material insuficiente é gastar para falhar adiante.
    if longo:
        com_material = [
            t for t in candidatas
            if (t.get("posts_com_video") or 0) >= LONGO_MIN_POSTS_VIDEO
        ]
        if len(com_material) < len(candidatas):
            print(
                f"[longo] {len(candidatas) - len(com_material)} candidata(s) "
                f"com menos de {LONGO_MIN_POSTS_VIDEO} posts com clipe fora da "
                f"disputa (o formato precisa de material para o piso da "
                f"auditoria; {len(com_material)} seguem)."
            )
        if not com_material:
            raise SystemExit(
                "Nenhuma candidata de hoje tem os "
                f"{LONGO_MIN_POSTS_VIDEO} posts com clipe que o formato longo "
                "precisa para chegar ao piso da auditoria — o vídeo não teria "
                f"material para {LONGO_MIN_S}-{LONGO_MAX_S}s de tela; "
                "abortando antes de gastar "
                "roteiro e narração. Se isso virar rotina, a alavanca é a "
                "própria lista do X: contas que publiquem VÍDEO. X_MAX_POSTS "
                "já está no teto de 100 por chamada da API."
            )
        candidatas = com_material

    # PORTÃO DE METRAGEM DO SHORT: existiu por algumas horas em 2026-08-28 e
    # foi removido no mesmo dia, junto com o piso duro que lhe dava sentido.
    # Ele tirava da disputa a candidata com menos de ~24s de clipe; medido
    # contra 50 curtidas reais, isso descartava 73% delas — não por serem pauta
    # ruim, mas por terem clipe curto. Era o comprimento do vídeo escolhendo a
    # pauta. Agora o Short dura o que a pauta dá e nenhuma candidata é barrada
    # por tamanho de material.

    # Não há portão de QUANTIDADE no curto: a exigência de 2 posts com clipe,
    # testada em 2026-08-17, estreitou a disputa (7 de 8 candidatas fora numa
    # execução) sem resolver nada — o material que sobrava era do mesmo tipo que
    # a auditoria reprova. Contar clipe não adianta quando o problema é a FONTE
    # dele; quem trata isso é CONTAS_SEM_CLIPE (config.py), que tira o clipe de
    # quem só publica recorte de emissora antes de ele contar como material.

    # RODÍZIO DE TEMAS DOS SHORTS REMOVIDO em 2026-08-29 — ver a nota no lugar
    # de RODIZIO_SHORTS_TEMAS, no topo do módulo. Nenhuma candidata sai mais da
    # disputa por ser do mesmo macrotema do Short anterior; repetir tema é
    # decisão do modelo, guiada pelas views/h dos publicados.

    janela_repeticao = (
        JANELA_REPETICAO_HORAS_LONGO if longo else JANELA_REPETICAO_HORAS
    )
    recentes_janela = _recentes_na_janela(recentes_regras, janela_repeticao)
    instrucoes_selecao = (
        INSTRUCOES_SELECAO_LONGO.format(
            duracao=cfg.video_duracao,
            max_clipes=cfg.max_clipes,
            topicos_max=TOPICOS_MAX,
            piso=RETENCAO_MINIMA,
        )
        if longo
        else INSTRUCOES_SELECAO.format(piso=RETENCAO_MINIMA)
    )
    while True:
        conteudo = (
            AVISO_DADOS_EXTERNOS
            + "\n\nTrends mais faladas do X hoje:\n"
            + _resumo_trends(candidatas)
            + _resumo_campeoes(campeoes, cfg.formato)
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
        # Mesmo princípio de _resumo_campeoes: o número exibido é o que a régua
        # usou para escolher a lista. No Short é o engajamento; a retenção saiu
        # em 2026-08-22 e não deve mais aparecer aqui, ou o roteirista calibra
        # por uma métrica que ninguém está medindo.
        curto = formato == "curto"
        partes.append(
            "Vídeos que mais seguraram quem abriu (o público fica assistindo "
            "vídeos assim):"
            if curto
            else "Campeões de retenção (o público assiste até o fim vídeos assim):"
        )
        for c in campeoes:
            if curto:
                gancho = c.get("retencao_gancho")
                medida = (
                    f"segura {gancho}% de quem abre"
                    if gancho is not None
                    else "alto engajamento"
                )
            else:
                medida = f"assistem em média {c.get('retencao_media', '?')}% do vídeo"
            partes.append(f"- {c.get('titulo', '')} ({medida})")
            # O dossiê (só no Short) traz a NARRAÇÃO e a CAPA. Aqui ele vale
            # mais do que na seleção: este prompt é o que escreve o roteiro, e
            # é onde tipo de abertura, ritmo de fala e densidade de informação
            # por segundo podem de fato ser imitados.
            partes += _bloco_dossie(c)
        if any(c.get("visual") for c in campeoes):
            partes.append(
                "Nesses campeões, a CAPA é a imagem que o vídeo usou de "
                "thumbnail. Imite o TIPO DE PROMESSA que ela faz e a relação "
                "dela com o assunto; NUNCA reaproveite o título nem o assunto "
                "deles."
            )
    return "\n".join(partes)


def _faixa_palavras(cfg: Config) -> tuple[int, int]:
    """Piso e teto de palavras faladas do roteiro, conforme o formato.

    No formato longo a faixa sai da FAIXA DURA do próprio formato (120 a 150s),
    com as margens assimétricas de MARGEM_LONGO_MIN_S/MARGEM_LONGO_MAX_S para
    absorver a variação de ritmo do TTS sem furar o piso.

    No formato curto o teto vem da duração-alvo (VIDEO_DURACAO) e o piso é o
    MAIOR entre a fração da duração-alvo e o que o PISO DURO do Short exige:
    FRACAO_MINIMA sozinha autorizava um roteiro de 51 segundos com alvo de 60,
    e qualquer variação de ritmo para baixo derrubava isso abaixo dos 50s
    proibidos — o piso duro tem que entrar no orçamento de palavras, não só na
    conferência do fim.

    A VELOCIDADE entra como multiplicador: a narração acelerada do Short cabe
    proporcionalmente mais palavras no mesmo tempo de tela, e sem isso o vídeo
    sairia mais curto que a duração pedida — que foi exatamente o bug do piso
    de palavras em 2026-07-16, por outro caminho.

    Os SEGUNDOS aqui são sempre segundos do áudio FINAL, porque é isso que
    PALAVRAS_POR_SEGUNDO mede desde 2026-08-05 (depois da aceleração e do corte
    de silêncios). Não há nada a descontar por fora: o corte de silêncio já
    está dentro da constante.
    """
    ritmo = PALAVRAS_POR_SEGUNDO * (getattr(cfg, "velocidade", 1.0) or 1.0)
    if cfg.formato == "longo":
        return (
            int((LONGO_MIN_S + MARGEM_LONGO_MIN_S) * ritmo),
            int((LONGO_MAX_S - MARGEM_LONGO_MAX_S) * ritmo),
        )
    limite = int(cfg.video_duracao * ritmo)
    # O TERMO ABSOLUTO SAIU em 2026-08-28, com o piso duro do formato. Ele era
    # `(CURTO_MIN_S + margem) * ritmo`, e existia para o roteiro nunca sair
    # abaixo dos 21 segundos proibidos. Sem piso não há o que proteger: o alvo
    # já é o tamanho que a pauta comporta, e exigir um mínimo absoluto em cima
    # dele mandaria o roteirista escrever mais texto do que cabe em imagem —
    # exatamente o loop que esta mudança tirou.
    #
    # O que fica é o piso PROPORCIONAL (FRACAO_MINIMA): o roteiro não pode sair
    # muito abaixo do alvo DAQUELA pauta. Isso continua sendo defeito de
    # roteiro, e continua valendo.
    piso = int(limite * FRACAO_MINIMA)
    return piso, max(limite, piso)


def _aparar_hook_final(roteiro: dict) -> None:
    """Remove a abertura falada repetida literalmente no fim do texto.

    O loop emenda na abertura do REINÍCIO do vídeo; quando o modelo a copia no
    final da narração, ela fica duplicada e o trecho da última imagem passa a
    existir duas vezes no texto, desalinhando os cortes.

    A abertura FALADA é o `preview` no Short e a `pauta_falada` no longo. O
    campo `pergunta` deixou de ser narrado nos dois formatos (longo em
    2026-08-24, Short em 2026-08-25) — ele só alimenta o par P:/R: da
    descrição, e mirar nele aqui deixava a duplicação real passar.
    """
    hook = (roteiro.get("preview") or roteiro.get("pauta_falada") or "").strip()
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
            "[roteiro] Abertura repetida no fim do texto removida "
            "(o loop emenda no reinício, não dentro da narração)."
        )


# Quantas reescritas o roteiro longo ganha para entregar a ESTRUTURA que a
# montagem em quatro partes exige (três tópicos, citação literal em cada um).
# Duas: a primeira costuma ser um tópico a mais ou uma citação parafraseada, e
# o modelo corrige com o erro na mão; passar disso é jogar dinheiro em um
# roteiro que não vai fechar.
TENTATIVAS_ESTRUTURA_LONGA = 2


def _falhas_de_estrutura(roteiro: dict) -> list[str]:
    """O que impede o roteiro longo de virar as quatro partes da montagem.

    TRÊS conferências, e as três são DURAS porque a montagem depende delas
    (montagem_longa.py): o vídeo é partido em quatro (abertura + uma parte por
    pauta), e o ponto de corte de cada parte é o primeiro caractere da
    `citacao` do tópico, localizada por busca LITERAL no texto narrado.

      1. exatamente TOPICOS_MAX tópicos — dois tópicos dariam três partes, e
         quatro dariam cinco: não há montagem para nenhum dos dois casos;
      2. a `citacao` de cada tópico existe no `texto_video`, ignorando as audio
         tags entre colchetes (que a narração não fala e o alinhamento não
         traz) e em ordem CRESCENTE — citação que aparece antes da do tópico
         anterior faria a parte ter duração negativa;
      3. a `citacao` do PRIMEIRO tópico chega até ABERTURA_MAX_PALAVRAS
         palavras faladas do começo (2026-08-26).

    A terceira é nova e é a que faltava. A abertura não tem duração própria: ela
    é "tudo que vem antes da citação do tópico 1", então a citação do tópico 1
    NÃO é só o carimbo do capítulo dele — é o tamanho da abertura. Com as duas
    regras antigas, uma citação copiada do MEIO do bloco do tópico 1 passava
    limpa, e a abertura engolia a pauta: no canal US em 26/08 saiu um vídeo com
    45,4s de abertura e 10,2s de pauta 1, contra os ~10s e ~45s do desenho.
    Nada aqui reprovou aquilo, porque as duas regras antigas estavam satisfeitas.

    Esta conferência mede em PALAVRAS porque roda antes da narração existir; a
    medição em segundos, no áudio final, é `manchetes.planejar_partes`. As duas
    existem: esta reprova de graça e com reescrita, a de lá é a rede de baixo.

    Devolve a lista de problemas em linguagem de pedido, pronta para voltar ao
    modelo. Vazia = o roteiro monta.
    """
    problemas: list[str] = []
    topicos = roteiro.get("topicos") or []
    if len(topicos) != TOPICOS_MAX:
        problemas.append(
            f"o roteiro trouxe {len(topicos)} tópico(s) e o formato monta "
            f"EXATAMENTE {TOPICOS_MAX} (o vídeo é cortado em quatro partes: a "
            f"abertura e uma por tópico) — entregue {TOPICOS_MAX} tópicos"
        )

    texto = roteiro.get("texto_video") or ""
    cursor = 0
    for k, topico in enumerate(topicos, 1):
        citacao = " ".join((topico.get("citacao") or "").split())
        titulo = (topico.get("titulo") or f"tópico {k}").strip()
        if not citacao:
            problemas.append(
                f"o tópico {k} ('{titulo}') veio sem `citacao` — ela é o ponto "
                "em que o vídeo é cortado, sem ela a parte não existe"
            )
            continue
        pos = localizar_citacao(texto, citacao, cursor)
        if pos is None:
            problemas.append(
                f"a `citacao` do tópico {k} ('{titulo}') não existe "
                f'LITERALMENTE em texto_video: "{citacao}" — copie 5 a 12 '
                "palavras consecutivas do próprio texto narrado, caractere "
                "por caractere, sem parafrasear"
            )
            continue
        if pos < cursor:
            problemas.append(
                f"a `citacao` do tópico {k} ('{titulo}') aparece no texto "
                "ANTES da citação do tópico anterior; as citações têm que "
                "seguir a ordem dos tópicos na narração"
            )
            continue
        # A citação do PRIMEIRO tópico é a borda da ABERTURA: o que vier antes
        # dela é a primeira parte do vídeo, e o desenho dá ~10s a ela.
        if k == 1:
            abertura = _contar_palavras(texto[:pos])
            if abertura > ABERTURA_MAX_PALAVRAS:
                problemas.append(
                    f"a abertura ficou com {abertura} palavras faladas e o "
                    f"teto é {ABERTURA_MAX_PALAVRAS} (~{LONGO_ABERTURA_S:.0f} "
                    "segundos de fala): a abertura é TUDO que vem antes da "
                    f"`citacao` do tópico 1 ('{titulo}'), que hoje é "
                    f'"{citacao}". Ou a `citacao` do tópico 1 não são as '
                    "PRIMEIRAS palavras dele — copie a primeira frase do bloco "
                    "desse tópico, não uma do meio dele —, ou a pauta falada "
                    "mais a contextualização geral estão longas demais; corte "
                    "para caber e devolva o texto que sobrar para dentro das "
                    "pautas, mantendo o total de palavras do roteiro"
                )
        cursor = pos + 1
    return problemas


def _conferir_estrutura_longa(
    cliente: OpenAI,
    cfg: Config,
    roteiro: dict,
    instrucoes: str,
    conteudo: str,
) -> dict:
    """Devolve um roteiro longo que a montagem em quatro partes consegue cortar.

    Pede a reescrita enquanto houver falha, até TENTATIVAS_ESTRUTURA_LONGA, e
    ABORTA se ela sobreviver — de propósito, e antes do ElevenLabs. Este é o
    único defeito de roteiro que não tem degradação possível: sem os três
    pontos de corte não existe vídeo de quatro partes, e o que sairia é o bloco
    corrido de 135 segundos que o usuário rejeitou. Falhar aqui custa o texto
    já pago; falhar depois custaria narração, visão e montagem, e ainda
    publicaria o vídeo errado.
    """
    problemas = _falhas_de_estrutura(roteiro)
    for tentativa in range(1, TENTATIVAS_ESTRUTURA_LONGA + 1):
        if not problemas:
            return roteiro
        print(
            f"[roteiro] Estrutura das quatro partes reprovada "
            f"({tentativa}/{TENTATIVAS_ESTRUTURA_LONGA}):"
        )
        for problema in problemas:
            print(f"  - {problema}")
        pedido = (
            "O roteiro não pode ser montado. O vídeo é cortado em QUATRO "
            "PARTES — a abertura e uma parte por tópico —, e o ponto de corte "
            "de cada parte é a `citacao` do tópico, localizada por busca "
            "LITERAL dentro de texto_video. Repare no que isso significa para "
            "o tópico 1: a ABERTURA é tudo que vem ANTES da citação dele, "
            "então essa citação decide o tamanho dela (teto: "
            f"{ABERTURA_MAX_PALAVRAS} palavras faladas, ~"
            f"{LONGO_ABERTURA_S:.0f} segundos). Reescreva o JSON completo "
            "corrigindo TODOS os problemas abaixo, mantendo o assunto, o "
            "título, a descrição e o tamanho do texto:\nProblemas:\n- "
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
            response_format={"type": "json_schema", "json_schema": ESQUEMA_ROTEIRO_LONGO},
        )
        corrigido = json.loads(resposta.choices[0].message.content)
        _aparar_hook_final(corrigido)
        restantes = _falhas_de_estrutura(corrigido)
        # Só troca se a reescrita resolveu MAIS do que quebrou: uma versão que
        # conserta a citação e perde um tópico não é progresso.
        if len(restantes) < len(problemas):
            roteiro, problemas = corrigido, restantes
    if problemas:
        raise SystemExit(
            "O roteiro do formato longo não fecha a estrutura de quatro partes "
            f"depois de {TENTATIVAS_ESTRUTURA_LONGA} reescritas, e sem ela o "
            "vídeo sairia como o bloco corrido que o formato deixou de ser; "
            "abortando antes da narração.\nProblemas:\n- "
            + "\n- ".join(problemas)
            + "\nAlavanca: um TEXT_MODEL que copie a citação caractere por "
            "caractere."
        )
    return roteiro


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
    videos_recentes: list[dict] | None = None,
    campeoes: list[dict] | None = None,
    panorama: dict | None = None,
) -> dict:
    """Gera o roteiro completo da trend escolhida, a partir dos posts do X.

    A busca de NOTÍCIAS (Firecrawl) que enriquecia este material foi removida em
    2026-08-16: os fatos, nomes e números saem agora só do resumo da trend e dos
    posts que a originaram, e são essas contas as fontes citáveis na narração.

    `panorama` é o retrato do assunto no YouTube de hoje (``seo.py``): os
    vídeos que outros canais já publicaram sobre o mesmo fato nas últimas
    horas, com views/h e o vocabulário de tags deles. Entra no material do
    roteirista para calibrar título, descrição e tags contra a disputa REAL da
    busca — o resumo de estilo ao lado dele só enxerga o próprio canal. É
    opcional: sem ele, o roteiro sai como saía antes (com as tags montadas só a
    partir do fato).
    """
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
        + _resumo_estilo(videos_recentes, campeoes, cfg.formato)
        + resumo_para_prompt(panorama)
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
        formatacao["topicos_max"] = TOPICOS_MAX
        formatacao["minimo_s"] = LONGO_MIN_S
        formatacao["maximo_s"] = LONGO_MAX_S
        formatacao["abertura_palavras"] = ABERTURA_MAX_PALAVRAS
        formatacao["abertura_s"] = LONGO_ABERTURA_S
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
    # retenção; vídeo curto demais fura o piso duro do formato e a execução
    # aborta depois da narração já paga. Fora da faixa, até
    # TENTATIVAS_FAIXA_PALAVRAS novas tentativas pedindo ajuste — uma só não
    # segurava (ver o comentário da constante).
    palavras = _contar_palavras(roteiro["texto_video"])

    # Distância da faixa: 0 dentro dela, quantas palavras faltam/sobram fora.
    # Aceitar a reescrita "porque melhorou na direção pedida" deixava passar um
    # texto que despencava para o outro lado (de 120 palavras acima do teto
    # para 50, abaixo do piso), então a régua é a distância, não a direção.
    def _dist_faixa(n: int) -> int:
        return max(minimo - n, n - int(limite * folga), 0)

    for tentativa in range(1, TENTATIVAS_FAIXA_PALAVRAS + 1):
        if minimo <= palavras <= limite * folga:
            break
        estourou = palavras > limite * folga
        print(
            f"[roteiro] texto_video com {palavras} palavras faladas "
            f"(faixa {minimo}-{limite}); pedindo versão "
            f"{'mais curta' if estourou else 'mais completa'} "
            f"({tentativa}/{TENTATIVAS_FAIXA_PALAVRAS})..."
        )
        preservar = (
            "mantenha a pauta falada da abertura, os tópicos com as três "
            "batidas (contexto, fato e análise), as frases de virada "
            "e o fecho com a síntese e o que observar"
            if longo
            else "mantenha o preview de abertura, a consequência única e a "
            "conclusão em tensão que emenda de volta no preview"
        )
        cortar = (
            "cortando detalhe secundário da contextualização geral e da "
            "batida de contexto das pautas (sem eliminar nenhum tópico e sem "
            "tocar na análise de nenhum deles)"
            if longo
            else "cortando detalhes do ACONTECIMENTO"
        )
        acrescentar = (
            "acrescentando dado CONCRETO do material recebido (número, nome, "
            f"empresa, prazo) aos {TOPICOS_MAX} tópicos que já existem (NÃO "
            "acrescente tópico novo)"
            if longo
            else "acrescentando detalhes CONCRETOS ao ACONTECIMENTO (número, "
            "nome, mecanismo)"
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

        # Só substitui se a reescrita ficou MAIS PERTO da faixa; a próxima
        # tentativa continua de onde esta parou.
        if _dist_faixa(ajustadas) < _dist_faixa(palavras):
            roteiro = ajustado
        palavras = _contar_palavras(roteiro["texto_video"])
    else:
        if _dist_faixa(palavras) > 0:
            print(
                f"[aviso] texto_video ficou com {palavras} palavras faladas "
                f"depois de {TENTATIVAS_FAIXA_PALAVRAS} tentativas (faixa "
                f"{minimo}-{limite}); seguindo com a melhor versão — se ela "
                "furar o piso de duração, a execução aborta depois da narração."
            )

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
                f"; os {TOPICOS_MAX} tópicos e a análise concreta de cada um "
                "precisam estar no texto, e o vídeo fecha "
                "com o próximo marco a observar, sem CTA. "
                if longo
                else "; a narração abre com o PREVIEW (o que o vídeo vai "
                "entregar, sem dar o número e a fonte) e entrega isso antes de "
                "acabar, e assunto de nicho ganha âncora na contextualização. "
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

    # ESTRUTURA DAS QUATRO PARTES (só no longo, 2026-08-25): três tópicos e uma
    # citação literal em cada um. Por último de propósito — a reescrita da
    # faixa de palavras e a da auditoria pró-leigo devolvem um JSON inteiro e
    # podem QUEBRAR a citação que já estava certa, então quem confere tem que
    # ser o último a falar. Aborta se não fechar: sem os pontos de corte não
    # existe o vídeo de quatro partes.
    if longo:
        roteiro = _conferir_estrutura_longa(
            cliente, cfg, roteiro, instrucoes, conteudo
        )
        palavras = _contar_palavras(roteiro["texto_video"])

    # As tags passam pelo saneamento em código porque o limite que importa é o
    # da API, não o do prompt: o YouTube recusa o UPLOAD INTEIRO quando a soma
    # das tags passa de 500 caracteres — um vídeo já pago não pode morrer numa
    # tag a mais.
    roteiro["tags"] = limpar_tags(roteiro.get("tags"))

    print(f"[roteiro] {palavras} palavras faladas (faixa {minimo}-{limite})")
    print(f"[roteiro] Tema do dia: {roteiro['tema']}")
    print(f"[roteiro] Título: {roteiro['titulo']}")
    if roteiro.get("resposta_curta"):
        print(f"[roteiro] Resposta curta (GEO): {roteiro['resposta_curta']}")
    if roteiro.get("tags"):
        print(f"[roteiro] Tags: {', '.join(roteiro['tags'])}")
    else:
        print("[aviso] O roteiro saiu sem tags aproveitáveis; o vídeo sobe sem elas.")
    if roteiro.get("preview"):
        print(f"[roteiro] Preview da abertura: {roteiro['preview']}")
    if roteiro.get("pauta_falada"):
        print(f"[roteiro] Pauta falada na abertura: {roteiro['pauta_falada']}")
    if roteiro.get("pergunta"):
        print(f"[roteiro] Pergunta (P:/R: da descrição): {roteiro['pergunta']}")
    if roteiro.get("consequencia"):
        print(f"[roteiro] Consequência: {roteiro['consequencia']}")
    if roteiro.get("tese"):
        print(f"[roteiro] Tese: {roteiro['tese']}")
    if roteiro.get("topicos"):
        topicos = roteiro["topicos"]
        print(f"[roteiro] {len(topicos)} tópicos cobertos:")
        for t in topicos:
            print(f"  - {t.get('titulo', '')} — {t.get('dado', '')}")
            if t.get("analise"):
                print(f"      análise: {t['analise']}")
    if roteiro.get("sintese"):
        print(f"[roteiro] Síntese do fecho: {roteiro['sintese']}")
    if roteiro.get("o_que_observar"):
        print(f"[roteiro] O que observar: {roteiro['o_que_observar']}")
    return roteiro
