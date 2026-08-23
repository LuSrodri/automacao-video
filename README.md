# Automação de Vídeos

Pipeline em Python que transforma as trends mais quentes do X (Twitter) em um vídeo vertical narrado, em formato explicativo (análise/educacional), pronto para publicar.

> **Sem recorte temático** (decisão de **2026-08-16**, pedido do usuário: *"amplie para todos os temas possíveis"*). Qualquer assunto pode virar vídeo — tecnologia, IA, negócios, trabalho, mercado financeiro, ciência, saúde, política, mundo, esporte, cultura, crime, clima, consumo. Não há tema vetado nem tema obrigatório: o que decide a pauta é o **valor da informação** e, entre as candidatas, o que a **audiência do canal assiste até o fim**. Isso reverte o recorte de 2026-07-30, que tinha tirado guerra e geopolítica do canal, e o de tech/mercado que veio junto — os prompts, a lista de macrotemas e a auditoria pró-leigo foram todos limpos dos vetos por tema.

> **Idioma — o canal decide, nunca o modelo.** O canal brasileiro publica **tudo** em português (título, descrição, narração e **capa**); o canal americano (`-usa`), **tudo** em inglês. O idioma é dado do pipeline (`cfg.publico`), não coisa a deduzir do conteúdo: os prompts do roteiro (`FOCO_BRASIL`/`FOCO_USA`) e o da capa (`pipeline/thumbnail.py`) recebem a regra explícita, e a capa ainda é **conferida em código** depois da resposta, com uma segunda chamada cobrando a correção quando sai fora. Ver "Formato longo".

