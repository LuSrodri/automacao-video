# Automação de Vídeos — Geopolítica, Inteligência, IA & Tech

Pipeline em Python que transforma as trends mais quentes de geopolítica, inteligência, IA e tech no X (Twitter) em um vídeo vertical narrado, em formato explicativo (análise/educacional), pronto para publicar:

1. **Coleta** os posts das últimas 24h da **lista fixa de contas** do canal (`CONTAS_PADRAO` em `pipeline/config.py`; `X_ACCOUNTS` no `.env` a substitui) via X API oficial v2, pay-per-use, com teto de leitura configurável, e o **GPT** os sumariza nas **10 trends mais quentes** — notícias, lançamentos, novidades, curiosidades e tretas — cada uma com resumo, engajamento, nota de apelo visual e **quantos posts têm clipe de vídeo nativo** (a mesma chamada da coleta já traz o tipo de mídia de cada post). O GPT devolve o **inventário completo** dos posts com vídeo de cada trend (`posts_video`) à parte da lista de posts mais centrais (`posts`, truncada): a contagem sai da união dos dois, senão uma pauta que **tem** clipe — só não entre os posts mais centrais — seria vetada como se não tivesse material. Os posts com vídeo vão para a frente da lista, que é onde o lookup de mídias corta.
2. **GPT 5.6 Luna** classifica cada candidata (**macrotema** + **imagem mental**) — sem filtro nem score: todas as candidatas seguem vivas para a seleção.
3. **GPT 5.6 Luna** escolhe a trend guiado **somente pela audiência**: recebe os **últimos 100 vídeos publicados no canal selecionado com as métricas reais** (views/likes em tempo real, YouTube Data API) e os **campeões de retenção** (YouTube Analytics), e escolhe a candidata com a maior chance de performar com esse público — repetir o tipo de conteúdo que está performando é bem-vindo. Regras duras, aplicadas em código: **candidata sem nenhum post com clipe de vídeo sai da disputa** (o formato é montado só com clipes do X), **o mesmo macrotema não emenda mais de 4 vídeos seguidos** e a **verificação anti-repetição** — o GPT confere se a escolhida cobriria o **mesmo fato** de um vídeo publicado nas últimas 36h sem desenvolvimento novo; se sim, ela sai da disputa e a seleção refaz (se todas as candidatas caírem em uma das regras, não há vídeo).
4. **Firecrawl (sources=news)** busca **notícias recentes** sobre a trend escolhida (título, link, resumo e data) para complementar o material com fatos, nomes e números corretos (falha aqui não aborta: o roteiro segue com o resumo e os posts do X).
5. **GPT 5.6 Luna** escreve o roteiro **explicativo (análise/educacional) em tom adulto**, **sempre citando as fontes** (as contas do X que originaram a trend e os veículos das notícias do Firecrawl): para um adulto leigo (o público real: homens de 25-54) com metade da atenção — frases com **ritmo de fala natural** (8 a 16 palavras, teto 20, alternando curtas de impacto com mais cheias), uma ideia por frase, **vocabulário preciso de telejornal** (sem jargão de nicho nem sigla sem explicação), tom de furo de notícia (nunca infantil), estrutura fixa **HOOK (imagem chocante, 0-2s) → FATO (até a metade, com âncora pró-leigo quando o assunto é de nicho) → IMPLICAÇÃO única (segunda metade) → CORTE em tensão que emenda no hook (loop)**, sem CTA falado. O **título e a descrição são autossuficientes** (teste do leigo: sem nome de nicho, sem cauda de suspense; a descrição entrega o fato com a fonte, não é teaser) e prometem **exatamente** o que o vídeo entrega. Uma **auditoria pró-leigo** (chamada própria ao GPT) confere título, descrição e narração contra essas regras e pede **uma reescrita** quando reprova. O roteiro inclui **audio tags** (`[excited]`, `[whispers]`…) que ditam o tom da voz.
6. **X API** baixa um **pool de clipes de vídeo** dos posts originais da trend (o MP4 de maior bitrate de cada um) — mais do que os 3 que entram na montagem, como folga para a auditoria — junto com a **conta de origem** de cada clipe e as **fotos dos posts**, que alimentam as cartelas. **Imagem estática nunca ocupa a tela**, então não há busca de imagens na web.
7. **Auditoria do material visual** (`pipeline/auditoria.py`): o **GPT com visão** descreve e **classifica** cada clipe do pool (cena real, reportagem de TV, gravação de tela, cartela, logo…) e diz se há **selo de emissora ou veículo de imprensa** na imagem. Em cima disso: **veto duro em código** — material de telejornal, vinheta de logotipo e qualquer mídia com selo de emissora saem da disputa, assim como mídia que não recebeu laudo — e uma **nota de pertinência de 1 a 5** dada pelo GPT, que mede só uma coisa: o quanto aquilo que a mídia **mostra** é o que a narração **diz** (abaixo de 3 sai; material que mostra a manchete de um veículo em vez do fato tem teto 2). **Zero clipe aprovado aborta a execução** (o formato longo exige um piso de 3). Roda **antes do ElevenLabs**, para a reprovação não custar créditos de narração, e deixa o rastro em `auditoria_clipe.json`.
8. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere) e o pipeline **corta os silêncios** da narração (remapeando os timestamps para as legendas continuarem sincronizadas), deixando o áudio sem trechos parados.
9. **Infográficos animados**: o GPT escolhe até **2 números reais** da história (nunca inventados) e o pipeline renderiza (Pillow) **contadores** que sobem do zero e terminam **verdes** — ou descem até o negativo e terminam **vermelhos** — e **barras comparativas** com a barra destacada crescendo mais que as outras. Estilo minimalista e editorial: Archivo Black preta com **stroke branco** (a mesma tipografia das legendas), **emoji colorido com halo branco** e a **fonte do dado citada** no rodapé. O painel ocupa o **terço superior** (o crédito de reprodução some enquanto ele está na tela) e **sempre surge deslizando da base do vídeo** com easing suave.
10. **Cartelas de imagem nos momentos-chave** (`pipeline/cartelas.py`): a **foto do post da trend** (que o pipeline já lia e descartava) ou a **og:image de uma das notícias** entra **emoldurada por cima do clipe** por ~3,6s, no instante em que a narração **nomeia** o que ela mostra — a pessoa citada, o lugar atingido, o documento assinado. Cartão branco com cantos arredondados, sombra e o **crédito próprio** no rodapé (`Reprodução: X / @conta` ou o domínio do veículo; `Image Credit` no `-usa`), entrando com escala 92%→100% e fade. As imagens passam pela **mesma auditoria dos clipes** (visão + veto duro + nota), o gancho fica limpo (nada entra nos 3 primeiros segundos) e nenhuma cartela cai em cima de um infográfico.
11. **ffmpeg** monta o vídeo vertical: o **fundo de cada momento é o próprio clipe daquele trecho, ampliado para cobrir a tela e borrado**; por cima entra o **clipe nítido em largura total, centrado** (clipe mais curto que a janela repete em loop). Os clipes **cobrem 100% da narração** (nunca há um instante sem imagem) com **crossfade curto e limpo** entre si. **Legendas** sincronizadas palavra a palavra — grandes, em **Archivo Black** branca com contorno preto, com entrada de "carimbo" editorial — são queimadas no vídeo, e o **crédito de reprodução** ("Reprodução Imagem: X" + "Conta `@usuario`" do post de origem; "Image Credit"/"Account" no modo `-usa`) fica no **canto superior direito** sobre uma tarja preta translúcida, trocando junto com o clipe. A trilha `assets/trilha.mp3` entra em **loop sob a narração** a ~-18 dB (alavanca de retenção; a faixa incluída é "Tension Documentary" de AtlasAudio, licença Pixabay — uso comercial livre, sem atribuição; troque o arquivo para mudar a trilha, ou apague-o para vídeo sem música). A cauda após a narração é de **0,15s** — curta de propósito, para o CORTE emendar no hook quando o Short reinicia (loop).
12. O `.mp4` final vai para `output/`, é registrado em `videos.txt` e publicado automaticamente no **YouTube** (Data API v3). Roda sempre, independente da flag `-usa` (o horário de publicação é o do cronjob que dispara a execução).

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

