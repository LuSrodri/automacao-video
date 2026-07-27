# Automação de Vídeos — Geopolítica, Inteligência, IA & Tech

Pipeline em Python que transforma as trends mais quentes de geopolítica, inteligência, IA e tech no X (Twitter) em um vídeo vertical narrado, em formato explicativo (análise/educacional), pronto para publicar:

1. **Coleta** os posts das últimas 24h da **lista fixa de contas** do canal (`CONTAS_PADRAO` em `pipeline/config.py`; `X_ACCOUNTS` no `.env` a substitui) via X API oficial v2, pay-per-use, com teto de leitura configurável, e o **GPT** os sumariza nas **10 trends mais quentes** — notícias, lançamentos, novidades, curiosidades e tretas — cada uma com resumo, engajamento, nota de apelo visual e **quantos posts têm clipe de vídeo nativo** (a mesma chamada da coleta já traz o tipo de mídia de cada post).
2. **GPT 5.6 Luna** classifica cada candidata (**macrotema** + **imagem mental**) — sem filtro nem score: todas as candidatas seguem vivas para a seleção.
3. **GPT 5.6 Luna** escolhe a trend guiado **somente pela audiência**: recebe os **últimos 100 vídeos publicados no canal selecionado com as métricas reais** (views/likes em tempo real, YouTube Data API) e os **campeões de retenção** (YouTube Analytics), e escolhe a candidata com a maior chance de performar com esse público — repetir o tipo de conteúdo que está performando é bem-vindo. Regras duras, aplicadas em código: **candidata sem nenhum post com clipe de vídeo sai da disputa** (o formato é montado só com clipes do X), **o mesmo macrotema não emenda mais de 4 vídeos seguidos** e a **verificação anti-repetição** — o GPT confere se a escolhida cobriria o **mesmo fato** de um vídeo publicado nas últimas 36h sem desenvolvimento novo; se sim, ela sai da disputa e a seleção refaz (se todas as candidatas caírem em uma das regras, não há vídeo).
4. **Firecrawl (sources=news)** busca **notícias recentes** sobre a trend escolhida (título, link, resumo e data) para complementar o material com fatos, nomes e números corretos (falha aqui não aborta: o roteiro segue com o resumo e os posts do X).
5. **GPT 5.6 Luna** escreve o roteiro **explicativo (análise/educacional) em tom adulto**, **sempre citando as fontes** (as contas do X que originaram a trend e os veículos das notícias do Firecrawl): para um adulto leigo (o público real: homens de 25-54) com metade da atenção — frases com **ritmo de fala natural** (8 a 16 palavras, teto 20, alternando curtas de impacto com mais cheias), uma ideia por frase, **vocabulário preciso de telejornal** (sem jargão de nicho nem sigla sem explicação), tom de furo de notícia (nunca infantil), estrutura fixa **HOOK (imagem chocante, 0-2s) → FATO (até a metade, com âncora pró-leigo quando o assunto é de nicho) → IMPLICAÇÃO única (segunda metade) → CORTE em tensão que emenda no hook (loop)**, sem CTA falado. O **título e a descrição são autossuficientes** (teste do leigo: sem nome de nicho, sem cauda de suspense; a descrição entrega o fato com a fonte, não é teaser) e prometem **exatamente** o que o vídeo entrega. Uma **auditoria pró-leigo** (chamada própria ao GPT) confere título, descrição e narração contra essas regras e pede **uma reescrita** quando reprova. O roteiro inclui **audio tags** (`[excited]`, `[whispers]`…) que ditam o tom da voz.
6. **X API** baixa até **3 clipes de vídeo** dos posts originais da trend (o MP4 de maior bitrate de cada um), junto com a **conta de origem** de cada clipe — **imagem estática é proibida** no formato, então não há busca de imagens na web.
7. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere) e o pipeline **corta os silêncios** da narração (remapeando os timestamps para as legendas continuarem sincronizadas), deixando o áudio sem trechos parados.
8. **Infográficos animados**: o GPT escolhe até **2 números reais** da história (nunca inventados) e o pipeline renderiza (Pillow) **contadores** que sobem do zero e terminam **verdes** — ou descem até o negativo e terminam **vermelhos** — e **barras comparativas** com a barra destacada crescendo mais que as outras. Estilo minimalista e editorial: Archivo Black preta com **stroke branco** (a mesma tipografia das legendas), **emoji colorido com halo branco** e a **fonte do dado citada** no rodapé. O painel ocupa o **terço superior** (o crédito de reprodução some enquanto ele está na tela) e **sempre surge deslizando da base do vídeo** com easing suave.
9. **ffmpeg** monta o vídeo vertical: o **fundo de cada momento é o próprio clipe daquele trecho, ampliado para cobrir a tela e borrado**; por cima entra o **clipe nítido em largura total, centrado** (clipe mais curto que a janela repete em loop). Os clipes **cobrem 100% da narração** (nunca há um instante sem imagem) com **crossfade curto e limpo** entre si. **Legendas** sincronizadas palavra a palavra — grandes, em **Archivo Black** branca com contorno preto, com entrada de "carimbo" editorial — são queimadas no vídeo, e o **crédito de reprodução** ("Reprodução Imagem: X" + "Conta `@usuario`" do post de origem; "Image Credit"/"Account" no modo `-usa`) fica no **canto superior direito** sobre uma tarja preta translúcida, trocando junto com o clipe. A trilha `assets/trilha.mp3` entra em **loop sob a narração** a ~-18 dB (alavanca de retenção; a faixa incluída é "Tension Documentary" de AtlasAudio, licença Pixabay — uso comercial livre, sem atribuição; troque o arquivo para mudar a trilha, ou apague-o para vídeo sem música). A cauda após a narração é de **0,15s** — curta de propósito, para o CORTE emendar no hook quando o Short reinicia (loop).
10. O `.mp4` final vai para `output/`, é registrado em `videos.txt` e publicado automaticamente no **YouTube** (Data API v3). Roda sempre, independente da flag `-usa` (o horário de publicação é o do cronjob que dispara a execução).

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
- **Material**: até **8 clipes** de vídeo do X (consultando até 10 posts da
  trend), trocando a cada 8-20s; clipe vertical aparece como faixa central
  sobre o próprio clipe borrado. Até **4 infográficos** animados, espalhados
  pela narração.