1. **Coleta** os posts da janela **de uma LISTA do X** (`/2/lists/{id}/tweets` do id em `X_LIST_ID`) via X API oficial v2, pay-per-use, com teto de leitura configurável: uma chamada paginada, **cronológica**, com os posts de todos os membros — ver "Como funciona a leitura da lista do X". O **GPT** então os sumariza nas **10 trends mais quentes**, ordenadas pelo **valor da informação** (vazamento, documento, exclusivo, urgência, número inédito) **antes** do engajamento, cada uma com resumo, `valor_informativo`, `urgencia`, engajamento, nota de apelo visual e **quantos posts têm clipe de vídeo nativo** (a mesma chamada da coleta já traz o tipo de mídia de cada post). O GPT devolve o **inventário completo** dos posts com vídeo de cada trend (`posts_video`) à parte da lista de posts mais centrais (`posts`, truncada): a contagem sai da união dos dois, senão uma pauta que **tem** clipe — só não entre os posts mais centrais — seria vetada como se não tivesse material. Os posts com vídeo vão para a frente da lista, que é onde o lookup de mídias corta. **A lista do X é o caminho único da pauta desde 2026-08-22**: o fallback pelas contas seguidas foi removido e falha de leitura aborta a execução.
2. **GPT 5.6 Luna** classifica cada candidata (**macrotema** + **imagem mental**) — sem filtro nem score: todas as candidatas seguem vivas para a seleção. Os macrotemas cobrem **todos os assuntos** desde 2026-08-16: `ia`, `criacoes-ia`, `dev-software`, `hardware-chips`, `bigtech-negocios`, `mercado-trabalho`, `mercado-financeiro`, `ciencia-espaco`, `saude-bem-estar`, `politica-sociedade`, `mundo-conflitos`, `crime-justica`, `clima-ambiente`, `esporte`, `cultura-entretenimento`, `consumo-cotidiano` e `outro`. A lista precisou crescer junto com o fim do recorte temático por um motivo mecânico: `outro` é o rótulo de descarte e **não entra no rodízio**, então uma lista só de rótulos de tecnologia empurraria metade das pautas novas para lá e o rodízio pararia de funcionar exatamente nos assuntos recém-admitidos. **`criacoes-ia` entrou em 2026-08-04**: é o oposto de `ia` — `ia` é a notícia sobre o **laboratório** (modelo lançado, benchmark, rodada), `criacoes-ia` é a notícia sobre **o que foi feito com a ferramenta** (vídeo, curta, música, imagem, personagem, jogo, app gerados por IA). É o macrotema que melhor casa com um formato montado só de clipes: a criação **é** o clipe. Além de rotular, o macrotema voltou a ter efeito de regra nos Shorts — ver o rodízio de temas no item 3.
3. **GPT 5.6 Luna** escolhe a trend guiado **somente pela audiência**: recebe os **últimos 100 vídeos publicados no canal selecionado com as métricas reais** (views/likes em tempo real, YouTube Data API) e a **régua de retenção** (YouTube Analytics), e escolhe a candidata com a maior chance de performar com esse público — repetir o tipo de conteúdo que está performando é bem-vindo, **sem cota de variedade**. Nos **Shorts** vale, desde 2026-08-04, um **rodízio de temas** aplicado em código antes da escolha: as candidatas do macrotema do Short anterior saem da disputa, de modo que **cada Short sai de um tema diferente do anterior** (o veto cede se zerar as candidatas — melhor repetir o tema do que não publicar). O formato longo não tem rodízio. As métricas chegam ao prompt **normalizadas pela idade** (**views por hora** ao lado das views acumuladas): views acumuladas medem há quanto tempo o vídeo está no ar tanto quanto medem qualidade, então o pico de um ciclo já encerrado continuaria sendo o maior número da lista por dias depois do assunto morrer. É o views/h que mostra o ciclo esfriando — vídeos recentes de um macrotema rendendo bem menos por hora que os antigos do mesmo macrotema — e faz o modelo trocar de assunto sozinho. **Retenção é a métrica que manda** (2026-08-16, pedido do usuário: *"sempre priorizando alto engajamento (versus swipe-away) de 70% ou mais"*; a régua media o gancho até a correção de 2026-08-17) — ver "Como funciona a régua de retenção". A candidata precisa se parecer com os campeões **no assunto**. Regras duras, aplicadas em código: **candidata sem nenhum post com clipe de vídeo sai da disputa** (o formato é montado só com clipes do X) e a **verificação anti-repetição** — o GPT confere se a escolhida cobriria o **mesmo fato** de um vídeo publicado nas últimas 36h sem desenvolvimento novo; se sim, ela sai da disputa e a seleção refaz (se todas as candidatas caírem em uma das regras, não há vídeo).
4. **Panorama do dia** (`pipeline/seo.py`, 2026-08-07): a **YouTube Data API** devolve os vídeos que **outros canais** publicaram sobre o mesmo assunto nas últimas `JANELA_HORAS` — títulos, canal, **views por hora** e as **tags** que eles usaram. É a única leitura do pipeline sobre a disputa **fora** do canal: os últimos publicados e a régua de retenção calibram o tom com o próprio público, mas não dizem nada sobre quem mais cobriu o fato hoje nem com que palavras. O panorama alimenta o título, a descrição, as **tags** e o texto da **capa** — ver "Como funcionam o SEO e o GEO". Falha aqui **só avisa**.
5. **GPT 5.6 Luna** escreve o roteiro **explicativo (análise/educacional) em tom adulto**, **sempre citando as fontes** (as contas do X que originaram a trend, e os veículos que elas citam): para um adulto leigo (o público real: homens de 25-54) com metade da atenção — frases com **ritmo de fala natural** (8 a 16 palavras, teto 20, alternando curtas de impacto com mais cheias), uma ideia por frase, **vocabulário preciso de telejornal** (sem jargão de nicho nem sigla sem explicação), tom de furo de notícia (nunca infantil), e a estrutura fixa em **cinco blocos: PERGUNTA ESQUISITA (0-2s) → CONTEXTUALIZAÇÃO → DESENVOLVIMENTO → CONSEQUÊNCIA → CONCLUSÃO** — a conclusão responde a pergunta da abertura de um jeito que **emenda de volta nela quando o Short reinicia** (loop) e carrega a **disputa** do assunto, sem CTA falado. Ver "Como funciona a estrutura em cinco blocos". O roteiro traz também o **comentário de abertura** que o pipeline posta no vídeo (ver "Como funciona a alavanca de share e comentário"). O **título e a descrição são autossuficientes** (teste do leigo: sem nome de nicho, sem cauda de suspense; a descrição entrega o fato com a fonte, não é teaser) e prometem **exatamente** o que o vídeo entrega. Uma **auditoria pró-leigo** (chamada própria ao GPT) confere título, descrição e narração contra essas regras e pede **uma reescrita** quando reprova. O roteiro inclui **audio tags** (`[excited]`, `[whispers]`…) que ditam o tom da voz. Desde 2026-08-07 ele devolve também as **tags de busca** do vídeo e a **resposta curta** que vai para a descrição no par `P:`/`R:` — ver "Como funcionam o SEO e o GEO".
6. **X API** baixa um **pool de clipes de vídeo** dos posts originais da trend (o MP4 de **maior bitrate que cabe no teto de 60 MB**: o X serve o mesmo clipe em várias resoluções, e a de cima às vezes é um 4K de 2,9 GB — descartá-la descartava o clipe inteiro, então o download **desce a lista de variantes** até uma caber) — mais do que os 3 que entram na montagem, como folga para a auditoria — junto com a **conta de origem** de cada clipe e as **fotos dos posts**, que alimentam as cartelas. **Imagem estática nunca ocupa a tela**, então não há busca de imagens na web.
7. **Auditoria do material visual** (`pipeline/auditoria.py`): o **GPT com visão** descreve e **classifica** cada clipe do pool (cena real, reportagem de TV, gravação de tela, cartela, logo…) e diz se há **selo de emissora ou veículo de imprensa** na imagem. Em cima disso: **veto duro em código** — material de telejornal, vinheta de logotipo e qualquer mídia com selo de emissora saem da disputa, assim como mídia que não recebeu laudo — e uma **nota de pertinência de 1 a 5** dada pelo GPT, que mede só uma coisa: o quanto aquilo que a mídia **mostra** é o que a narração **diz** (abaixo de 3 sai; material que mostra a manchete de um veículo em vez do fato tem teto 2). Desde 2026-08-07 há também o **veto por texto na tela**: clipe **tomado por texto** — e, mais ainda, por texto **parado** (slide, cartaz, print) — sai da montagem, **a não ser** que aquele texto seja o assunto que a narração descreve. **Zero clipe aprovado aborta a execução** (o formato longo exige um piso de 3). Roda **antes do ElevenLabs**, para a reprovação não custar créditos de narração, e deixa o rastro em `auditoria_clipe.json`.
8. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere), o pipeline **acelera a narração** conforme o formato (`VIDEO_VELOCIDADE`, 1.25x no Short; **1.0x, velocidade normal, no `--long-take`**) e **corta os silêncios**, deixando o áudio sem trechos parados. Os timestamps do alinhamento são reescalados nas duas etapas, então cortes, legendas, cartelas e figuras seguem sincronizados. O orçamento de palavras do roteiro é multiplicado pela velocidade — narração mais rápida cabe mais palavras nos mesmos segundos de tela. **Piso duro de duração, conferido aqui** (2026-08-04): Short abaixo de **21s** e vídeo longo abaixo de **120s** **abortam a execução sem publicar**. (O alvo do Short caiu de 60 para **25 segundos** em 2026-08-09, e o piso desceu junto — mantê-lo em 50 com alvo de 25 faria toda execução abortar depois de pagar a narração. A folga entre piso e alvo no orçamento de palavras virou **proporcional** na mesma mudança: era um valor absoluto de 7s, calibrado contra o alvo de 60, e sobre 25 segundos ele empurraria o piso de palavras para cima do teto.) A conferência é depois da narração, e não só na faixa de palavras do roteiro, porque **palavra não é segundo** — o ritmo real do TTS varia ~25% de narração para narração, e só depois de narrar e cortar os silêncios se sabe a duração de verdade. O roteirista já teve **3 tentativas** de acertar o tamanho antes disso; o que sobra aqui é um vídeo que não deveria ir ao ar. O teto **não** aborta (vídeo comprido é defeito de retenção, não de formato).
9. **Cartelas de imagem nos momentos-chave** (`pipeline/cartelas.py`): a **foto do post da trend** (que o pipeline já lia e descartava) **toma a tela inteira** por ~3,6s, no instante em que a narração **nomeia** o que ela mostra — a pessoa citada, o lugar atingido, o documento assinado. A imagem entra inteira sobre um fundo feito dela mesma, ampliada e borrada, com o **crédito próprio** numa faixa na base (`Reprodução: X / @conta` ou o domínio do veículo; `Image Credit` no `-usa`). Ela não é um cartão sobreposto: entra e sai pelo **deslize do carrossel** (ver "Como funciona a tela cheia e o carrossel"). As imagens passam pela **mesma auditoria dos clipes** (visão + veto duro + nota), o gancho fica limpo (nada entra nos 3 primeiros segundos) e nenhuma cartela cai em cima de uma figura gerada.
10. **Figuras geradas por IA** (`pipeline/figuras.py`): o **gpt-image-2** desenha **gráficos, tabelas, infográficos, diagramas e cartazes** a partir dos **números que a própria narração diz**, ancorados numa **citação literal** do trecho em que o dado é falado. Só entra dado que está na narração — a tela nunca mostra um número que ninguém falou. Cada figura **toma a tela inteira** pelo mesmo deslize das cartelas, etiquetada como **infográfico do canal** na faixa da base (para o espectador não confundir com material de terceiro). Desde 2026-08-04 são a **única fonte de "big number" na tela**: os infográficos animados que o ffmpeg montava a partir de PNGs do Pillow (`pipeline/grafico.py`) foram removidos a pedido do usuário, junto com o módulo. Ver "Como funcionam as figuras geradas".
11. **ffmpeg** monta o vídeo em **tela cheia** (ver "Como funciona a tela cheia e o carrossel"): o **fundo de cada momento é o próprio clipe daquele trecho, ampliado para cobrir o quadro e borrado**; por cima entra o **clipe nítido no maior tamanho que cabe nele, centrado** (clipe mais curto que a janela repete em loop). Os clipes **cobrem 100% da narração** (nunca há um instante sem imagem) com **crossfade curto e limpo** entre si. **Legendas** sincronizadas palavra a palavra — grandes, em **Archivo Black** branca com contorno preto, com entrada de "carimbo" editorial — são queimadas no vídeo, e o **crédito de reprodução** ("Reprodução Imagem: X" + "Conta `@usuario`" do post de origem; "Image Credit"/"Account" no modo `-usa`) fica no **canto superior direito do quadro** sobre uma tarja preta translúcida, trocando junto com o clipe e sumindo enquanto uma imagem ocupa a tela (ela traz o crédito dela). O vídeo **não tem música de fundo** (a trilha foi removida em 2026-07-30, junto com o arquivo `assets/trilha.mp3`): sobram a narração e os wooshes das transições — o formato virou análise, e música disputa atenção com a informação falada. A cauda após a narração é de **0,15s** — curta de propósito, para a CONCLUSÃO emendar na pergunta de abertura quando o Short reinicia (loop).
13. O `.mp4` final vai para `output/`, é registrado em `videos.txt` e publicado automaticamente no **YouTube** (Data API v3), com as **tags de busca** e com a **descrição montada** em `pipeline/seo.py` — parágrafo do payload, par `P:`/`R:`, capítulos (formato longo), fontes reais e as hashtags por último. Roda sempre, independente da flag `-usa` (o horário de publicação é o do cronjob que dispara a execução). Logo após o upload, o pipeline posta o **comentário de abertura** do dono no vídeo (`commentThreads.insert`, 50 unidades de cota) — ver "Como funciona a alavanca de share e comentário".

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH. No Windows: `winget install Gyan.FFmpeg` (reabra o terminal depois)
- O fundo é montado a partir dos próprios clipes (não há fundo de cor); a resolução (padrão vertical 9:16, `1080x1920`) é configurável por `VIDEO_LARGURA`/`VIDEO_ALTURA`.
- Chaves de API (três):
  - **OpenAI** — em [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (sumarização das trends, roteiro e descrição dos clipes com `gpt-5.6-luna`).
  - **X API** — Consumer Key + Secret do app em [developer.x.com](https://developer.x.com) (leitura da lista de pauta, coleta dos posts dela e download dos clipes; pay-per-use). Lista **privada** exige também as credenciais OAuth 2.0 de usuário — ver "Como funciona a leitura da lista do X".
  - **ElevenLabs** — em [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) (narração TTS).

## Configuração inicial (uma vez só)

```powershell
# 1. Crie o ambiente virtual e instale as dependências
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Crie o .env a partir do exemplo e preencha as chaves (e o X_LIST_ID)
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

Autorizações (uma vez só, não geram vídeo): `--auth-youtube` e `--auth-youtube-usa`.

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
mesmo pipeline — mesma coleta do X, mesma tela cheia, mesmo crédito de
reprodução no canto superior direito — com outra direção editorial:

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
- **Capa customizada** (`pipeline/thumbnail.py`): um quadro real do vídeo (2s)
  escurecido, com 2 a 5 palavras em Archivo Black na
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
- **Tela cheia**, igual ao Short: o clipe ocupa o quadro inteiro sobre o fundo
  borrado dele mesmo. O cenário de sala com TV que o formato longo teve entre
  2026-07-27 e 2026-08-09 — e a moldura de celular que o substituiu — saíram
  em 2026-08-16 (ver "Como funciona a tela cheia e o carrossel").
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
  janela com a **cadência do cron** — 4h para os Shorts, que rodam de 4 em 4
  horas, e 48h para quem roda segunda/quarta/sexta.

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
| `X_LIST_ID` | — | Id da **lista do X** de onde sai a pauta. **Obrigatório**: é o caminho único da coleta desde 2026-08-22 |
| `X_TOKEN_MARGEM_MIN` | `75` | Minutos de vida restante abaixo dos quais o cron renovador troca o access token do X. Precisa ser **maior que o intervalo do cron renovador**, senão o token vence entre dois ticks |
| `X_MAX_POSTS` | `200` | Teto de posts lidos por execução (a X API cobra por post lido) |
| `X_MAX_POSTS_BUSCA` | `30` (só `--long-take`) | Busca **aberta** por clipes do assunto, fora das contas do canal. Fontes **não curadas** — a auditoria é a única guarda, e ela julga pertinência, não veracidade; `0` desliga |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados. Alargar **não** custa mais na X API (o teto é o `X_MAX_POSTS`; a janela só decide de que intervalo saem esses posts). Case com a **cadência do cron**, não com o formato: em produção os Shorts rodam com `4` (**6 por dia** em cada canal, de 4 em 4 horas; entre 11/08 e 17/08 de 2026 foram 1 por dia, com janela `24`) e os crons `--long-take` com `48` — ver a nota abaixo |
| `NUM_TRENDS` | `10` | Quantas trends mais faladas do X coletar para escolher a do vídeo |
| `TEXT_MODEL` | `gpt-5.6-luna` | Modelo do roteiro, da sumarização das trends e da visão |
| `IMAGEM_MODEL` | `gpt-image-2` | Modelo das figuras geradas (gráficos, tabelas, infográficos, cartazes) |
| `IMAGEM_QUALIDADE` | `medium` | `low`/`medium`/`high`/`auto`. `medium` é o piso para figura com texto: em `low` o rótulo sai borrado |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `25` | Duração-alvo da narração em segundos (a duração final segue o áudio; o corte de silêncios tira ~10%). Caiu de 60 para 25 em 2026-08-09. **Piso duro de 21s**: Short mais curto que isso não é publicado, e valor abaixo de 21 aqui é recusado no carregamento |
| `VIDEO_VELOCIDADE` | `1.25` | Velocidade da narração e, com ela, do ritmo do vídeo inteiro. O **Short roda acelerado**; o `--long-take` roda em `1.0` (`LONG_VELOCIDADE`). O orçamento de palavras do roteiro é multiplicado por este valor |
| `VIDEO_LARGURA` | `1080` | Largura do vídeo |
| `VIDEO_ALTURA` | `1920` | Altura do vídeo |
| `MAX_POSTS_MIDIA` | `12` | Posts da trend consultados no lookup de mídias (a X API cobra por post lido) |
| `POOL_EXTRA_CLIPES` | `3` | Clipes baixados além dos que entram na montagem, como folga da auditoria |
| `MAX_FOTOS` | `4` | Fotos dos posts baixadas para as cartelas (`0` desliga) |
| `MAX_CARTELAS` | `1` | Cartelas de imagem nos momentos-chave, que tomam a tela inteira pelo deslize do carrossel (`0` desliga). Caiu de 2 para 1 com o Short de 25s: cada imagem tira ~4s de clipe da tela |
| `MAX_FIGURAS` | `1` | Figuras **geradas** pelo gpt-image-2 a partir dos números da narração — única fonte de "big number" na tela (`0` desliga). Caiu de 2 para 1 pelo mesmo motivo |
| `VETO_TEXTO_DENSO` | `1` | Barra o clipe **tomado por texto** (e, mais ainda, por texto **parado**) quando ele não é o assunto que a narração descreve. `0` aceita de volta o fundo de slide/print atrás das legendas queimadas |
| `VETO_CLIPE_PARADO` | `1` | Barra o clipe **estático** (o mesmo quadro do começo ao fim) e o de **pessoa falando para a câmera** (entrevista, podcast, coletiva, âncora). Veto duro, sem exceção de contexto nem de formato. `0` aceita de volta o busto falante e a foto com áudio |
| `LONG_DURACAO` | `135` | Só com `--long-take`: duração-alvo da narração (aceita 120 a 150; **abaixo de 120s o vídeo não sai**) |
| `LONG_LARGURA` / `LONG_ALTURA` | `1920` / `1080` | Só com `--long-take`: resolução 16:9 |
| `LONG_MAX_CLIPES` | `8` | Só com `--long-take`: clipes do X usados na montagem |
| `LONG_MAX_POSTS_MIDIA` | `16` | Só com `--long-take`: posts da trend consultados para achar os clipes |
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
| `SEO_PANORAMA` | `1` | Lê da YouTube Data API os vídeos que **outros canais** publicaram hoje sobre o mesmo assunto, para calibrar título, descrição, tags e capa. Uma busca por execução, no balde de **Search Queries** (100/dia), fora da cota de 10.000 unidades. `0` desliga — ver "Como funcionam o SEO e o GEO" |
| `SEO_MAX_VIDEOS` | `20` | Vídeos do dia lidos por execução (teto da API: 50). Acima de ~20 o bloco vira ruído no prompt |

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

O pipeline é **fail-fast**: credenciais ausentes/quebradas, falha ao ler os últimos vídeos ou a régua de retenção, classificação indisponível, verificação de vídeo repetido indisponível e falha no upload — tudo isso derruba a execução com erro explícito (para o agendador poder alertar), em vez de seguir e degradar o vídeo em silêncio. As leituras do canal acontecem logo no início, antes de qualquer chamada paga (X/OpenAI). Os clipes são obrigatórios: se nenhum clipe dos posts da trend puder ser baixado, a execução aborta (o formato não admite imagem estática). Se o upload falhar, o vídeo continua salvo em `output/` e registrado em `videos.txt` para publicação manual.

## Publicação no TikTok (removida em 2026-08-16)

Entre **2026-08-06 e 2026-08-16** o mesmo arquivo que ia para o YouTube era publicado também no TikTok (`@lusrodri`), na mesma execução e com custo adicional zero, passando pelo [Zernio](https://zernio.com) — um cliente já auditado pelo TikTok, que é o que permitia postar **público** sem submeter este pipeline à auditoria da plataforma.

**Saiu inteiro a pedido do usuário**: o módulo `pipeline/zernio.py`, a chamada no `main.py`, os campos de `Config` e as variáveis `TIKTOK_PUBLICAR`, `ZERNIO_API_KEY`, `ZERNIO_ACCOUNT_ID`, `TIKTOK_USUARIO`, `TIKTOK_PRIVACY` e `TIKTOK_AIGC` (também apagadas dos cron jobs do Render). **O YouTube é o único destino do vídeo.** Não reintroduzir sem pedido explícito.

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

## Como funcionam o SEO e o GEO

Diretriz de **2026-08-07**. Até aqui o pipeline escolhia título, descrição e capa olhando **só para dentro do canal**: os últimos publicados com as métricas reais e a régua de retenção. Isso calibra o **tom** — o tipo de título que este público clica — mas não diz nada sobre a **disputa**: quem mais cobriu o fato hoje, com que palavras, e o que está subindo rápido. E havia um buraco: `main.py` sempre publicou com `tags=roteiro.get("tags")`, mas o esquema do roteiro **nunca teve esse campo** — ou seja, **todo vídeo do canal subiu com a lista de tags vazia**.

**1. Panorama do dia** (`pipeline/seo.py`). Depois de escolher a pauta, a seleção devolve também uma `consulta_youtube` — 2 a 5 palavras **no idioma do canal**, do jeito que um espectador digitaria na busca (diferente da `consulta_clipes`, que é em inglês e em linguagem de agência). Com ela, `search.list` + `videos.list` trazem os vídeos publicados sobre o assunto nas últimas `JANELA_HORAS`, ordenados por **views/hora**, com o **vocabulário de tags** que eles usaram.

> **Custo:** uma busca por execução. Ela **não** gasta da cota de 10.000 unidades/dia do projeto (onde o upload consome 1.600) — cai no balde separado de **Search Queries**, com teto de **100 buscas/dia**. O `videos.list` que completa os dados custa 1 unidade.

O panorama **falha aberta**, ao contrário de `ultimos_publicados`/`top_retencao`: aqueles são a **régua da seleção** e abortam quando falham (sem eles a pauta é escolhida às cegas); este é **contexto de redação**, e perdê-lo devolve exatamente o comportamento anterior a 2026-08-07 — que já publicava vídeo. `SEO_PANORAMA=0` desliga.

**2. O que o panorama muda.** Ele entra no material do roteirista ao lado da régua interna, e alimenta:

- **Tags** (campo `tags`, novo): 8 a 15 termos de busca, no idioma do canal. É o **único** campo de metadados em que cabe o nome próprio que o título proíbe — tag não é lida pelo espectador, então o teste do leigo não se aplica ali, e é por "H200", "Claude 4.5" ou "layoff" que procura quem **já** conhece o assunto. O saneamento é feito **em código** (`seo.limpar_tags`), porque o limite que importa é o da API: o YouTube recusa o **upload inteiro** quando a soma das tags passa de 500 caracteres, e um vídeo já pago não pode morrer numa tag a mais.
- **Título e descrição**: as palavras com que o público está procurando o fato (busca casa por palavra — chamar o fato por um nome que ninguém digita é sumir dele) e, no sentido oposto, o **ângulo que ainda não foi ocupado**: se cinco títulos dizem a mesma coisa, o nosso diz o que os cinco deixaram de fora.
- **Capa** (`thumbnail.py`, formato longo): o modelo recebe os títulos concorrentes do dia e escolhe **outro fato verdadeiro** do mesmo vídeo. A regra de dizer o fato continua acima de tudo — diferenciar nunca é inventar.

**3. GEO — a parte de *Generative Engine Optimization*.** Motor de resposta generativo cita trecho **autossuficiente**: uma frase que já traz a entidade, o número, a data e de quem veio. O parágrafo escrito para gente não serve, porque depende do vídeo ("isso significa que…"). Então o roteiro devolve um campo `resposta_curta` — uma frase, até 30 palavras, que responde a pergunta de abertura e se sustenta sozinha fora do vídeo — e a descrição a publica num par `P:`/`R:` (`Q:`/`A:` no canal americano). O teste, no prompt: se começa com "isso", "ele" ou "a empresa", não passou.

**4. A descrição publicada** deixa de ser só o parágrafo do roteirista e passa a ser montada em `seo.montar_descricao`, nesta ordem:

```
parágrafo do payload        <- os ~150 primeiros caracteres são o que aparece na busca
P: pergunta / R: resposta   <- GEO: o trecho citável
Capítulos (formato longo)   <- vira "momentos principais" no YouTube
Fontes (formato longo)      <- posts do X e veículos que a narração citou
#hashtags                   <- sempre por último
```

As hashtags vão para o fim **em código**: o modelo as escreve grudadas no parágrafo, e ali elas empurrariam o resto para fora dos primeiros caracteres.

**5. Capítulos (só no `--long-take`).** Cada tópico do roteiro passa a trazer uma **citação literal** do ponto da narração em que ele começa — o mesmo mecanismo das cartelas e das figuras —, e o alinhamento do ElevenLabs a converte em carimbo de tempo. Capítulo com carimbo chutado seria **pior** que capítulo nenhum: ele promete um ponto do vídeo que não existe. Por isso o bloco só sai quando é **válido** pelas regras do YouTube (primeiro carimbo em `0:00`, no mínimo 3 capítulos, trechos de pelo menos 10s); citação que não bate no texto é descartada com aviso, e bloco incompleto simplesmente não é publicado.

## Infográficos animados (removidos em 2026-08-04)

Até 2026-08-04 o pipeline montava, além das figuras geradas, **infográficos animados** próprios: `pipeline/grafico.py` renderizava com Pillow **contadores** que subiam do zero e **barras comparativas**, e o ffmpeg os sobrepunha no terço superior do vídeo. Eles foram **removidos a pedido do usuário**, junto com o módulo — os "big numbers" da tela passam a vir **só das figuras do gpt-image-2** (`pipeline/figuras.py`), que já cobrem o mesmo repertório com uma identidade visual única em vez de duas.

Com eles saiu também a regra que **escondia o crédito de reprodução** enquanto um infográfico estava na tela: o crédito sumia porque o painel ocupava o terço superior, e cartelas e figuras ficam no **miolo** da tela, onde nunca encostaram nele.

## Como funcionam os clipes e os cortes

O pipeline baixa um **pool** de clipes de vídeo dos posts originais da trend (X API, MP4 de maior bitrate): **3 + `POOL_EXTRA_CLIPES`** entram na disputa por 3 vagas na montagem (**8 vagas no `--long-take`**). O **GPT com visão** descreve e classifica cada um a partir de frames extraídos pelo ffmpeg, a **auditoria** derruba o que não presta (veja abaixo) e um "editor de cortes" (GPT) decide **quando cada clipe aprovado entra**, ancorando cada corte numa **citação exata da narração** (convertida em tempo pelos timestamps do ElevenLabs) — o primeiro clipe abre o gancho, e clipe mais curto que a janela repete em **loop**. Na tela, cada clipe carrega o próprio **crédito de reprodução** no canto superior direito ("Reprodução Imagem: X" + "Conta `@usuario`" do post de onde ele veio). O plano fica em `cortes.json`; se ele falhar, os clipes aprovados são distribuídos uniformemente pela narração, **na ordem da nota da auditoria** (o melhor abre o vídeo).

## Como funciona a auditoria do material visual

O que motivou a camada: até então nada filtrava os clipes. O pipeline usava os **primeiros** que a X API devolvesse, e o planejador de cortes até era instruído a omitir clipe fora do assunto — mas quando ele omitia, o plano era reprovado e o fallback usava **todos** os clipes baixados de volta. O caminho do descarte levava ao uso, e vídeo de telejornal ou cena sem relação com a narração entrava.

Agora `pipeline/auditoria.py` roda sobre o pool, em quatro etapas:

1. **Veto duro, em código** — a mesma chamada de visão que descreve a mídia também a **classifica** (`cena_real`, `reportagem_tv`, `estudio_ou_podcast`, `gravacao_de_tela`, `cartela_ou_manchete`, `logo_ou_marca`) e diz se há **selo de emissora ou veículo de imprensa** na imagem. Sai da disputa: material de telejornal, vinheta de logotipo, qualquer mídia com selo de emissora e qualquer mídia **sem laudo de visão**. É regra fixa de propósito: o problema é recorrente, e julgamento de LLM sobre "isso é jornalismo de terceiro?" oscila de execução para execução.
2. **Nota de pertinência (1 a 5)** — uma chamada ao GPT compara o que cada mídia **mostra** com o que a narração **diz**. Abaixo de 3 a mídia sai. A escala separa três coisas que já foram confundidas e custaram execução:
   - **3 = imagem real do acontecimento coberto**, mesmo sem dar para identificar o objeto. Um clarão no céu noturno, num vídeo sobre aquela guerra, é registro do conflito — B-roll legítimo, não material "ilegível". Era exatamente isto que vinha sendo reprovado por um teto de indecifrabilidade.
   - **2 = genérico de arquivo.** O teste: trocando o assunto do vídeo, a imagem continuaria servindo? Se sim, é 2 (paisagem urbana qualquer, sala de servidores qualquer).
   - **1 = contradiz a narração** — ataque acontecendo enquanto a narração fala em trégua, outro número/pessoa/data no texto da tela. É o pior caso: material irrelevante só não ajuda, material contraditório desmente o próprio vídeo.

   Teto de **cobertura de imprensa** (máx. 2) só pega o que é *só rótulo*: cartela de manchete parada, print de site, chamada de estúdio e nada mais. Telejornal que exibe **imagens do fato** é julgado por essas imagens na escala normal — senão o material que o veto duro passou a admitir no `--long-take` voltaria a morrer aqui, pela nota. Esta etapa **falha aberta** (aviso no log e todos passam): o veto duro já carrega a regra do canal, e derrubar o vídeo por um erro transitório da OpenAI desperdiçaria tudo que veio antes.

3. **Veto por falta de movimento (2026-08-09)** — pedido direto: *"adicione no veto vídeos estáticos ou de pessoas falando"*. Dois casos saem da disputa: o clipe **estático** (os frames são o mesmo quadro — foto com áudio, slide, tela congelada) e o clipe de **pessoa falando para a câmera** (entrevista, podcast, coletiva, depoimento, âncora, selfie-vídeo), incluindo o tipo `estudio_ou_podcast` inteiro. Os dois falham pelo mesmo motivo: o vídeo é montado **sobre movimento** — o clipe é o que prova o fato enquanto a narração o conta —, e um quadro que não muda ou um busto que só mexe a boca ocupam a tela sem mostrar nada.

   Diferente do veto por texto, este é **duro e sem exceção de contexto**: o problema é o que o material **é**, não a relação dele com a narração. Quem mede é a visão (`cena_estatica`, `pessoa_falando`), quem veta é o código (`_veto_parado`). Vale só para os **clipes** — as cartelas passam com `vetar_parado=False`, porque imagem parada e rosto de quem foi nomeado são exatamente o material que aquela camada existe para mostrar. **Consequência no `--long-take`**: este veto roda **antes** da marcação de representação visual, então telejornal só continua entrando quando é **VT com imagens do fato**; âncora ou repórter falando em quadro cai aqui. `VETO_CLIPE_PARADO=0` desliga.

4. **Veto por texto na tela (2026-08-07)** — pedido direto: *"evitar vídeos de fundo que tenham muitos textos ou textos estáticos, a menos que seja dentro do contexto"*. O clipe do X entra como **fundo** de um vídeo que já é cheio de camadas: legendas grandes queimadas, cartelas, figuras geradas e o crédito de reprodução. Um clipe que **também** é texto empilha duas leituras concorrentes na mesma tela, e o espectador não faz nenhuma das duas. Texto **parado** é o caso pior — ele não passa, fica ali os segundos inteiros do corte, competindo com a legenda que está tentando ser lida.

   A exceção ("dentro do contexto") **não dá para decidir em código**, porque é semântica: o print do post que a narração está citando, a tela do app de que ela fala, o gráfico com o número que ela diz — nesses o texto **é** o assunto, e tirá-lo tiraria a prova do que está sendo narrado. Então a decisão é dividida em três responsabilidades:

   | Quem | O que decide | Campo |
   | --- | --- | --- |
   | **Visão** (`midia_x.py`) | quanto da tela é texto, e se ele fica parado | `densidade_texto` (`nenhum`/`pouco`/`moderado`/`muito`), `texto_estatico` |
   | **Auditor** (que lê a narração) | se aquele texto é o assunto narrado | `texto_pertinente` |
   | **Código** (`auditoria.py`) | a regra que junta as duas coisas | `_veto_texto` |

   A regra: densidade **`muito`** barra sozinha; **`moderado` com texto parado** também barra; `texto_pertinente = true` salva os dois casos. Se a chamada de pertinência falhar, o veto **encolhe** para o único caso que dispensa contexto — tela tomada por texto **parado** —, porque aí nenhuma leitura da narração salvaria o clipe. O veto vale só para os **clipes**, que ficam em tela cheia; as **cartelas** passam com `vetar_texto=False` (são um cartão pequeno e emoldurado, e o print do post citado é justamente o material que aquela camada existe para mostrar). No desempate entre clipes de mesma nota, ganha o de **tela mais limpa**. `VETO_TEXTO_DENSO=0` desliga.

A auditoria roda **antes do ElevenLabs**, então reprovar não custa crédito de narração. Ficar abaixo do piso de clipes aprovados (1 no Short, 3 no `--long-take`) **não aborta mais a execução**: desde 2026-08-05 a candidata sai da disputa e o pipeline **tenta outra trend** — ver "Como funciona o fallback de tema". A mensagem aponta o `auditoria_clipe.json` da pasta, que lista aprovados e reprovados com nota e motivo. As imagens das cartelas passam pela mesma peneira (`auditoria_imagem.json`).

## Como funciona o fallback de tema

A trend é escolhida por um sinal **indireto** de material: quantos posts dela têm clipe de vídeo nativo. O sinal erra dos dois lados — o clipe pode não baixar (post apagado, arquivo acima do teto) e a auditoria pode reprovar tudo que baixou. Quando isso acontecia, a execução inteira morria com `exit 1` **com a coleta e a classificação já pagas** e outras candidatas ainda vivas na lista.

Desde **2026-08-05**, a candidata que não rende material sai da disputa e o pipeline refaz os passos 4 a 7 com a **próxima trend**, até `TENTATIVAS_TREND` (3) candidatas por execução. As duas falhas cobertas são: **nenhum clipe baixado** e **auditoria abaixo do piso**.

O laço fecha **antes do TTS** de propósito. Cada tentativa extra custa notícias + roteiro + visão, e **nenhuma custa narração** — que é o crédito caro. Por isso o **piso de duração continua abortando seco**: narração curta é defeito do roteiro, e trocar de tema não conserta isso, só paga o ElevenLabs de novo. Se as 3 candidatas falharem, aí sim a execução aborta, e as alavancas são as de sempre: alargar `JANELA_HORAS`, subir `X_MAX_POSTS` ou revisar as contas acompanhadas.

**Exceção do `--long-take`: telejornal entra marcado, não vetado.** No formato longo, material de tipo `reportagem_tv` e mídia com selo de emissora deixam de cair no veto duro e entram **marcados como representação visual** — o clipe vai para a tela **dessaturado**, com a etiqueta `REPRESENTAÇÃO VISUAL` (`ILLUSTRATIVE FOOTAGE` no `-usa`) no rodapé esquerdo, enquanto os outros clipes da mesma montagem seguem coloridos e sem etiqueta. O motivo: 120 a 150 segundos de tela raramente se sustentam só com cena crua, e a marcação resolve o que originou o veto — o espectador tomar cobertura de terceiro por material do canal. `logo_ou_marca` continua vetado nos dois formatos (vinheta de logotipo não representa assunto nenhum), a nota de pertinência continua valendo para todo mundo, e no formato curto **nada muda**. O `auditoria_clipe.json` marca cada aprovada com `representacao_visual`.

## Como funcionam as cartelas de imagem

Uma das duas camadas de imagem, ao lado das figuras geradas: nos **momentos-chave** — quando a narração **nomeia** a pessoa, o lugar, o documento ou o produto — uma imagem **toma a tela do celular** por ~3,6s, entrando pelo deslize do carrossel. O corpo do vídeo continua sendo só clipe de vídeo do X.

- **De onde vêm** — as **fotos dos posts da trend**, que o pipeline já lia da X API e descartava no filtro de tipo: são o material mais barato (vêm no mesmo lookup) e estão no assunto por construção. Nenhuma chamada nova de API, e nada de busca de imagem em banco. Até 2026-08-16 a **og:image das notícias** do Firecrawl completava o pool; com a busca de notícias removida, sobraram só as fotos do X.
- **Como aparecem** — renderizadas no **tamanho exato do quadro**: a imagem entra inteira (nada de recorte que corte rosto ou número) sobre um fundo feito dela mesma, ampliado, borrado e escurecido — o mesmo tratamento que o clipe já recebe —, com o **crédito próprio numa faixa na base** (`Reprodução: X / @conta` ou `Reprodução: reuters.com`; `Image Credit` no `-usa`). O movimento é o **deslize** (ver "Como funciona a tela cheia e o carrossel"); este módulo só desenha o quadro parado. Substituiu em 2026-08-09 o cartão branco com sombra que subia de baixo do quadro — com a imagem ocupando a tela inteira, o problema de "cartão pequeno perde a disputa pela atenção", que em 2026-08-04 tinha sido tratado aumentando o cartão, deixou de existir.
- **Onde não aparecem** — nos **3 primeiros segundos** (o gancho fica com o clipe limpo) e em cima de uma figura gerada (as janelas nunca coincidem).
- **Quantas** — até `MAX_CARTELAS` (1; 4 no `--long-take`), escolhidas pelo GPT entre as imagens aprovadas na auditoria, com o momento ancorado numa **citação exata da narração**. O plano fica em `cartelas.json`. `MAX_CARTELAS=0` desliga a feature; qualquer falha só deixa o vídeo sem cartelas.

## Como funcionam as figuras geradas

O `pipeline/figuras.py` desenha, com o **gpt-image-2**, todo o repertório de infografia do canal: **gráfico de barras, gráfico de linha, tabela, infográfico de pictogramas, diagrama de causa e efeito e cartaz de um número só**. Desde 2026-08-04 é a **única** camada de "big number" do vídeo — os infográficos animados que o Pillow desenhava e o ffmpeg sobrepunha (`pipeline/grafico.py`) foram removidos a pedido do usuário, com o módulo junto.

- **De onde vêm os dados** — **exclusivamente da narração**. Um GPT lê o texto narrado e devolve, para cada figura, a **citação literal** do trecho em que o dado é dito, o **tipo** de figura, o título e os pares rótulo/valor. Número que está nas notícias mas não foi falado **não** entra: a tela mostrando um valor que ninguém disse é o pior defeito possível nesta camada.
- **Como são desenhadas** — o estilo visual é **fixo em código** (fundo branco, tipografia grotesca pesada, preto quase puro + um único laranja de destaque, sem 3D, sem sombra, sem marca d'água), porque identidade visual não pode variar de vídeo para vídeo. O prompt lista os rótulos exatos e proíbe qualquer texto além deles — o modelo ainda erra tipografia quando o cartaz é cheio, e figura enxuta é figura legível.
- **Como aparecem** — na **tela inteira**, pelo mesmo deslize das cartelas, etiquetadas como **infográfico do canal** (`CHANNEL GRAPHIC` no `-usa`) na faixa da base, para o espectador não confundir com gráfico publicado por terceiro — do mesmo jeito que o crédito de reprodução distingue o clipe de terceiro. Ficam ~4s na tela. Aqui a mudança de 2026-08-09 pesa mais que nas cartelas: a figura carrega **texto** (rótulo, valor, título), e o cartão que ela ocupava — mesmo aumentado em 2026-08-04 — deixava o rótulo pequeno demais para ser lido no celular, o que anulava a razão de a figura existir. A orientação pedida ao gpt-image-2 acompanha o **quadro** (retrato no Short 9:16, paisagem no `--long-take` 16:9).
- **Em que idioma** — no **idioma do CANAL** (`cfg.publico`), como todo o resto: título, rótulos e valores em português no canal brasileiro e em inglês no americano, com a notação de cada um (`21 mil` / `US$ 2 bi` contra `21K` / `$2B`). O idioma entra **explícito** na instrução e nos exemplos do esquema, e o texto devolvido é **conferido em código** (`config.idioma_plausivel`): uma reescrita é cobrada, e a figura que continuar no idioma errado é **descartada** — texto errado aqui sai queimado na imagem e não tem conserto depois de publicado. Até 2026-08-05 este era o último lugar do pipeline que **inferia** o idioma ("no idioma da narração", com exemplos em português dentro de um prompt em português), o mesmo sinal fraco que já tinha posto uma capa em português no canal americano.
- **Onde não aparecem** — nos 3 primeiros segundos (gancho limpo) e em cima de uma cartela (as janelas nunca coincidem).
- **Quantas** — até `MAX_FIGURAS` (1; 4 no `--long-take`). O plano fica em `figuras.json`. A ancoragem na narração é conferida **antes** da geração da imagem, que é a única etapa cara aqui. `MAX_FIGURAS=0` desliga; qualquer falha só deixa o vídeo sem figuras.

O roteirista sabe dessa camada: o prompt pede que **todo número, comparação e lista curta seja dito na narração, com valor e unidade** — dado não falado não vira figura —, e ao mesmo tempo mantém a proibição de referenciar a tela ("como você vê no gráfico"), porque a narração tem que se sustentar de olhos fechados.

## Como funciona a tela cheia e o carrossel

Pedido do usuário em **2026-08-16**: *"volte para o formato fullscreen com o preenchimento de background em blur"*. O conteúdo voltou a ocupar o **quadro inteiro**, e saíram os dois cenários que embrulharam o vídeo antes dele: a **moldura de celular sobre uma cama** (2026-08-09 a 2026-08-16, nos dois formatos) e, antes dela, a **sala de estar com TV** (2026-07-27, só no `--long-take`). Foram apagados junto o módulo `pipeline/cenario.py` e a foto `fundo-cama.png`. **Não reintroduzir cenário nenhum sem pedido explícito.**

**O preenchimento em blur.** O fundo de cada momento é o **próprio clipe daquele trecho**: escalado por cobertura (`force_original_aspect_ratio=increase` + `crop`), borrado (`gblur`, sigma 18) e levemente escurecido. Por cima entra o **clipe nítido no maior tamanho que cabe no quadro** (`decrease`), centrado. É isso que mantém a tela **sempre preenchida** quando o clipe não tem a proporção do quadro — o clipe 16:9 num Short 9:16 ganha a faixa borrada em cima e embaixo, em vez de barra preta.

**A orientação do material deixou de importar.** Entre 2026-08-10 e 2026-08-16, `orientacao_dominante` media cada clipe com o ffprobe (respeitando a matriz de rotação dos vídeos de celular) e pesava pelo tempo de tela para decidir se o aparelho ficava em pé ou deitado. Sem moldura não há o que orientar, então a função saiu — o clipe simplesmente cabe no quadro com o fundo borrado preenchendo o resto, como era antes das molduras.

**A área útil voltou a ser o quadro.** Legendas, cartelas, figuras e o crédito de reprodução são todos medidos contra ele. Sumiram com isso o retângulo intermediário (`retangulo_tela`), a área de legenda alternativa que descia para a cama quando o aparelho ficava deitado (`area_legenda`) e os **pisos de corpo** de fonte que existiam só porque a tela deitada de 438px entregava um crédito ilegível num quadro de 1080 (`CREDITO_FONTE_PISO_FRAC`, `REPR_FONTE_PISO_FRAC`).

**O carrossel de duas posições continua** — o usuário pediu para mantê-lo quando a mão saiu, em 2026-08-10, e ele sobreviveu à volta da tela cheia. O clipe está na posição 0 e a imagem do momento na posição 1, à direita, fora do quadro. Um único **deslocamento** `s(t)` — 0 com o vídeo na tela, 1 com a imagem — move as duas coisas: o clipe sai para `−largura · s` e a imagem entra em `largura · (1 − s)`. Como o offset é o mesmo, a borda de uma encosta na da outra durante todo o deslize, sem rasgo nem preto no meio. O que era recortado pelo corpo do aparelho agora é recortado pela **borda do próprio quadro**, sem máscara nenhuma no ffmpeg.

`s(t)` é uma **expressão de tempo do ffmpeg**, não uma sequência de PNGs: `overlay` avalia `x` por quadro, então a rampa (`_expr_progresso`, com *smoothstep* nas pontas) é montada em texto a partir das janelas das cartelas — sobe em `T_ARRASTO` (0,42s), fica em 1 enquanto a imagem é lida, e desce em `T_ARRASTO` no fim da janela. Os intervalos são **semiabertos** (`gte`/`lt`) para que dois termos nunca valham na mesma fronteira e a soma passe de 1.

**A mão saiu** em **2026-08-10** (*"remova a mão e o toque, mas pode manter a animação de deslizar"*). Era uma silhueta desenhada em Pillow que subia de fora do quadro antes de cada arrasto e descia depois. Não reintroduzir sem pedido explícito.

**Janela mínima.** Uma imagem precisa de `MIN_JANELA_CARROSSEL` (1,84s = os dois deslizes de 0,42s mais 1,0s de leitura com a imagem parada); abaixo disso ela entraria e já sairia, sem ninguém ler o que mostra. `DUR_MINIMA` das cartelas (2,2s) e das figuras (2,6s) já fica acima, e a montagem descarta com aviso o que chegar menor.

**O que saiu junto, lá atrás.** Com a imagem ocupando a tela inteira (2026-08-09), o **desfoque do que ficava atrás das cartelas** (`CARTELA_BLUR_SIGMA`/`CARTELA_BLUR_RAMPA`) perdeu função e foi removido: não há mais nada atrás para tirar de foco. As cartelas e as figuras deixaram de ser **sequências de PNG** e passaram a ser **um PNG só** cada.

## Como funciona a leitura da lista do X

A pauta sai de **uma lista do X** (`X_LIST_ID`), lida em `/2/lists/{id}/tweets`: uma chamada paginada, **cronológica**, com os posts de todos os membros. **Pôr ou tirar alguém da lista é a forma de mexer na pauta do canal** — vale já na execução seguinte, sem commit nem deploy.

Antes disso a coleta lia as **contas seguidas** (`/2/users/:id/following`) por `search/recent` com `from:` em lotes. O problema era mecânico: 162 contas não cabem numa query de 512 caracteres, viravam 7 lotes, e o teto de leitura era **repartido** entre eles — 28 posts para 25 contas, escolhidos por **relevância**. O efeito medido em 2026-08-17: `@sentdefender` publicou 12 vezes em 24h e apareceu **zero** vez na coleta. A lista não tem nada disso.

- **Paginação** — de 100 em 100 até `X_MAX_POSTS`, parando no primeiro post mais velho que a janela (como a ordem é cronológica reversa, o resto também será).
- **Janela** — a lista **não** aceita `start_time`; o corte é feito no cliente. Quando a janela devolve pouco (ou nada com clipe), ela **reabre por etapas** — 8h, 12h, 24h, 48h — sobre a mesma lista.
- **Autenticação** — lista **privada** exige contexto de usuário. O access token OAuth 2.0 é distribuído por um cron dedicado (`--renovar-x-token`), que o grava junto com o **vencimento** nas env vars do próprio serviço; os crons de vídeo leem de lá pela API do Render, em tempo de execução, e **não renovam nada** (com quatro crons renovando por conta própria, quem renovasse por último invalidava o refresh dos outros — o token é de uso único).
- **Renovação por idade, não por morte** (2026-08-22) — o renovador trocava o token só depois que ele **morria**: testava `/2/users/me` e, com 200, não fazia nada. Como o token vale 2h e o cron roda de hora em hora, a troca saía de 3 em 3 horas e sobrava uma **janela morta de até uma hora** em cada ciclo. Medido em 22/08: renovações às 00:20, 03:20, 06:20… e **401 na leitura da lista em exatamente as quatro execuções de vídeo que caíam nessas janelas** (US 03:02, BR 06:03, US 15:04, BR 18:04) — 4 das 12 do dia. Agora o vencimento é gravado junto com o token e a troca acontece com `X_TOKEN_MARGEM_MIN` minutos de vida ainda pela frente. A margem tem que ser **maior que o intervalo do cron renovador**; o `/2/users/me` ficou como conferência para o caso de token revogado antes da hora.
- **Sem rede debaixo** — falha de leitura **aborta**. O fallback pelas contas seguidas foi removido em 2026-08-22 porque era ele que fazia o 401 acima passar despercebido: o vídeo saía com a pauta ordenada por relevância, e nos logs isso aparecia como um aviso no meio de uma execução bem-sucedida. Página que quebra no **meio** da paginação ainda aproveita o que já veio.
- **Veto de fonte** — `CONTAS_VETADAS` continua valendo, agora aplicado sobre os posts da lista.

## Como funciona a régua de retenção

Pedido do usuário em **2026-08-16**: *"postar conforme os melhores vídeos do canal, sempre priorizando alto engajamento (versus swipe-away) de 70% ou mais"*.

São **duas** métricas, e confundi-las foi a origem de todos os bugs desta régua:

- **Retenção** (`averageViewPercentage`): quanto do vídeo quem abriu assistiu. **Passa de 100% quando o espectador reassiste** — o efeito do roteiro em loop discreto. O piso é **acima de 100%**.
- **Engajamento** ("Continuaram assistindo" vs "Pularam o vídeo", no Studio): a fração de quem não deslizou. O alvo do usuário é 70%, mas **esse número não existe na Analytics API** — ver abaixo.

### A correção de 2026-08-17

Até aqui o piso era aplicado sobre o **gancho** (`engagedViews / views`). Medido contra a API real, isso deixava a régua **patológica** — ela descartava os sucessos do canal:

| | canal BR | canal US |
|---|---|---|
| gancho **máximo** de todo o catálogo | 72,1% | **66,7%** |
| vídeos com gancho ≥70% | **1** (com 183 views) | **0** |
| vídeos com retenção ≥70% | 70 | 77 |
| … destes, com 20k+ views | 7 | 0 |

Os hits reais do BR (20k a 46k views) têm gancho de **43% a 53%** — todos abaixo do piso — e retenção de 105% a 136% (Short conta replay, por isso passa de 100%). No canal US **nenhum vídeo jamais** passou do piso, então a régua caía no fallback em toda execução desde que foi criada.

O efeito prático era o inverso do pedido: o único "molde de alto engajamento" do canal BR era um vídeo de **183 views sobre IA**, e foi assim que saiu um Short sobre robô humanoide num canal cujos hits são todos de geopolítica.

### O piso de engajamento vem da CURVA, não de uma métrica

O "Continuaram assistindo" do Studio **não é exposto pela Analytics API**. Verificado em 2026-08-17: `swipeAways`, `skipRate`, `engagementRate`, `continuedWatching` e `audienceRetentionPercentage` devolvem todos *Unknown identifier*. O único campo próximo, `engagedViews/views`, mede outra escala — no agregado de 28 dias do canal ele dá **46,7%** onde o Studio mostra **66,8%**, e a razão entre os dois varia de 1,43 a 1,61 por vídeo, então não há conversão. Mas ele é **reconstruível pela curva** `audienceWatchRatio` (`dimensions=elapsedVideoTimeRatio`): a queda da audiência nos primeiros segundos **é** o "continuou vs deslizou fora". `_gancho_pela_curva` lê quanto da audiência do instante inicial ainda está lá aos **6 segundos** (`SEGUNDO_DO_GANCHO`).

O ponto de leitura foi **calibrado, não chutado**: com 6 vídeos cujo "Continuaram assistindo" real foi lido no Studio, varreu-se de 1s a 8s procurando o que reproduz aquele número. Erro médio absoluto — 1s: 23,7 pts · 3s: 9,0 pts · 5s: 3,3 pts · **6s: 3,32 pts (viés −0,4)** · 6,5s: 3,31 pts (viés −1,6) · 8s: 4,7 pts. Ganha 6s pelo **viés**: 6,5s empata no erro mas puxa a leitura para baixo sistematicamente. A janela (vida toda vs 28 dias) não importa — muda o erro na terceira casa.

O custo é **uma chamada por vídeo**. Ele só é viável porque roda **depois** do corte de `LIMITE_REFERENCIA` e **em paralelo** (`CURVAS_PARALELAS`, 16 threads): medido, **30 curvas em ~44 segundos**, contra ~4 minutos se rodasse sobre o catálogo inteiro. Foi para isso que o teto de 50 existe.

**Precisão.** Sobram **3,3 pontos** de erro, irredutíveis por este caminho: o desvio por vídeo vai de −5 a +3, então a fórmula exata do Studio difere da nossa em algo que a curva não revela. Trate `ENGAJAMENTO_MINIMO` como uma faixa, não como fronteira: subir de 70 para 75 muda quem entra, mexer de 70 para 71 não significa nada.

O piso **corta**: dos 30 vídeos do BR que passam na retenção, **6 saem** por engajamento, e os 24 que ficam leem de 70% a 79% — a mesma faixa dos 70,1% a 74,4% que o Studio mostra. Vídeo **sem curva** (novo demais, erro de rede) **não é reprovado** — ausência de medição não é sinal de nada — e se o piso esvaziar a lista, ele cede.

Já a **ordenação** é `gancho × profundidade`, a pontuação de **antes** de 2026-08-16 — com o `engagedViews/views` barato, que serve para ordenar mesmo sem servir para cortar. Aquela versão funcionava justamente porque ordenava: ordenação devolve os melhores do canal seja qual for a escala da métrica, enquanto um piso absoluto numa escala que nunca alcança o número pedido reprova o catálogo inteiro.

### Como está agora

- O ranking **ordena por `gancho × profundidade`**, a pontuação da versão que funcionava.
- O **piso de `RETENCAO_MINIMA`: retenção acima de 100%** (o vídeo foi reassistido), combinado com **`VIEWS_MINIMO_REFERENCIA` (1000 views)** para o número significar algo. O piso de views fecha o buraco por onde o vídeo de 183 views passava. Resultado: **30 vídeos de referência no BR e 25 no US**.
- **Teto de `LIMITE_REFERENCIA` (50)**, aplicado depois da ordenação, então o corte é sempre pelos piores. 50 é também o limite de ids que `videos.list` aceita por chamada, então a lista inteira cabe numa requisição de títulos. Hoje o teto ainda não morde.
- Os **títulos entram no log** (os 10 primeiros). Sem isso era impossível auditar a régua sabendo só a contagem — a investigação acima só achou o vídeo de 183 views consultando a API por fora.
- A busca de títulos vai em **lotes de 50**, porque `videos.list` recusa mais que isso por chamada. Com o teto de 50 a lista cabe numa chamada, mas o lote continua ali para o dia em que o teto subir.

No prompt de seleção (`escritor._resumo_campeoes`), cada vídeo entra **rotulado em código**: `[ALTA RETENÇÃO]` acima do piso, `[abaixo do piso de 70%]` abaixo dele. O rótulo é escrito por Python, e não deixado para o modelo comparar de cabeça, porque regra numérica embutida em prosa é justamente o tipo de instrução que se perde no meio de cem linhas de contexto.

**A semelhança que vale é a de ASSUNTO** (2026-08-17). O prompt antigo pedia que a candidata "se parecesse" com os campeões sem dizer em quê, e o modelo lia isso como formato, gancho ou energia do título. Agora a instrução é explícita: leia de que **temas** tratam os vídeos de alta retenção e escolha a candidata cujo **assunto** cai no mesmo território; candidata de tema alheio a essa lista é a pior escolha possível, por mais atual que pareça.

**O piso prioriza, não veta.** Canal sem nenhum vídeo acima dele não trava: a lista cai para os melhores disponíveis, com aviso no log e com cada um marcado como abaixo do piso. Bloquear a publicação por causa da régua deixaria o canal sem vídeo justamente quando ele mais precisa de material novo.

## Como funciona a estrutura em cinco blocos

Todo roteiro — Short e `--long-take` — segue a mesma ordem de aula bem dada:

1. **PERGUNTA ESQUISITA** (a primeira frase, campo `pergunta`): concreta, estranha e específica, com coisa/número/gente dentro ("quanto custa desligar um data center por um dia?"). É **proibida** pergunta abstrata, retórica ou dirigida ao espectador ("você já parou pra pensar?"). O estranhamento é o gancho: o cérebro quer a resposta.
2. **CONTEXTUALIZAÇÃO**: o mínimo para a pergunta fazer sentido — e é aqui que assunto de nicho ganha a âncora pró-leigo ("a empresa por trás do ChatGPT").
3. **DESENVOLVIMENTO**: o miolo. O que aconteceu, com número, nome, **mecanismo** e a fonte nominal.
4. **CONSEQUÊNCIA**: uma só, concreta — o que muda para quem trabalha, investe ou usa aquilo.
4. **CONCLUSÃO**: a **resposta** à pergunta da abertura, em uma frase seca que carrega a **disputa** do assunto. No Short ela emenda de volta na pergunta quando o vídeo reinicia (**loop**); no `--long-take` ela fecha de verdade, com o próximo marco a observar.

A auditoria pró-leigo (chamada própria ao GPT) verifica isso em código de prompt: reprova se a primeira frase não for pergunta, se a pergunta for abstrata ou dirigida ao espectador, e se a narração **não responder** a pergunta antes de acabar.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (X API pay-per-use, ~US$ 0,005/post, teto `X_MAX_POSTS`) | ~US$ 1,00 com o padrão de 200 posts |
| Figuras geradas (gpt-image-2, `MAX_FIGURAS` imagens em qualidade `medium`) | ~US$ 0,08 por figura (`MAX_FIGURAS=0` desliga) |
| Mídias dos posts da trend (X API, até 12 posts + pool de 6 clipes e 4 fotos) | ~US$ 0,11 (~US$ 0,17 com `--long-take`: 16 posts, 11 clipes, 6 fotos) |
| GPT 5.6 Luna (sumarização + seleção + roteiro + visão e auditoria das mídias) | ~US$ 0,08 (~US$ 0,14 com `--long-take`: mais mídias no pool) |
| ElevenLabs (~420 caracteres por narração de 25s) | ~420 créditos do plano (~1.700 no `--long-take`) |
| Panorama do dia (YouTube Data API) | **US$ 0** — 1 busca no balde de Search Queries (100/dia) + 1 unidade de cota |

O maior custo de API é a leitura de posts do X — ajuste `X_MAX_POSTS` para equilibrar cobertura e preço. A auditoria e as cartelas somam ~US$ 0,10 por vídeo (pool maior de mídias na X API + uma chamada de visão por mídia do pool + a chamada da nota de pertinência): para cortar isso, baixe `MAX_POSTS_MIDIA`/`POOL_EXTRA_CLIPES` — mas lembre que sem pool a auditoria só tem como reprovar até o vídeo não sair. `MAX_CARTELAS=0` e `MAX_FOTOS=0` desligam a parte das cartelas sem mexer na auditoria dos clipes, e `MAX_FIGURAS=0` desliga a geração de imagem. A leitura da lista substituiu as várias consultas de busca mais uma requisição por conta das timelines: hoje a coleta é **uma** chamada paginada. O custo fixo segue sendo o plano da ElevenLabs: o gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana.

**Atenção ao ligar o `--long-take` num cron diário**: cada vídeo longo consome ~1.700 créditos de TTS, ou seja ~51k créditos/mês com uma execução por dia — sozinho já estoura o Starter. Some a isso a leitura de posts do X, que é cobrada por execução (~US$ 1,00 com `X_MAX_POSTS=200`): um cron de vídeo longo por dia custa ~US$ 30/mês só de X API. Se o longo rodar em horário próximo ao de um Short, considere baixar `X_MAX_POSTS` na execução longa.

## Problemas comuns

- **Erro na coleta de posts** — confira `X_CONSUMER_KEY`/`X_CONSUMER_SECRET` e o saldo/plano do app em [developer.x.com](https://developer.x.com).
- **Quer mudar as contas acompanhadas** — **adicione ou remova o membro na lista do X**: a coleta lê `X_LIST_ID` a cada execução e a mudança vale já na próxima.
- **`Leitura da lista … falhou: 401`** — access token do X vencido ou revogado. Confira o cron `x-token-refresher` (ele grava `X_OAUTH_ACCESS_TOKEN` e `X_OAUTH_ACCESS_TOKEN_EXPIRA` no próprio serviço) e, se o refresh tiver sido queimado, reautorize no navegador. Desde 2026-08-22 isso **aborta** a execução em vez de cair para as contas seguidas — não há mais fallback.
- **`Sem X_LIST_ID não há pauta`** — preencha `X_LIST_ID` com o id da lista (o número na URL `x.com/i/lists/…`).
- **Execução abortou sem clipe** — a trend escolhida precisa ter post com vídeo nativo; a seleção já filtra, mas o download ainda pode falhar (post apagado, todas as variantes acima de 60 MB). Desde 2026-08-05 isso derruba só a **candidata**, não a execução: o log mostra `[fallback] Tentativa 1/3 descartada` e outra trend é tentada. Abortar de vez exige as 3 falharem.
- **Execução abortou na auditoria** (`[fallback] ... a auditoria aprovou 0 clipe(s)` nas 3 tentativas) — todo o material das candidatas era de telejornal, tinha selo de emissora ou não mostrava o que a narração diz. Abrir o `auditoria_clipe.json` da pasta do vídeo mostra o motivo de cada reprovação. Se estiver reprovando demais, o caminho é **aumentar o pool** (`MAX_POSTS_MIDIA`, `POOL_EXTRA_CLIPES`), não afrouxar a regra — a alternativa é o vídeo voltar a mostrar material que não condiz com a narração. No `--long-take` o telejornal já não reprova (entra marcado como representação visual), então uma reprovação em massa ali é de **pertinência**: o material não mostra o que a narração diz.
- **Muitos clipes reprovados por "texto ocupando a tela"** — é o veto de 2026-08-07 funcionando: o assunto do dia rendeu sobretudo print, slide e cartaz, e nenhum deles era o que a narração descrevia. O `auditoria_clipe.json` mostra `densidade_texto` e `texto_estatico` de cada mídia. Se estiver reprovando material bom, o primeiro suspeito é a narração não estar **falando** do que a tela mostra (o auditor só marca `texto_pertinente` quando ela fala); `VETO_TEXTO_DENSO=0` desliga a regra inteira.
- **Vídeo publicado sem capítulos** (`--long-take`) — o bloco só sai quando é válido pelo YouTube: `0:00` no primeiro, mínimo de 3 e trechos de pelo menos 10s. O log diz qual citação não foi encontrada na narração (`[seo] Capítulo sem âncora…`) ou que sobraram poucos capítulos. Capítulo com carimbo chutado seria pior que capítulo nenhum, então o bloco é descartado inteiro.
- **`[seo] aviso: panorama do dia falhou`** — a busca do assunto no YouTube não voltou. Falha aberta de propósito: o vídeo sai com título, descrição e capa calibrados só pelo histórico do canal. Se o motivo for cota, o balde de **Search Queries** é de 100 buscas/dia e o pipeline usa uma por execução (mais uma por tentativa do fallback de tema).
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 3)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` (e `--auth-youtube-usa`) de novo para reautorizar com os escopos de leitura. Sem isso a execução aborta logo no início (a leitura alimenta a seleção guiada pela audiência).
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