`--long-take` produz um **vídeo de análise em 16:9 (1920x1080), de 90 a 120
segundos, sem legendas**, para os **dois canais** (combina com `-usa`). É o
mesmo pipeline — mesma coleta do X, mesmas notícias do Firecrawl, mesmo
crédito de reprodução no canto superior direito — com outra direção editorial:

- **Enquadramento**: explica um acontecimento contemporâneo cruzando as quatro
  óticas — **geopolítica, tecnologia/IA, negócios e mercado de trabalho** —
  costuradas por causa e efeito, nunca como lista de tópicos.
- **Espectador**: o adulto que está **procurando emprego ou em transição de
  carreira**. O payload obrigatório do vídeo é o que aquele acontecimento muda
  na prática para ele (setor que contrata ou corta, função na linha de tiro,
  habilidade que passa a valer, prazo) — conselho de coach e futurologia sem
  base reprovam na auditoria.
- **Estrutura**: ABERTURA (hook + promessa) → O QUE ACONTECEU → AS QUATRO
  ÓTICAS → O QUE ISSO MUDA PARA QUEM TRABALHA → SÍNTESE + O QUE OBSERVAR
  (próximo marco concreto). Sem CTA e sem loop — o vídeo fecha entregando.
- **Fontes**: pelo menos duas citações nominais na narração (veículo ou conta
  do X) e a **lista de links reais** anexada ao final da descrição do YouTube.