- **Regras duras próprias**: candidatas com pelo menos 2 posts com clipe têm
  preferência, e o teto de macrotema e o veto a vídeo repetido (janela de 72h)
  comparam **só com os vídeos longos** já publicados — a rajada de Shorts do
  dia não bloqueia o longo, e um Short sobre o mesmo fato não conta como
  repetição.

A duração final segue a narração: o roteirista escreve dentro de uma faixa
dura de palavras (~216 a 266 faladas) e o pipeline avisa no log se o áudio
sair fora de 90-120s.

## Ajustes no .env

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `X_ACCOUNTS` | vazio | Opcional: usa somente estas contas no lugar da lista fixa `CONTAS_PADRAO` (`pipeline/config.py`) |
| `X_MAX_POSTS` | `200` | Teto de posts lidos por execução (a X API cobra por post lido) |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados |
| `NUM_TRENDS` | `10` | Quantas trends mais faladas do X coletar para escolher a do vídeo |
| `NUM_NOTICIAS` | `6` | Quantas notícias (Firecrawl news) buscar para enriquecer a trend |
| `TEXT_MODEL` | `gpt-5.6-luna` | Modelo do roteiro, da sumarização das trends e da visão |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `32` | Duração-alvo da narração em segundos (a duração final segue o áudio; o corte de silêncios tira ~10%, então 32s de alvo ≈ vídeo final de ~29s, a faixa que melhor retém) |
| `VIDEO_LARGURA` | `1080` | Largura do vídeo |
| `VIDEO_ALTURA` | `1920` | Altura do vídeo |
| `LONG_DURACAO` | `105` | Só com `--long-take`: duração-alvo da narração (aceita 90 a 120) |
| `LONG_LARGURA` / `LONG_ALTURA` | `1920` / `1080` | Só com `--long-take`: resolução 16:9 |
| `LONG_MAX_CLIPES` | `8` | Só com `--long-take`: clipes do X usados na montagem |
| `LONG_MAX_POSTS_MIDIA` | `10` | Só com `--long-take`: posts da trend consultados para achar os clipes |
| `LONG_NUM_NOTICIAS` | `10` | Só com `--long-take`: notícias que embasam a análise |
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

