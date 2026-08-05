# Automação de Vídeos — Tech, IA, Mercado de Trabalho & Mercado Financeiro

Pipeline em Python que transforma as trends mais quentes de tecnologia, inteligência artificial, mercado de trabalho e mercado financeiro no X (Twitter) em um vídeo vertical narrado, em formato explicativo (análise/educacional), pronto para publicar. **Guerra, geopolítica militar e inteligência/espionagem estão fora do escopo do canal** (decisão de 2026-07-30: as contas de OSINT e defesa saíram da lista e os prompts vetam o tema):

> **Idioma — o canal decide, nunca o modelo.** O canal brasileiro publica **tudo** em português (título, descrição, narração e **capa**); o canal americano (`-usa`), **tudo** em inglês. O idioma é dado do pipeline (`cfg.publico`), não coisa a deduzir do conteúdo: os prompts do roteiro (`FOCO_BRASIL`/`FOCO_USA`) e o da capa (`pipeline/thumbnail.py`) recebem a regra explícita, e a capa ainda é **conferida em código** depois da resposta, com uma segunda chamada cobrando a correção quando sai fora. Ver "Formato longo".

1. **Coleta** os posts das últimas 24h da **lista fixa de contas** do canal (`CONTAS_PADRAO` em `pipeline/config.py`; `X_ACCOUNTS` no `.env` a substitui) via X API oficial v2, pay-per-use, com teto de leitura configurável, por **dois caminhos complementares**: a **busca por relevância** (`/2/tweets/search/recent`, mais a varredura opcional `has:videos`) e a **timeline cronológica** das contas (`/2/users/:id/tweets`) — ver "Como funciona a coleta por timeline". O **GPT** então os sumariza nas **10 trends mais quentes**, ordenadas pelo **valor da informação** (vazamento, documento, exclusivo, urgência, número inédito) **antes** do engajamento, cada uma com resumo, `valor_informativo`, `urgencia`, engajamento, nota de apelo visual e **quantos posts têm clipe de vídeo nativo** (a mesma chamada da coleta já traz o tipo de mídia de cada post). O GPT devolve o **inventário completo** dos posts com vídeo de cada trend (`posts_video`) à parte da lista de posts mais centrais (`posts`, truncada): a contagem sai da união dos dois, senão uma pauta que **tem** clipe — só não entre os posts mais centrais — seria vetada como se não tivesse material. Os posts com vídeo vão para a frente da lista, que é onde o lookup de mídias corta.
2. **GPT 5.6 Luna** classifica cada candidata (**macrotema** + **imagem mental**) — sem filtro nem score: todas as candidatas seguem vivas para a seleção. Os macrotemas são `ia`, `criacoes-ia`, `dev-software`, `hardware-chips`, `bigtech-negocios`, `mercado-trabalho`, `mercado-financeiro`, `ciencia-espaco` e `outro`. **`criacoes-ia` entrou em 2026-08-04**: é o oposto de `ia` — `ia` é a notícia sobre o **laboratório** (modelo lançado, benchmark, rodada), `criacoes-ia` é a notícia sobre **o que foi feito com a ferramenta** (vídeo, curta, música, imagem, personagem, jogo, app gerados por IA). É o macrotema que melhor casa com um formato montado só de clipes: a criação **é** o clipe. Além de rotular, o macrotema voltou a ter efeito de regra nos Shorts — ver o rodízio de temas no item 3.
3. **GPT 5.6 Luna** escolhe a trend guiado **somente pela audiência**: recebe os **últimos 100 vídeos publicados no canal selecionado com as métricas reais** (views/likes em tempo real, YouTube Data API) e os **campeões de retenção** (YouTube Analytics), e escolhe a candidata com a maior chance de performar com esse público — repetir o tipo de conteúdo que está performando é bem-vindo, **sem cota de variedade**. Nos **Shorts** vale, desde 2026-08-04, um **rodízio de temas** aplicado em código antes da escolha: as candidatas do macrotema do Short anterior saem da disputa, de modo que **cada Short sai de um tema diferente do anterior** (o veto cede se zerar as candidatas — melhor repetir o tema do que não publicar). O formato longo não tem rodízio. As métricas chegam ao prompt **normalizadas pela idade** (**views por hora** ao lado das views acumuladas): views acumuladas medem há quanto tempo o vídeo está no ar tanto quanto medem qualidade, então o pico de um ciclo já encerrado continuaria sendo o maior número da lista por dias depois do assunto morrer. É o views/h que mostra o ciclo esfriando — vídeos recentes de um macrotema rendendo bem menos por hora que os antigos do mesmo macrotema — e faz o modelo trocar de assunto sozinho. Regras duras, aplicadas em código: **candidata sem nenhum post com clipe de vídeo sai da disputa** (o formato é montado só com clipes do X) e a **verificação anti-repetição** — o GPT confere se a escolhida cobriria o **mesmo fato** de um vídeo publicado nas últimas 36h sem desenvolvimento novo; se sim, ela sai da disputa e a seleção refaz (se todas as candidatas caírem em uma das regras, não há vídeo).
4. **Firecrawl (sources=news)** busca **notícias recentes** sobre a trend escolhida (título, link, resumo e data) para complementar o material com fatos, nomes e números corretos (falha aqui não aborta: o roteiro segue com o resumo e os posts do X).
5. **GPT 5.6 Luna** escreve o roteiro **explicativo (análise/educacional) em tom adulto**, **sempre citando as fontes** (as contas do X que originaram a trend e os veículos das notícias do Firecrawl): para um adulto leigo (o público real: homens de 25-54) com metade da atenção — frases com **ritmo de fala natural** (8 a 16 palavras, teto 20, alternando curtas de impacto com mais cheias), uma ideia por frase, **vocabulário preciso de telejornal** (sem jargão de nicho nem sigla sem explicação), tom de furo de notícia (nunca infantil), e a estrutura fixa em **cinco blocos: PERGUNTA ESQUISITA (0-2s) → CONTEXTUALIZAÇÃO → DESENVOLVIMENTO → CONSEQUÊNCIA → CONCLUSÃO** — a conclusão responde a pergunta da abertura de um jeito que **emenda de volta nela quando o Short reinicia** (loop) e carrega a **disputa** do assunto, sem CTA falado. Ver "Como funciona a estrutura em cinco blocos". O roteiro traz também o **comentário de abertura** que o pipeline posta no vídeo (ver "Como funciona a alavanca de share e comentário"). O **título e a descrição são autossuficientes** (teste do leigo: sem nome de nicho, sem cauda de suspense; a descrição entrega o fato com a fonte, não é teaser) e prometem **exatamente** o que o vídeo entrega. Uma **auditoria pró-leigo** (chamada própria ao GPT) confere título, descrição e narração contra essas regras e pede **uma reescrita** quando reprova. O roteiro inclui **audio tags** (`[excited]`, `[whispers]`…) que ditam o tom da voz.
6. **X API** baixa um **pool de clipes de vídeo** dos posts originais da trend (o MP4 de **maior bitrate que cabe no teto de 60 MB**: o X serve o mesmo clipe em várias resoluções, e a de cima às vezes é um 4K de 2,9 GB — descartá-la descartava o clipe inteiro, então o download **desce a lista de variantes** até uma caber) — mais do que os 3 que entram na montagem, como folga para a auditoria — junto com a **conta de origem** de cada clipe e as **fotos dos posts**, que alimentam as cartelas. **Imagem estática nunca ocupa a tela**, então não há busca de imagens na web.
7. **Auditoria do material visual** (`pipeline/auditoria.py`): o **GPT com visão** descreve e **classifica** cada clipe do pool (cena real, reportagem de TV, gravação de tela, cartela, logo…) e diz se há **selo de emissora ou veículo de imprensa** na imagem. Em cima disso: **veto duro em código** — material de telejornal, vinheta de logotipo e qualquer mídia com selo de emissora saem da disputa, assim como mídia que não recebeu laudo — e uma **nota de pertinência de 1 a 5** dada pelo GPT, que mede só uma coisa: o quanto aquilo que a mídia **mostra** é o que a narração **diz** (abaixo de 3 sai; material que mostra a manchete de um veículo em vez do fato tem teto 2). **Zero clipe aprovado aborta a execução** (o formato longo exige um piso de 3). Roda **antes do ElevenLabs**, para a reprovação não custar créditos de narração, e deixa o rastro em `auditoria_clipe.json`.
8. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere), o pipeline **acelera a narração** conforme o formato (`VIDEO_VELOCIDADE`, 1.25x no Short; **1.0x, velocidade normal, no `--long-take`**) e **corta os silêncios**, deixando o áudio sem trechos parados. Os timestamps do alinhamento são reescalados nas duas etapas, então cortes, legendas, cartelas e figuras seguem sincronizados. O orçamento de palavras do roteiro é multiplicado pela velocidade — narração mais rápida cabe mais palavras nos mesmos segundos de tela. **Piso duro de duração, conferido aqui** (2026-08-04): Short abaixo de **50s** e vídeo longo abaixo de **120s** **abortam a execução sem publicar**. A conferência é depois da narração, e não só na faixa de palavras do roteiro, porque **palavra não é segundo** — o ritmo real do TTS varia ~25% de narração para narração, e só depois de narrar e cortar os silêncios se sabe a duração de verdade. O roteirista já teve **3 tentativas** de acertar o tamanho antes disso; o que sobra aqui é um vídeo que não deveria ir ao ar. O teto **não** aborta (vídeo comprido é defeito de retenção, não de formato).
9. **Cartelas de imagem nos momentos-chave** (`pipeline/cartelas.py`): a **foto do post da trend** (que o pipeline já lia e descartava) ou a **og:image de uma das notícias** entra **emoldurada por cima do clipe** por ~3,6s, no instante em que a narração **nomeia** o que ela mostra — a pessoa citada, o lugar atingido, o documento assinado. Cartão branco com cantos arredondados, sombra e o **crédito próprio** no rodapé (`Reprodução: X / @conta` ou o domínio do veículo; `Image Credit` no `-usa`). O movimento é o mesmo das figuras geradas: **sobe de baixo do quadro** até a posição de leitura e **sai por cima do quadro**. As imagens passam pela **mesma auditoria dos clipes** (visão + veto duro + nota), o gancho fica limpo (nada entra nos 3 primeiros segundos) e nenhuma cartela cai em cima de uma figura gerada.
10. **Figuras geradas por IA** (`pipeline/figuras.py`): o **gpt-image-2** desenha **gráficos, tabelas, infográficos, diagramas e cartazes** a partir dos **números que a própria narração diz**, ancorados numa **citação literal** do trecho em que o dado é falado. Só entra dado que está na narração — a tela nunca mostra um número que ninguém falou. Cada figura entra num cartão branco etiquetado como **infográfico do canal** (para o espectador não confundir com material de terceiro), **sobe de baixo do quadro** e **sai por cima**. Desde 2026-08-04 são a **única fonte de "big number" na tela**: os infográficos animados que o ffmpeg montava a partir de PNGs do Pillow (`pipeline/grafico.py`) foram removidos a pedido do usuário, junto com o módulo. Ver "Como funcionam as figuras geradas".
11. **ffmpeg** monta o vídeo vertical: o **fundo de cada momento é o próprio clipe daquele trecho, ampliado para cobrir a tela e borrado**; por cima entra o **clipe nítido em largura total, centrado** (clipe mais curto que a janela repete em loop). Os clipes **cobrem 100% da narração** (nunca há um instante sem imagem) com **crossfade curto e limpo** entre si. **Legendas** sincronizadas palavra a palavra — grandes, em **Archivo Black** branca com contorno preto, com entrada de "carimbo" editorial — são queimadas no vídeo, e o **crédito de reprodução** ("Reprodução Imagem: X" + "Conta `@usuario`" do post de origem; "Image Credit"/"Account" no modo `-usa`) fica no **canto superior direito** sobre uma tarja preta translúcida, trocando junto com o clipe. Enquanto uma **cartela ou figura** está na tela, tudo que está atrás dela **sai de foco**, e desde 2026-08-04 esse desfoque **entra e sai em rampa suave** (~0,45s de cada lado), acompanhando o movimento do cartão em vez de piscar de um quadro para o outro — ver "Como funciona a rampa de desfoque". O vídeo **não tem música de fundo** (a trilha foi removida em 2026-07-30, junto com o arquivo `assets/trilha.mp3`): sobram a narração e os wooshes das transições — o formato virou análise, e música disputa atenção com a informação falada. A cauda após a narração é de **0,15s** — curta de propósito, para a CONCLUSÃO emendar na pergunta de abertura quando o Short reinicia (loop).
12. O `.mp4` final vai para `output/`, é registrado em `videos.txt` e publicado automaticamente no **YouTube** (Data API v3). Roda sempre, independente da flag `-usa` (o horário de publicação é o do cronjob que dispara a execução). Logo após o upload, o pipeline posta o **comentário de abertura** do dono no vídeo (`commentThreads.insert`, 50 unidades de cota) — ver "Como funciona a alavanca de share e comentário".

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH. No Windows: `winget install Gyan.FFmpeg` (reabra o terminal depois)
- O fundo é montado a partir dos próprios clipes (não há fundo de cor); a resolução (padrão vertical 9:16, `1080x1920`) é configurável por `VIDEO_LARGURA`/`VIDEO_ALTURA`.
- Chaves de API (quatro):
  - **OpenAI** — em [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (sumarização das trends, roteiro e descrição dos clipes com `gpt-5.6-luna`).
  - **X API** — Consumer Key + Secret do app em [developer.x.com](https://developer.x.com) (coleta dos posts das contas acompanhadas e download dos clipes; pay-per-use).
  - **Firecrawl** — em [firecrawl.dev](https://firecrawl.dev) (busca de notícias via Search API com `sources=["news"]`).
  - **ElevenLabs** — em [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) (narração TTS).

## Configuração inicial (uma vez só)

```powershell
# 1. Crie o ambiente virtual e instale as dependências
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Crie o .env a partir do exemplo e preencha as três chaves
Copy-Item .env.example .env
notepad .env
```

## Rodando

Toda vez que quiser gerar o vídeo do dia:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py                    # Short vertical, público brasileiro
python main.py -usa               # Short vertical, público americano (inglês)
python main.py --long-take        # vídeo longo de análise (16:9), em português
python main.py --long-take -usa   # vídeo longo de análise (16:9), em inglês
```

Com `-usa`, todo o material — escolha do tema, título, descrição, texto narrado e hashtags — é produzido em inglês americano e direcionado 100% ao público dos EUA (a coleta também prioriza o que está dominando a conversa por lá), e a narração usa a voz americana configurada em `ELEVENLABS_VOICE_ID_USA`.

O resultado fica em uma pasta por execução (o formato longo marca a pasta com
`_longo`):

```
output/
└── 2026-06-10_titulo-do-dia/
    ├── roteiro.json     # tema, título, descrição e texto narrado
    ├── clipe_x_1.mp4 …  # clipes baixados dos posts do X (até 3; 8 no longo)
    ├── narracao.mp3     # narração TTS
    └── video_final.mp4  # este é o que você publica
```

## Formato longo (`--long-take`)

`--long-take` produz um **vídeo de análise em 16:9 (1920x1080), de 120 a 150
segundos, sem legendas**, para os **dois canais** (combina com `-usa`). É o
mesmo pipeline — mesma coleta do X, mesmas notícias do Firecrawl, mesmo
crédito de reprodução no canto superior direito — com outra direção editorial:

- **Enquadramento**: explica um acontecimento contemporâneo cobrindo **de 3 a 5
  tópicos** — recortes diferentes do mesmo fato, costurados por causa e efeito,
  nunca como lista de bullets falados. As quatro óticas do canal
  (**tecnologia/IA, negócios, mercado de trabalho e mercado financeiro**) são a
  fonte natural desses tópicos, mas **deixaram de ser uma cota em 2026-08-04**:
  quando o fato não tem leitura financeira real, o roteiro cobre outro recorte
  (regulação, concorrente, usuário, precedente) em vez de inventar uma — forçar
  a ótica ausente produzia exatamente a frase de analista vazia que a auditoria
  reprova. (Guerra e geopolítica militar saíram do canal em 2026-07-30.)
- **Espectador**: o adulto que está **procurando emprego ou em transição de
  carreira**. O payload obrigatório do vídeo é o que aquele acontecimento muda
  na prática para ele (setor que contrata ou corta, função na linha de tiro,
  habilidade que passa a valer, prazo) — conselho de coach e futurologia sem
  base reprovam na auditoria.
- **Estrutura**: a mesma do Short — PERGUNTA ESQUISITA → CONTEXTUALIZAÇÃO →
  DESENVOLVIMENTO (os 3 a 5 tópicos) → CONSEQUÊNCIA PARA QUEM TRABALHA →
  CONCLUSÃO (a resposta à pergunta + o próximo marco concreto a observar). Sem
  CTA e **sem loop** — aqui o vídeo fecha entregando.
- **Velocidade normal** (`LONG_VELOCIDADE=1.0`): análise não se acompanha em
  fala apressada. O Short é o contrário e roda acelerado.
- **Fontes**: pelo menos duas citações nominais na narração (veículo ou conta
  do X) e a **lista de links reais** anexada ao final da descrição do YouTube.
- **Sem legendas queimadas**: a narração se sustenta sozinha (nenhuma frase
  pode depender de texto na tela).
- **Capa customizada** (`pipeline/thumbnail.py`): um quadro real do vídeo (2s,
  já com a sala e a TV) escurecido, com 2 a 5 palavras em Archivo Black na
  base. O texto vem do GPT com duas regras duras. A primeira, dizer **o fato**,
  nunca provocar: "GOOGLE CORTA 8 MIL VAGAS" e não "VOCÊ NÃO VAI ACREDITAR",
  porque curiosidade fabricada traz clique e perde a audiência no primeiro
  segundo. A segunda, o **idioma do CANAL** — português no canal brasileiro,
  inglês no americano —, que entra explícito na instrução (`cfg.publico`) e é
  **conferido em código** depois da resposta (`config.idioma_plausivel`, a mesma
  checagem usada pelas figuras), com uma segunda chamada cobrando a correção e o
  título do vídeo como reserva. Antes o prompt era escrito em
  português e só pedia "no mesmo idioma do título": o modelo tinha que deduzir o
  idioma de um sinal fraco contra um prompt inteiro em português e deduziu
  errado — o último vídeo longo do canal americano saiu com a capa "GOOGLE LEVA
  ROBÔS AO CORPO" em cima de um vídeo narrado em inglês (corrigido em
  2026-08-04).
  Falha aqui não aborta (cai na capa automática do YouTube), e o upload da
  capa exige **canal verificado** — sem verificação o YouTube devolve 403 e o
  log avisa. Só no formato longo: no Short o feed mostra o vídeo rodando.
- **Sala de estar com TV** (`pipeline/cenario.py`): o clipe não ocupa o quadro
  inteiro — aparece **dentro da TV de uma sala**, desenhada com Pillow (sem
  asset externo nem licença de imagem). É identidade visual só do longo; o
  Short segue em tela cheia. A tela ocupa `TELA_FRAC_LARGURA` (0.76) da
  largura — subir aproxima o clipe do tamanho de antes e some com a sala.
- **Material**: até **8 clipes** de vídeo do X (consultando até 16 posts da
  trend, e baixando 11 para a auditoria escolher 8), trocando a cada 8-20s;
  clipe vertical aparece como faixa central sobre o próprio clipe borrado. Até
  **4 cartelas** de imagem e **4 figuras geradas** pelo gpt-image-2, espalhadas
  pela narração. A auditoria exige um **piso de 3 clipes aprovados** — 120 a 150
  segundos presos em um ou dois clipes é insustentável, então abaixo disso o
  vídeo não sai.
- **Regras duras próprias**: candidata precisa de **4 posts com clipe** para
  disputar (`LONGO_MIN_POSTS_VIDEO`, derivado do piso de 3 da auditoria mais
  uma folga, já que a auditoria reprova parte do material) — sem ninguém no
  portão a execução aborta ali, antes de gastar roteiro e narração, porque
  seguir com material insuficiente é gastar para falhar adiante. E o veto a
  vídeo repetido (janela de 72h)
  compara **só com os vídeos longos** já publicados — a rajada de Shorts do
  dia não bloqueia o longo, e um Short sobre o mesmo fato não conta como
  repetição.
- **Janela de coleta maior (`JANELA_HORAS=48` nos crons longos)**: o gargalo do
  formato não é a edição, é achar **um acontecimento com vários posts de vídeo
  nativo**. Video de um fato específico é raro — a maior parte dos posts sobre
  ele é texto. Com a janela de 4h dos Shorts, execuções reais achavam trends com
  0, 1 ou 2 clipes e abortavam no piso de 3. Alargar para 48h **não custa mais
  na X API** (o teto de leitura é o `X_MAX_POSTS`), só troca *quais* posts
  entram: os mais relevantes de dois dias em vez de os de quatro horas. Case a
  janela com a **cadência do cron** — 4h para quem roda de 4 em 4 horas, 48h
  para quem roda segunda/quarta/sexta.

A duração final segue a narração: o roteirista escreve dentro de uma faixa
dura de palavras (~277 a 316 faladas, calculada a partir do ritmo real medido
do TTS) e tem até **3 tentativas** de entrar nela. O **piso de 120s é duro**:
narração mais curta que isso **aborta a execução sem publicar**, depois do
corte de silêncios — palavra não é segundo, e só depois de narrar se sabe a
duração de verdade. O teto de 150s só gera aviso no log: vídeo comprido demais
é defeito de retenção, não de formato.

## Ajustes no .env

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `X_ACCOUNTS` | vazio | Opcional: usa somente estas contas no lugar da lista fixa `CONTAS_PADRAO` (`pipeline/config.py`) |
| `X_MAX_POSTS` | `200` | Teto de posts lidos por execução (a X API cobra por post lido) |
| `X_MAX_POSTS_VIDEO` | `60` | Leituras extras de uma varredura `has:videos` sobre as **mesmas** contas — a coleta normal ordena por relevância e não prefere vídeo, então o post com clipe perdia vaga para texto. Nenhuma fonte nova; `0` desliga |
| `X_MAX_POSTS_BUSCA` | `30` (só `--long-take`) | Busca **aberta** por clipes do assunto, fora das contas do canal. Fontes **não curadas** — a auditoria é a única guarda, e ela julga pertinência, não veracidade; `0` desliga |
| `X_MAX_POSTS_TIMELINE` | `60` | Leituras da **timeline** das contas (`/2/users/:id/tweets`), cronológica: é ela que pega o post fresco que a busca por relevância ainda não ranqueou. Custa **1 requisição por conta**, então o orçamento cobre um subconjunto **rotativo** por execução; `0` desliga |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados. Alargar **não** custa mais na X API (o teto é o `X_MAX_POSTS`; a janela só decide de que intervalo saem esses posts). Case com a **cadência do cron**, não com o formato: em produção os Shorts rodam com `4` (de 4 em 4 horas) e os crons `--long-take` com `48` — ver a nota abaixo |
| `NUM_TRENDS` | `10` | Quantas trends mais faladas do X coletar para escolher a do vídeo |
| `NUM_NOTICIAS` | `6` | Quantas notícias (Firecrawl news) buscar para enriquecer a trend |
| `TEXT_MODEL` | `gpt-5.6-luna` | Modelo do roteiro, da sumarização das trends e da visão |
| `IMAGEM_MODEL` | `gpt-image-2` | Modelo das figuras geradas (gráficos, tabelas, infográficos, cartazes) |
| `IMAGEM_QUALIDADE` | `medium` | `low`/`medium`/`high`/`auto`. `medium` é o piso para figura com texto: em `low` o rótulo sai borrado |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `60` | Duração-alvo da narração em segundos (a duração final segue o áudio; o corte de silêncios tira ~10%). **Piso duro de 50s**: Short mais curto que isso não é publicado, e valor abaixo de 50 aqui é recusado no carregamento |
| `VIDEO_VELOCIDADE` | `1.25` | Velocidade da narração e, com ela, do ritmo do vídeo inteiro. O **Short roda acelerado**; o `--long-take` roda em `1.0` (`LONG_VELOCIDADE`). O orçamento de palavras do roteiro é multiplicado por este valor |
| `VIDEO_LARGURA` | `1080` | Largura do vídeo |
| `VIDEO_ALTURA` | `1920` | Altura do vídeo |
| `MAX_POSTS_MIDIA` | `12` | Posts da trend consultados no lookup de mídias (a X API cobra por post lido) |
| `POOL_EXTRA_CLIPES` | `3` | Clipes baixados além dos que entram na montagem, como folga da auditoria |
| `MAX_FOTOS` | `4` | Fotos dos posts baixadas para as cartelas (`0` desliga) |
| `MAX_CARTELAS` | `2` | Cartelas de imagem sobrepostas nos momentos-chave (`0` desliga) |
| `MAX_FIGURAS` | `2` | Figuras **geradas** pelo gpt-image-2 a partir dos números da narração — única fonte de "big number" na tela (`0` desliga) |
| `LONG_DURACAO` | `135` | Só com `--long-take`: duração-alvo da narração (aceita 120 a 150; **abaixo de 120s o vídeo não sai**) |
| `LONG_LARGURA` / `LONG_ALTURA` | `1920` / `1080` | Só com `--long-take`: resolução 16:9 |
| `LONG_MAX_CLIPES` | `8` | Só com `--long-take`: clipes do X usados na montagem |
| `LONG_MAX_POSTS_MIDIA` | `16` | Só com `--long-take`: posts da trend consultados para achar os clipes |
| `LONG_NUM_NOTICIAS` | `10` | Só com `--long-take`: notícias que embasam a análise |
| `LONG_MAX_CARTELAS` | `4` | Só com `--long-take`: cartelas de imagem sobrepostas |
| `LONG_MAX_FOTOS` | `6` | Só com `--long-take`: fotos dos posts baixadas para as cartelas |
| `LONG_MAX_FIGURAS` | `4` | Só com `--long-take`: figuras geradas pelo gpt-image-2 |
| `LONG_VELOCIDADE` | `1.0` | Só com `--long-take`: velocidade **normal** da narração (análise não se acompanha em fala apressada) |
| `YOUTUBE_CLIENT_ID` | — | Client ID OAuth (Google Cloud, tipo "Desktop app") |
| `YOUTUBE_CLIENT_SECRET` | — | Client secret OAuth |
| `YOUTUBE_REFRESH_TOKEN` | — | Canal português; preenchido por `--auth-youtube` |
| `YOUTUBE_REFRESH_TOKEN_USA` | — | Canal inglês (`-usa`); preenchido por `--auth-youtube-usa` |
| `YOUTUBE_PRIVACY` | `public` | `public`, `unlisted` ou `private` |
| `YOUTUBE_CATEGORY_ID` | `28` | Categoria do YouTube (28 = Science & Technology) |

## Publicação automática no YouTube

A publicação usa a **YouTube Data API v3** com OAuth e roda sempre, em qualquer modo (`-usa` ou não). A autorização pede o conjunto completo de escopos do YouTube (publicar, ler e gerenciar), então o mesmo refresh token também é usado para ler os últimos vídeos do canal (passo 3 do fluxo) e cobre features futuras sem reautenticar. Configure uma vez:

1. No [Google Cloud Console](https://console.cloud.google.com), ative a **YouTube Data API v3** e crie uma credencial **OAuth client ID** do tipo **Desktop app**. Coloque o `client_id` e o `client_secret` no `.env` (`YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`).
2. Gere o refresh token de longa duração (abre o navegador para você autorizar a conta do canal):

   ```powershell
   python main.py --auth-youtube
   ```

   O token é salvo automaticamente em `YOUTUBE_REFRESH_TOKEN` no `.env`. A partir daí, toda execução do `python main.py` publica o vídeo ao final.

### Dois canais (português e inglês)

Cada canal tem seu próprio refresh token. A seleção é automática pela flag `-usa`:

- `python main.py` → publica no **canal português** (`YOUTUBE_REFRESH_TOKEN`)
- `python main.py -usa` → publica no **canal inglês** (`YOUTUBE_REFRESH_TOKEN_USA`)

Para autorizar o canal inglês (na tela do Google, escolha o canal em inglês):

```powershell
python main.py --auth-youtube-usa
```

Os dois usam o mesmo `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET` — muda só qual canal você seleciona no consentimento.

O pipeline é **fail-fast**: credenciais ausentes/quebradas, falha ao ler os últimos vídeos ou os campeões de retenção, classificação indisponível, verificação de vídeo repetido indisponível e falha no upload — tudo isso derruba a execução com erro explícito (para o agendador poder alertar), em vez de seguir e degradar o vídeo em silêncio. As leituras do canal acontecem logo no início, antes de qualquer chamada paga (X/OpenAI). **Exceção (Firecrawl)**: falha na busca de notícias só gera aviso no log e a execução segue (o roteiro sai do resumo/posts do X). Já os clipes são obrigatórios: se nenhum clipe dos posts da trend puder ser baixado, a execução aborta (o formato não admite imagem estática). Se o upload falhar, o vídeo continua salvo em `output/` e registrado em `videos.txt` para publicação manual.

## Como funciona o corte de silêncios

Depois da narração, o ffmpeg (`silencedetect`) localiza os silêncios e o pipeline os corta (`aselect`), deixando uma pequena folga em cada um para o áudio não ficar com trechos parados. O ponto crítico: os timestamps do alinhamento da ElevenLabs são **remapeados** para o novo áudio, então as legendas e a sincronização das imagens continuam corretas. Se não houver silêncio relevante (ou faltar ffmpeg), o áudio original é mantido. O roteiro também é escrito para ser dinâmico, rápido e direto ao ponto, reduzindo as pausas na origem.

## Como funcionam as legendas

(No formato longo, `--long-take`, **não há legendas**: esta seção vale só para os Shorts.) A ElevenLabs retorna o tempo de fala de cada caractere (`/with-timestamps`), e o pipeline mostra **uma palavra por vez** em maiúsculas, gravadas em `legendas.ass` e queimadas no vídeo pelo ffmpeg. Como sempre há clipe na tela, as legendas ficam na **parte inferior** para não cobrir o clipe nítido. O estilo é editorial de rede social: texto **branco com contorno preto grosso e sombra suave**, fonte **Archivo Black** (em `fonts/ArchivoBlack-Regular.ttf`, licença OFL), tamanho de manchete, com entrada de "carimbo" (a palavra surge um pouco maior e assenta no tamanho final). Desde 2026-08-04 a **altura do glifo é levemente reduzida** (`ESCALA_Y = 92`, o `ScaleY` do ASS): o **corpo da fonte não mudou** — o que muda é só a proporção, que fica mais baixa e condensada, devolvendo o ar editorial e minimalista sem perder a força de manchete (que vem da largura e do peso, não da altura). O `scy` do ASS é absoluto, então a animação de entrada também sai desse valor — escrever `scy100` nela anularia o achatamento em toda palavra. O arquivo `alinhamento.json` de cada execução guarda os timestamps para depuração.

## Como funciona a alavanca de share e comentário

Diretriz de **2026-07-28**, tirada dos números do canal BR: na faixa de topo (12 vídeos, 306.947 views) a retenção já era ótima — `averageViewPercentage` de 121%, curva de retenção terminando acima de 1,0, ou seja, o loop funcionando — mas a propagação social era nula: **82 comentários (0,027%) e 39 compartilhamentos (0,013%)**. O vídeo entregava informação fechada e não dava o que discutir. Duas mudanças, nenhuma delas um CTA falado (o formato não tem e não vai ter — pedido explícito quebra o loop, que é a métrica que sustenta a distribuição):

- **CORTE com disputa** (Shorts): a última frase continua emendando no hook, mas agora carrega **a disputa do assunto** — o fato do próprio vídeo sobre o qual duas pessoas razoáveis brigariam (quem está certo, quem paga a conta, se valeu a pena). O espectador termina com uma opinião formada e um interlocutor em mente. O teste, no prompt: se não dá para discordar da frase ou de quem ela responsabiliza, é só suspense e o roteirista reescreve. Proibido virar isca — pergunta dirigida ao espectador, opinião do canal e pedido de like/comentário/share continuam vetados.
- **Comentário de abertura** (os dois formatos): o roteiro passa a trazer um campo `comentario` (duas frases, até 280 caracteres) que o pipeline posta como comentário do dono assim que o vídeo sai. Ele vai **onde o vídeo não foi** — o dado, número ou contexto real que não coube na narração — e fecha com uma **pergunta aberta** sobre a disputa. Não resume nem repete a narração: quem chega nos comentários já assistiu. Duas regras são aplicadas **em código** (`_limpar_comentario`), não só no prompt: **URL é removida** (link em comentário do dono reduz o alcance do vídeo) e **pedido de like/inscrição é removido** (seria o CTA voltando pela porta dos comentários). Se sobrar texto vazio, o vídeo sai sem comentário.

O comentário **não fica fixado**: a YouTube Data API v3 não tem endpoint de fixar comentário — a fixação, se você quiser, é manual no YouTube Studio. Como comentário do dono do canal, ele já aparece com destaque na aba. Falha ao postar **só avisa no log** (o vídeo já está no ar; derrubar a execução depois de uma publicação bem-sucedida trocaria um comentário perdido por um alarme falso).

> Histórico, para não confundir: entre 27/06 e 14/07/2026 existiu um comentário automático **de divulgação** (Turing/Firecrawl) só no canal US, removido a pedido. Este aqui é editorial e existe para abrir discussão — outro propósito.

## Infográficos animados (removidos em 2026-08-04)

Até 2026-08-04 o pipeline montava, além das figuras geradas, **infográficos animados** próprios: `pipeline/grafico.py` renderizava com Pillow **contadores** que subiam do zero e **barras comparativas**, e o ffmpeg os sobrepunha no terço superior do vídeo. Eles foram **removidos a pedido do usuário**, junto com o módulo — os "big numbers" da tela passam a vir **só das figuras do gpt-image-2** (`pipeline/figuras.py`), que já cobrem o mesmo repertório com uma identidade visual única em vez de duas.

Com eles saiu também a regra que **escondia o crédito de reprodução** enquanto um infográfico estava na tela: o crédito sumia porque o painel ocupava o terço superior, e cartelas e figuras ficam no **miolo** da tela, onde nunca encostaram nele.

## Como funcionam os clipes e os cortes

O pipeline baixa um **pool** de clipes de vídeo dos posts originais da trend (X API, MP4 de maior bitrate): **3 + `POOL_EXTRA_CLIPES`** entram na disputa por 3 vagas na montagem (**8 vagas no `--long-take`**). O **GPT com visão** descreve e classifica cada um a partir de frames extraídos pelo ffmpeg, a **auditoria** derruba o que não presta (veja abaixo) e um "editor de cortes" (GPT) decide **quando cada clipe aprovado entra**, ancorando cada corte numa **citação exata da narração** (convertida em tempo pelos timestamps do ElevenLabs) — o primeiro clipe abre o gancho, e clipe mais curto que a janela repete em **loop**. Na tela, cada clipe carrega o próprio **crédito de reprodução** no canto superior direito ("Reprodução Imagem: X" + "Conta `@usuario`" do post de onde ele veio). O plano fica em `cortes.json`; se ele falhar, os clipes aprovados são distribuídos uniformemente pela narração, **na ordem da nota da auditoria** (o melhor abre o vídeo).

## Como funciona a auditoria do material visual

O que motivou a camada: até então nada filtrava os clipes. O pipeline usava os **primeiros** que a X API devolvesse, e o planejador de cortes até era instruído a omitir clipe fora do assunto — mas quando ele omitia, o plano era reprovado e o fallback usava **todos** os clipes baixados de volta. O caminho do descarte levava ao uso, e vídeo de telejornal ou cena sem relação com a narração entrava.

Agora `pipeline/auditoria.py` roda sobre o pool, em duas etapas:

1. **Veto duro, em código** — a mesma chamada de visão que descreve a mídia também a **classifica** (`cena_real`, `reportagem_tv`, `estudio_ou_podcast`, `gravacao_de_tela`, `cartela_ou_manchete`, `logo_ou_marca`) e diz se há **selo de emissora ou veículo de imprensa** na imagem. Sai da disputa: material de telejornal, vinheta de logotipo, qualquer mídia com selo de emissora e qualquer mídia **sem laudo de visão**. É regra fixa de propósito: o problema é recorrente, e julgamento de LLM sobre "isso é jornalismo de terceiro?" oscila de execução para execução.
2. **Nota de pertinência (1 a 5)** — uma chamada ao GPT compara o que cada mídia **mostra** com o que a narração **diz**. Abaixo de 3 a mídia sai. A escala separa três coisas que já foram confundidas e custaram execução:
   - **3 = imagem real do acontecimento coberto**, mesmo sem dar para identificar o objeto. Um clarão no céu noturno, num vídeo sobre aquela guerra, é registro do conflito — B-roll legítimo, não material "ilegível". Era exatamente isto que vinha sendo reprovado por um teto de indecifrabilidade.
   - **2 = genérico de arquivo.** O teste: trocando o assunto do vídeo, a imagem continuaria servindo? Se sim, é 2 (paisagem urbana qualquer, sala de servidores qualquer).
   - **1 = contradiz a narração** — ataque acontecendo enquanto a narração fala em trégua, outro número/pessoa/data no texto da tela. É o pior caso: material irrelevante só não ajuda, material contraditório desmente o próprio vídeo.

   Teto de **cobertura de imprensa** (máx. 2) só pega o que é *só rótulo*: cartela de manchete parada, print de site, chamada de estúdio e nada mais. Telejornal que exibe **imagens do fato** é julgado por essas imagens na escala normal — senão o material que o veto duro passou a admitir no `--long-take` voltaria a morrer aqui, pela nota. Esta etapa **falha aberta** (aviso no log e todos passam): o veto duro já carrega a regra do canal, e derrubar o vídeo por um erro transitório da OpenAI desperdiçaria tudo que veio antes.

A auditoria roda **antes do ElevenLabs**, então reprovar não custa crédito de narração. Ficar abaixo do piso de clipes aprovados (1 no Short, 3 no `--long-take`) **não aborta mais a execução**: desde 2026-08-05 a candidata sai da disputa e o pipeline **tenta outra trend** — ver "Como funciona o fallback de tema". A mensagem aponta o `auditoria_clipe.json` da pasta, que lista aprovados e reprovados com nota e motivo. As imagens das cartelas passam pela mesma peneira (`auditoria_imagem.json`).

## Como funciona o fallback de tema

A trend é escolhida por um sinal **indireto** de material: quantos posts dela têm clipe de vídeo nativo. O sinal erra dos dois lados — o clipe pode não baixar (post apagado, arquivo acima do teto) e a auditoria pode reprovar tudo que baixou. Quando isso acontecia, a execução inteira morria com `exit 1` **com a coleta e a classificação já pagas** e outras candidatas ainda vivas na lista.

Desde **2026-08-05**, a candidata que não rende material sai da disputa e o pipeline refaz os passos 4 a 7 com a **próxima trend**, até `TENTATIVAS_TREND` (3) candidatas por execução. As duas falhas cobertas são: **nenhum clipe baixado** e **auditoria abaixo do piso**.

O laço fecha **antes do TTS** de propósito. Cada tentativa extra custa notícias + roteiro + visão, e **nenhuma custa narração** — que é o crédito caro. Por isso o **piso de duração continua abortando seco**: narração curta é defeito do roteiro, e trocar de tema não conserta isso, só paga o ElevenLabs de novo. Se as 3 candidatas falharem, aí sim a execução aborta, e as alavancas são as de sempre: alargar `JANELA_HORAS`, subir `X_MAX_POSTS` ou revisar as contas acompanhadas.

**Exceção do `--long-take`: telejornal entra marcado, não vetado.** No formato longo, material de tipo `reportagem_tv` e mídia com selo de emissora deixam de cair no veto duro e entram **marcados como representação visual** — o clipe vai para a tela **dessaturado**, com a etiqueta `REPRESENTAÇÃO VISUAL` (`ILLUSTRATIVE FOOTAGE` no `-usa`) no rodapé esquerdo, enquanto os outros clipes da mesma montagem seguem coloridos e sem etiqueta. O motivo: 120 a 150 segundos de tela raramente se sustentam só com cena crua, e a marcação resolve o que originou o veto — o espectador tomar cobertura de terceiro por material do canal. `logo_ou_marca` continua vetado nos dois formatos (vinheta de logotipo não representa assunto nenhum), a nota de pertinência continua valendo para todo mundo, e no formato curto **nada muda**. O `auditoria_clipe.json` marca cada aprovada com `representacao_visual`.

## Como funcionam as cartelas de imagem

Um dos dois tipos de sobreposição, ao lado das figuras geradas: nos **momentos-chave** — quando a narração **nomeia** a pessoa, o lugar, o documento ou o produto — uma imagem entra **emoldurada por cima do clipe** por ~3,6s. O corpo do vídeo continua sendo só clipe de vídeo do X; imagem estática nunca ocupa a tela sozinha.

- **De onde vêm** — as **fotos dos posts da trend** (que o pipeline já lia da X API e descartava no filtro de tipo: são o material mais barato, vêm no mesmo lookup e estão no assunto por construção) e a **og:image das notícias** já buscadas no Firecrawl, creditadas pelo domínio do veículo. Nenhuma chamada nova de API, e nada de busca de imagem em banco.
- **Como aparecem** — cartão branco com cantos arredondados e sombra, **crédito próprio no rodapé** (`Reprodução: X / @conta` ou `Reprodução: reuters.com`; `Image Credit` no `-usa`). Movimento de direção única: **sobem de baixo do quadro** até a posição de leitura, ficam paradas enquanto são lidas e **saem por cima do quadro**. Centralizado acima da faixa das legendas no vertical, no meio da tela no 16:9. **Aumentadas em 2026-08-04** (78% da largura no vertical, 48% no 16:9, contra 62%/34% antes): o cartão pequeno perdia a disputa pela atenção com o clipe em movimento justamente no segundo em que a narração nomeia o que ele mostra. A posição de leitura subiu junto (0,44 → 0,38 da altura) para a base do cartão maior não invadir a faixa das legendas.
- **Onde não aparecem** — nos **3 primeiros segundos** (o gancho fica com o clipe limpo) e em cima de uma figura gerada (as janelas nunca coincidem).
- **Quantas** — até `MAX_CARTELAS` (2; 4 no `--long-take`), escolhidas pelo GPT entre as imagens aprovadas na auditoria, com o momento ancorado numa **citação exata da narração**. O plano fica em `cartelas.json`. `MAX_CARTELAS=0` desliga a feature; qualquer falha só deixa o vídeo sem cartelas.

## Como funcionam as figuras geradas

O `pipeline/figuras.py` desenha, com o **gpt-image-2**, todo o repertório de infografia do canal: **gráfico de barras, gráfico de linha, tabela, infográfico de pictogramas, diagrama de causa e efeito e cartaz de um número só**. Desde 2026-08-04 é a **única** camada de "big number" do vídeo — os infográficos animados que o Pillow desenhava e o ffmpeg sobrepunha (`pipeline/grafico.py`) foram removidos a pedido do usuário, com o módulo junto.

- **De onde vêm os dados** — **exclusivamente da narração**. Um GPT lê o texto narrado e devolve, para cada figura, a **citação literal** do trecho em que o dado é dito, o **tipo** de figura, o título e os pares rótulo/valor. Número que está nas notícias mas não foi falado **não** entra: a tela mostrando um valor que ninguém disse é o pior defeito possível nesta camada.
- **Como são desenhadas** — o estilo visual é **fixo em código** (fundo branco, tipografia grotesca pesada, preto quase puro + um único laranja de destaque, sem 3D, sem sombra, sem marca d'água), porque identidade visual não pode variar de vídeo para vídeo. O prompt lista os rótulos exatos e proíbe qualquer texto além deles — o modelo ainda erra tipografia quando o cartaz é cheio, e figura enxuta é figura legível.
- **Como aparecem** — cartão branco com sombra, etiquetado como **infográfico do canal** (`CHANNEL GRAPHIC` no `-usa`) para o espectador não confundir com gráfico publicado por terceiro, do mesmo jeito que o crédito de reprodução distingue o clipe de terceiro. **Sobem de baixo do quadro**, ficam ~4s paradas e **saem por cima do quadro**. **Aumentadas em 2026-08-04** (84% da largura no vertical, 54% no 16:9, contra 72%/40% antes), e aqui pesa mais que nas cartelas: a figura carrega **texto** (rótulo, valor, título), e rótulo pequeno num cartão pequeno visto no celular não é lido — o que anula a razão de a figura existir.
- **Em que idioma** — no **idioma do CANAL** (`cfg.publico`), como todo o resto: título, rótulos e valores em português no canal brasileiro e em inglês no americano, com a notação de cada um (`21 mil` / `US$ 2 bi` contra `21K` / `$2B`). O idioma entra **explícito** na instrução e nos exemplos do esquema, e o texto devolvido é **conferido em código** (`config.idioma_plausivel`): uma reescrita é cobrada, e a figura que continuar no idioma errado é **descartada** — texto errado aqui sai queimado na imagem e não tem conserto depois de publicado. Até 2026-08-05 este era o último lugar do pipeline que **inferia** o idioma ("no idioma da narração", com exemplos em português dentro de um prompt em português), o mesmo sinal fraco que já tinha posto uma capa em português no canal americano.
- **Onde não aparecem** — nos 3 primeiros segundos (gancho limpo) e em cima de uma cartela (as janelas nunca coincidem).
- **Quantas** — até `MAX_FIGURAS` (2; 4 no `--long-take`). O plano fica em `figuras.json`. A ancoragem na narração é conferida **antes** da geração da imagem, que é a única etapa cara aqui. `MAX_FIGURAS=0` desliga; qualquer falha só deixa o vídeo sem figuras.

O roteirista sabe dessa camada: o prompt pede que **todo número, comparação e lista curta seja dito na narração, com valor e unidade** — dado não falado não vira figura —, e ao mesmo tempo mantém a proibição de referenciar a tela ("como você vê no gráfico"), porque a narração tem que se sustentar de olhos fechados.

## Como funciona a rampa de desfoque

Enquanto uma **cartela** ou uma **figura gerada** está na tela, tudo que está atrás dela sai de foco (`CARTELA_BLUR_SIGMA = 20`), para a imagem do momento-chave não disputar atenção com o clipe em movimento. Até 2026-08-04 esse desfoque **ligava e desligava de um quadro para o outro** — um corte seco de nitidez no meio de um clipe em movimento, exatamente o tipo de solavanco que o resto da montagem evita. A pedido do usuário, ele passou a **entrar e sair em rampa** (`CARTELA_BLUR_RAMPA = 0,45s` de cada lado), casada com o movimento do cartão: o fundo desfoca enquanto a cartela sobe e volta ao foco enquanto ela sai.

A implementação existe porque o **`gblur` do ffmpeg não aceita expressão por quadro no `sigma`** — só `enable`, do suporte a *timeline*. Então a rampa é feita por **níveis**: `CARTELA_BLUR_NIVEIS = 5` filtros `gblur`, cada um com um sigma fixo (4, 8, 12, 16, 20) e ligado **apenas nas fatias de tempo em que aquele nível vale**, somadas as fatias de **todas** as cartelas do vídeo. Como as fatias são disjuntas, o **custo total é o de um único desfoque** — o que muda é só quando cada um liga. O nível cheio cobre um intervalo contíguo (a subida termina onde o platô começa e o platô termina onde a descida começa), e os `GAP_CARTELAS` de 1,2s entre sobreposições garantem que duas rampas nunca se encavalem.

## Como funciona a coleta por timeline

A busca do X (`/2/tweets/search/recent`) ordena por **relevância**, e relevância no X é engajamento acumulado. O post publicado há vinte minutos — o **vazamento**, o comunicado, o número que acabou de sair — ainda não tem engajamento nenhum, e por isso é justamente o que a busca deixa de fora. Como a diretriz do canal passou a priorizar informação de alto valor e urgência, essa era a lacuna estrutural da coleta.

A timeline (`/2/users/:id/tweets`) resolve isso: é **cronológica** e não faz juízo de popularidade. Ela aceita o mesmo bearer app-only da busca (a `reverse_chronological` **não** serve — exige contexto de usuário, OAuth 1.0a/PKCE, que o pipeline não tem).

- **Custo** — 1 requisição por conta. O orçamento `X_MAX_POSTS_TIMELINE` é dividido em "posts por conta" (mínimo 5 da API) e cobre um **subconjunto rotativo** das contas por execução; um cursor circular persistido (`.rotacao_timeline`) garante que todas passem ao longo do dia, como já acontece com os lotes da busca.
- **IDs** — a timeline é endereçada por ID numérico, resolvido em `/2/users/by` e guardado em `.contas_ids.json` por 30 dias (a lista de contas quase não muda).
- **Fusão** — os posts da timeline entram deduplicados por URL, depois da busca por relevância e da varredura `has:videos`; o log diz quantos posts frescos a busca não tinha devolvido.

## Como funciona a estrutura em cinco blocos

Todo roteiro — Short e `--long-take` — segue a mesma ordem de aula bem dada:

1. **PERGUNTA ESQUISITA** (a primeira frase, campo `pergunta`): concreta, estranha e específica, com coisa/número/gente dentro ("quanto custa desligar um data center por um dia?"). É **proibida** pergunta abstrata, retórica ou dirigida ao espectador ("você já parou pra pensar?"). O estranhamento é o gancho: o cérebro quer a resposta.
2. **CONTEXTUALIZAÇÃO**: o mínimo para a pergunta fazer sentido — e é aqui que assunto de nicho ganha a âncora pró-leigo ("a empresa por trás do ChatGPT").
3. **DESENVOLVIMENTO**: o miolo. O que aconteceu, com número, nome, **mecanismo** e a fonte nominal.
4. **CONSEQUÊNCIA**: uma só, concreta — o que muda para quem trabalha, investe ou usa aquilo.
5. **CONCLUSÃO**: a **resposta** à pergunta da abertura, em uma frase seca que carrega a **disputa** do assunto. No Short ela emenda de volta na pergunta quando o vídeo reinicia (**loop**); no `--long-take` ela fecha de verdade, com o próximo marco a observar.

A auditoria pró-leigo (chamada própria ao GPT) verifica isso em código de prompt: reprova se a primeira frase não for pergunta, se a pergunta for abstrata ou dirigida ao espectador, e se a narração **não responder** a pergunta antes de acabar.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (X API pay-per-use, ~US$ 0,005/post, teto `X_MAX_POSTS`) | ~US$ 1,00 com o padrão de 200 posts |
| Timeline das contas (X API, teto `X_MAX_POSTS_TIMELINE`) | ~US$ 0,30 com o padrão de 60 posts (`0` desliga) |
| Figuras geradas (gpt-image-2, `MAX_FIGURAS` imagens em qualidade `medium`) | ~US$ 0,08 por figura (`MAX_FIGURAS=0` desliga) |
| Mídias dos posts da trend (X API, até 12 posts + pool de 6 clipes e 4 fotos) | ~US$ 0,11 (~US$ 0,17 com `--long-take`: 16 posts, 11 clipes, 6 fotos) |
| Busca de notícias (Firecrawl Search) | ~2 créditos por consulta |
| GPT 5.6 Luna (sumarização + seleção + roteiro + visão e auditoria das mídias) | ~US$ 0,08 (~US$ 0,14 com `--long-take`: mais mídias no pool) |
| ElevenLabs (~1.000 caracteres por narração de 60s) | ~1.000 créditos do plano (~1.700 no `--long-take`) |

O maior custo de API é a leitura de posts do X — ajuste `X_MAX_POSTS` para equilibrar cobertura e preço. A auditoria e as cartelas somam ~US$ 0,10 por vídeo (pool maior de mídias na X API + uma chamada de visão por mídia do pool + a chamada da nota de pertinência): para cortar isso, baixe `MAX_POSTS_MIDIA`/`POOL_EXTRA_CLIPES` — mas lembre que sem pool a auditoria só tem como reprovar até o vídeo não sair. `MAX_CARTELAS=0` e `MAX_FOTOS=0` desligam a parte das cartelas sem mexer na auditoria dos clipes; `MAX_FIGURAS=0` desliga a geração de imagem e `X_MAX_POSTS_TIMELINE=0` desliga a leitura de timelines — as duas adições de 2026-07-30, que juntas somam ~US$ 0,45 por vídeo. O custo fixo segue sendo o plano da ElevenLabs: o gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana.

**Atenção ao ligar o `--long-take` num cron diário**: cada vídeo longo consome ~1.700 créditos de TTS, ou seja ~51k créditos/mês com uma execução por dia — sozinho já estoura o Starter. Some a isso a leitura de posts do X, que é cobrada por execução (~US$ 1,00 com `X_MAX_POSTS=200`): um cron de vídeo longo por dia custa ~US$ 30/mês só de X API. Se o longo rodar em horário próximo ao de um Short, considere baixar `X_MAX_POSTS` na execução longa.

## Problemas comuns

- **Erro na coleta de posts** — confira `X_CONSUMER_KEY`/`X_CONSUMER_SECRET` e o saldo/plano do app em [developer.x.com](https://developer.x.com).
- **Quer mudar as contas acompanhadas** — edite `CONTAS_PADRAO` em `pipeline/config.py`, ou preencha `X_ACCOUNTS` no `.env` para substituir a lista sem mexer no código.
- **Erro/429 na busca de notícias** — confira a `FIRECRAWL_API_KEY` e o saldo de créditos no [dashboard do Firecrawl](https://firecrawl.dev) (falha aqui não aborta: o roteiro segue sem as notícias).
- **Execução abortou sem clipe** — a trend escolhida precisa ter post com vídeo nativo; a seleção já filtra, mas o download ainda pode falhar (post apagado, todas as variantes acima de 60 MB). Desde 2026-08-05 isso derruba só a **candidata**, não a execução: o log mostra `[fallback] Tentativa 1/3 descartada` e outra trend é tentada. Abortar de vez exige as 3 falharem.
- **Execução abortou na auditoria** (`[fallback] ... a auditoria aprovou 0 clipe(s)` nas 3 tentativas) — todo o material das candidatas era de telejornal, tinha selo de emissora ou não mostrava o que a narração diz. Abrir o `auditoria_clipe.json` da pasta do vídeo mostra o motivo de cada reprovação. Se estiver reprovando demais, o caminho é **aumentar o pool** (`MAX_POSTS_MIDIA`, `POOL_EXTRA_CLIPES`), não afrouxar a regra — a alternativa é o vídeo voltar a mostrar material que não condiz com a narração. No `--long-take` o telejornal já não reprova (entra marcado como representação visual), então uma reprovação em massa ali é de **pertinência**: o material não mostra o que a narração diz.
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 3)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` (e `--auth-youtube-usa`) de novo para reautorizar com os escopos de leitura. Sem isso a execução aborta logo no início (a leitura alimenta a seleção guiada pela audiência).
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