- **Sem legendas queimadas**: a narração se sustenta sozinha (nenhuma frase
  pode depender de texto na tela).
- **Capa customizada** (`pipeline/thumbnail.py`): um quadro real do vídeo (2s,
  já com a sala e a TV) escurecido, com 2 a 5 palavras em Archivo Black na
  base. O texto vem do GPT com uma regra dura — dizer **o fato**, nunca
  provocar: "TRUMP PAUSA ATAQUES" e não "VOCÊ NÃO VAI ACREDITAR", porque
  curiosidade fabricada traz clique e perde a audiência no primeiro segundo.
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
  **4 infográficos** animados e **4 cartelas** de imagem, espalhados pela
  narração. A auditoria exige um **piso de 3 clipes aprovados** — 90 a 120
  segundos presos em um ou dois clipes é insustentável, então abaixo disso o
  vídeo não sai.
- **Regras duras próprias**: candidata precisa de **4 posts com clipe** para
  disputar (`LONGO_MIN_POSTS_VIDEO`, derivado do piso de 3 da auditoria mais
  uma folga, já que a auditoria reprova parte do material) — sem ninguém no
  portão a execução aborta ali, antes de gastar roteiro e narração, porque
  seguir com material insuficiente é gastar para falhar adiante. E o teto de
  macrotema e o veto a vídeo repetido (janela de 72h)
  comparam **só com os vídeos longos** já publicados — a rajada de Shorts do
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
dura de palavras (~216 a 266 faladas) e o pipeline avisa no log se o áudio
sair fora de 90-120s.