O pipeline baixa até **3 clipes de vídeo** dos posts originais da trend (**8 no `--long-take`**; X API, MP4 de maior bitrate) e o **GPT com visão** descreve cada um a partir de frames extraídos pelo ffmpeg. Um "editor de cortes" (GPT) decide então **quando cada clipe entra**, ancorando cada corte numa **citação exata da narração** (convertida em tempo pelos timestamps do ElevenLabs) — o primeiro clipe abre o gancho, e clipe mais curto que a janela repete em **loop**. Na tela, cada clipe carrega o próprio **crédito de reprodução** no canto superior direito ("Reprodução Imagem: X" + "Conta `@usuario`" do post de onde ele veio). O plano fica em `cortes.json`; se ele falhar, os clipes são distribuídos uniformemente pela narração.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (X API pay-per-use, ~US$ 0,005/post, teto `X_MAX_POSTS`) | ~US$ 1,00 com o padrão de 200 posts |
| Clipes dos posts da trend (X API, até 5 posts) | ~US$ 0,03 (~US$ 0,09 com `--long-take`, até 10 posts + 8 mídias) |
| Busca de notícias (Firecrawl Search) | ~2 créditos por consulta |
| GPT 5.6 Luna (sumarização das trends + seleção + roteiro + visão dos clipes) | < US$ 0,04 (~US$ 0,08 com `--long-take`: mais clipes descritos com visão) |
| ElevenLabs (~1.000 caracteres por narração de 60s) | ~1.000 créditos do plano (~1.700 no `--long-take`) |

O maior custo de API é a leitura de posts do X — ajuste `X_MAX_POSTS` para equilibrar cobertura e preço. O custo fixo segue sendo o plano da ElevenLabs: o gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana.

**Atenção ao ligar o `--long-take` num cron diário**: cada vídeo longo consome ~1.700 créditos de TTS, ou seja ~51k créditos/mês com uma execução por dia — sozinho já estoura o Starter. Some a isso a leitura de posts do X, que é cobrada por execução (~US$ 1,00 com `X_MAX_POSTS=200`): um cron de vídeo longo por dia custa ~US$ 30/mês só de X API. Se o longo rodar em horário próximo ao de um Short, considere baixar `X_MAX_POSTS` na execução longa.

## Problemas comuns

- **Erro na coleta de posts** — confira `X_CONSUMER_KEY`/`X_CONSUMER_SECRET` e o saldo/plano do app em [developer.x.com](https://developer.x.com).
- **Quer mudar as contas acompanhadas** — edite `CONTAS_PADRAO` em `pipeline/config.py`, ou preencha `X_ACCOUNTS` no `.env` para substituir a lista sem mexer no código.
- **Erro/429 na busca de notícias** — confira a `FIRECRAWL_API_KEY` e o saldo de créditos no [dashboard do Firecrawl](https://firecrawl.dev) (falha aqui não aborta: o roteiro segue sem as notícias).
- **Execução abortou sem clipe** — a trend escolhida precisa ter post com vídeo nativo; a seleção já filtra, mas o download ainda pode falhar (post apagado, vídeo acima de 60 MB). Rodar de novo escolhe outra trend se a conversa mudou.
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 3)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` (e `--auth-youtube-usa`) de novo para reautorizar com os escopos de leitura. Sem isso a execução aborta logo no início (a leitura alimenta a seleção guiada pela audiência e o teto de macrotemas seguidos).
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