## Ajustes no .env

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `X_ACCOUNTS` | vazio | Opcional: usa somente estas contas no lugar da lista fixa `CONTAS_PADRAO` (`pipeline/config.py`) |
| `X_MAX_POSTS` | `200` | Teto de posts lidos por execução (a X API cobra por post lido) |
| `X_MAX_POSTS_VIDEO` | `60` | Leituras extras de uma varredura `has:videos` sobre as **mesmas** contas — a coleta normal ordena por relevância e não prefere vídeo, então o post com clipe perdia vaga para texto. Nenhuma fonte nova; `0` desliga |
| `X_MAX_POSTS_BUSCA` | `30` (só `--long-take`) | Busca **aberta** por clipes do assunto, fora das contas do canal. Fontes **não curadas** — a auditoria é a única guarda, e ela julga pertinência, não veracidade; `0` desliga |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados. Alargar **não** custa mais na X API (o teto é o `X_MAX_POSTS`; a janela só decide de que intervalo saem esses posts). Case com a **cadência do cron**, não com o formato: em produção os Shorts rodam com `4` (de 4 em 4 horas) e os crons `--long-take` com `48` — ver a nota abaixo |
| `NUM_TRENDS` | `10` | Quantas trends mais faladas do X coletar para escolher a do vídeo |
| `NUM_NOTICIAS` | `6` | Quantas notícias (Firecrawl news) buscar para enriquecer a trend |
| `TEXT_MODEL` | `gpt-5.6-luna` | Modelo do roteiro, da sumarização das trends e da visão |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `32` | Duração-alvo da narração em segundos (a duração final segue o áudio; o corte de silêncios tira ~10%, então 32s de alvo ≈ vídeo final de ~29s, a faixa que melhor retém) |
| `VIDEO_LARGURA` | `1080` | Largura do vídeo |
| `VIDEO_ALTURA` | `1920` | Altura do vídeo |
| `MAX_POSTS_MIDIA` | `12` | Posts da trend consultados no lookup de mídias (a X API cobra por post lido) |
| `POOL_EXTRA_CLIPES` | `3` | Clipes baixados além dos que entram na montagem, como folga da auditoria |
| `MAX_FOTOS` | `4` | Fotos dos posts baixadas para as cartelas (`0` desliga) |
| `MAX_CARTELAS` | `2` | Cartelas de imagem sobrepostas nos momentos-chave (`0` desliga) |
| `LONG_DURACAO` | `105` | Só com `--long-take`: duração-alvo da narração (aceita 90 a 120) |
| `LONG_LARGURA` / `LONG_ALTURA` | `1920` / `1080` | Só com `--long-take`: resolução 16:9 |
| `LONG_MAX_CLIPES` | `8` | Só com `--long-take`: clipes do X usados na montagem |
| `LONG_MAX_POSTS_MIDIA` | `16` | Só com `--long-take`: posts da trend consultados para achar os clipes |
| `LONG_NUM_NOTICIAS` | `10` | Só com `--long-take`: notícias que embasam a análise |
| `LONG_MAX_CARTELAS` | `4` | Só com `--long-take`: cartelas de imagem sobrepostas |
| `LONG_MAX_FOTOS` | `6` | Só com `--long-take`: fotos dos posts baixadas para as cartelas |
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

(No formato longo, `--long-take`, **não há legendas**: esta seção vale só para os Shorts.) A ElevenLabs retorna o tempo de fala de cada caractere (`/with-timestamps`), e o pipeline mostra **uma palavra por vez** em maiúsculas, gravadas em `legendas.ass` e queimadas no vídeo pelo ffmpeg. Como sempre há clipe na tela, as legendas ficam na **parte inferior** para não cobrir o clipe nítido. O estilo é editorial de rede social: texto **branco com contorno preto grosso e sombra suave**, fonte **Archivo Black** (em `fonts/ArchivoBlack-Regular.ttf`, licença OFL), tamanho de manchete, com entrada de "carimbo" (a palavra surge um pouco maior e assenta no tamanho final). O arquivo `alinhamento.json` de cada execução guarda os timestamps para depuração.

## Como funcionam os infográficos animados

Depois do roteiro e da narração, uma chamada ao GPT (`pipeline/grafico.py`) decide até **2 infográficos** com números que aparecem **de verdade** na narração ou nas notícias — sem número forte, o vídeo sai sem infográfico (a regra é dura: valor inventado é proibido no prompt e o trecho-âncora precisa existir literalmente no texto). Cada infográfico é ancorado numa **citação exata da narração** (convertida em tempo pelos timestamps do ElevenLabs, como nos cortes) e renderizado pelo **Pillow** em frames RGBA transparentes que o ffmpeg sobrepõe:

- **Contador** — número que anima do zero até o valor com easing: alta/ganho termina **verde**, queda/corte desce até o **negativo** e termina **vermelho**. Com prefixo/sufixo (`US$`, `%`, `mil`), rótulo e **emoji colorido com halo branco**.
- **Barras** — 2 a 4 barras comparativas crescendo em sequência; a barra em **destaque** cresce com um leve overshoot e fica colorida, as demais pretas com contorno branco. Valores contam em cima de cada barra.

O painel entra **sempre deslizando da base do vídeo até o terço superior** (ease-out), fica ~4,5s e sai em fade. Enquanto está na tela, o **crédito de reprodução some** — o infográfico ocupa o terço superior. A **fonte do dado** ("Fonte: Reuters", "@conta") aparece no rodapé do painel. O plano de cada execução fica em `graficos.json` na pasta do vídeo, e qualquer falha na etapa só pula os infográficos (nunca derruba o pipeline).

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

A auditoria roda **antes do ElevenLabs**, então reprovar não custa crédito de narração. **Zero clipe aprovado aborta a execução** (piso de 3 no `--long-take`) — a mensagem aponta o `auditoria_clipe.json` da pasta, que lista aprovados e reprovados com nota e motivo. As imagens das cartelas passam pela mesma peneira (`auditoria_imagem.json`).

**Exceção do `--long-take`: telejornal entra marcado, não vetado.** No formato longo, material de tipo `reportagem_tv` e mídia com selo de emissora deixam de cair no veto duro e entram **marcados como representação visual** — o clipe vai para a tela **dessaturado**, com a etiqueta `REPRESENTAÇÃO VISUAL` (`ILLUSTRATIVE FOOTAGE` no `-usa`) no rodapé esquerdo, enquanto os outros clipes da mesma montagem seguem coloridos e sem etiqueta. O motivo: 90 a 120 segundos de tela raramente se sustentam só com cena crua, e a marcação resolve o que originou o veto — o espectador tomar cobertura de terceiro por material do canal. `logo_ou_marca` continua vetado nos dois formatos (vinheta de logotipo não representa assunto nenhum), a nota de pertinência continua valendo para todo mundo, e no formato curto **nada muda**. O `auditoria_clipe.json` marca cada aprovada com `representacao_visual`.

## Como funcionam as cartelas de imagem

Um segundo tipo de sobreposição, ao lado dos infográficos: nos **momentos-chave** — quando a narração **nomeia** a pessoa, o lugar, o documento ou o produto — uma imagem entra **emoldurada por cima do clipe** por ~3,6s. O corpo do vídeo continua sendo só clipe de vídeo do X; imagem estática nunca ocupa a tela sozinha.

- **De onde vêm** — as **fotos dos posts da trend** (que o pipeline já lia da X API e descartava no filtro de tipo: são o material mais barato, vêm no mesmo lookup e estão no assunto por construção) e a **og:image das notícias** já buscadas no Firecrawl, creditadas pelo domínio do veículo. Nenhuma chamada nova de API, e nada de busca de imagem em banco.
- **Como aparecem** — cartão branco com cantos arredondados e sombra, **crédito próprio no rodapé** (`Reprodução: X / @conta` ou `Reprodução: reuters.com`; `Image Credit` no `-usa`), entrando com escala 92%→100% e fade. Centralizado acima da faixa das legendas no vertical, no meio da tela no 16:9.
- **Onde não aparecem** — nos **3 primeiros segundos** (o gancho fica com o clipe limpo) e em cima de um infográfico (as janelas nunca coincidem).
- **Quantas** — até `MAX_CARTELAS` (2; 4 no `--long-take`), escolhidas pelo GPT entre as imagens aprovadas na auditoria, com o momento ancorado numa **citação exata da narração**. O plano fica em `cartelas.json`. `MAX_CARTELAS=0` desliga a feature; qualquer falha só deixa o vídeo sem cartelas.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (X API pay-per-use, ~US$ 0,005/post, teto `X_MAX_POSTS`) | ~US$ 1,00 com o padrão de 200 posts |
| Mídias dos posts da trend (X API, até 12 posts + pool de 6 clipes e 4 fotos) | ~US$ 0,11 (~US$ 0,17 com `--long-take`: 16 posts, 11 clipes, 6 fotos) |
| Busca de notícias (Firecrawl Search) | ~2 créditos por consulta |
| GPT 5.6 Luna (sumarização + seleção + roteiro + visão e auditoria das mídias) | ~US$ 0,08 (~US$ 0,14 com `--long-take`: mais mídias no pool) |
| ElevenLabs (~1.000 caracteres por narração de 60s) | ~1.000 créditos do plano (~1.700 no `--long-take`) |

O maior custo de API é a leitura de posts do X — ajuste `X_MAX_POSTS` para equilibrar cobertura e preço. A auditoria e as cartelas somam ~US$ 0,10 por vídeo (pool maior de mídias na X API + uma chamada de visão por mídia do pool + a chamada da nota de pertinência): para cortar isso, baixe `MAX_POSTS_MIDIA`/`POOL_EXTRA_CLIPES` — mas lembre que sem pool a auditoria só tem como reprovar até o vídeo não sair. `MAX_CARTELAS=0` e `MAX_FOTOS=0` desligam a parte das cartelas sem mexer na auditoria dos clipes. O custo fixo segue sendo o plano da ElevenLabs: o gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana.

**Atenção ao ligar o `--long-take` num cron diário**: cada vídeo longo consome ~1.700 créditos de TTS, ou seja ~51k créditos/mês com uma execução por dia — sozinho já estoura o Starter. Some a isso a leitura de posts do X, que é cobrada por execução (~US$ 1,00 com `X_MAX_POSTS=200`): um cron de vídeo longo por dia custa ~US$ 30/mês só de X API. Se o longo rodar em horário próximo ao de um Short, considere baixar `X_MAX_POSTS` na execução longa.

## Problemas comuns

- **Erro na coleta de posts** — confira `X_CONSUMER_KEY`/`X_CONSUMER_SECRET` e o saldo/plano do app em [developer.x.com](https://developer.x.com).
- **Quer mudar as contas acompanhadas** — edite `CONTAS_PADRAO` em `pipeline/config.py`, ou preencha `X_ACCOUNTS` no `.env` para substituir a lista sem mexer no código.
- **Erro/429 na busca de notícias** — confira a `FIRECRAWL_API_KEY` e o saldo de créditos no [dashboard do Firecrawl](https://firecrawl.dev) (falha aqui não aborta: o roteiro segue sem as notícias).
- **Execução abortou sem clipe** — a trend escolhida precisa ter post com vídeo nativo; a seleção já filtra, mas o download ainda pode falhar (post apagado, vídeo acima de 60 MB). Rodar de novo escolhe outra trend se a conversa mudou.
- **Execução abortou na auditoria** (`Auditoria aprovou 0 clipe(s)`) — todo o material da trend era de telejornal, tinha selo de emissora ou não mostrava o que a narração diz. Abrir o `auditoria_clipe.json` da pasta do vídeo mostra o motivo de cada reprovação. Se estiver reprovando demais, o caminho é **aumentar o pool** (`MAX_POSTS_MIDIA`, `POOL_EXTRA_CLIPES`), não afrouxar a regra — a alternativa é o vídeo voltar a mostrar material que não condiz com a narração. No `--long-take` o telejornal já não reprova (entra marcado como representação visual), então uma reprovação em massa ali é de **pertinência**: o material não mostra o que a narração diz.
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 3)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` (e `--auth-youtube-usa`) de novo para reautorizar com os escopos de leitura. Sem isso a execução aborta logo no início (a leitura alimenta a seleção guiada pela audiência e o teto de macrotemas seguidos).
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
