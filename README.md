# Automação de Vídeos — Notícias Tech & AI

Pipeline em Python que transforma as trends de tech/AI mais quentes do X (Twitter) em um vídeo vertical narrado, pronto para publicar:

1. **Coleta** os posts das últimas 24h das **contas que você segue no X** (X API oficial v2, pay-per-use, com teto de leitura configurável) e o **GPT** os sumariza nas **10 trends mais quentes** — notícias, lançamentos, novidades, curiosidades e tretas — cada uma com resumo, engajamento e uma nota de apelo visual. A lista de seguidos fica em cache local por 7 dias; `X_ACCOUNTS` permite fixar contas específicas no lugar dela.
2. **GPT 5.6 Luna** pontua cada candidata em **acessibilidade pré-conceitual** (1 a 5): o público de Shorts é passivo, então **só vira vídeo notícia com score >= 4** — evento físico/visual (explosão, desastre, confronto) ou ação humana dramática (ameaça de líder, prisão, escândalo), sempre com **imagem mental instantânea**. Score e justificativa de **todas** as candidatas (inclusive rejeitadas) são logados; sem aprovadas, não há vídeo no dia.
3. **GPT 5.6 Luna** escolhe a trend entre as aprovadas priorizando **posts com vídeo**, depois **com foto** e, por último, **só texto** (aí as imagens vêm todas do Firecrawl). Antes de decidir, recebe os **últimos 9 vídeos já publicados no canal selecionado** (lidos da própria YouTube Data API) e é instruído a **não repetir tema recente** — só repete um assunto se houver novidade real.
4. **Firecrawl (sources=news)** busca **notícias recentes** sobre a trend escolhida (título, link, resumo e data) para complementar o material com fatos, nomes e números corretos.
5. **GPT 5.6 Luna** escreve o roteiro **pré-conceitual em tom adulto**: para um adulto leigo (o público real: homens de 25-54) com metade da atenção — frases **curtas** (mira em 8 palavras, máximo 12), uma ideia por frase, **vocabulário do dia a dia** (sem jargão nem siglas), tom de furo de notícia (nunca infantil), estrutura fixa **HOOK (imagem chocante, 0-2s) → FATO (até a metade) → IMPLICAÇÃO única (segunda metade) → CORTE em tensão que emenda no hook (loop)**, sem CTA falado. O título promete **exatamente** o que o vídeo entrega (1 fato real + 1 implicação — clickbait sem payload é proibido). O roteiro inclui **audio tags** (`[excited]`, `[whispers]`…) que ditam o tom da voz e define de **8 a 10 imagens-chave**.
6. **Firecrawl Search** encontra as **imagens reais** na web — fotos jornalísticas do próprio fato (pessoas, eventos e produtos), nada gerado por IA.
7. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere) e o pipeline **corta os silêncios** da narração (remapeando os timestamps para as legendas continuarem sincronizadas), deixando o áudio sem trechos parados.
8. **ffmpeg** monta o vídeo vertical: o **fundo de cada momento é a própria imagem daquele trecho, ampliada para cobrir a tela e borrada**; por cima entra a **imagem nítida em largura total com zoom suave** (Ken Burns). As imagens **cobrem 100% da narração** (nunca há um instante sem figura) e fazem **crossfade** entre si — de **8 a 10 imagens**, até **10 segundos** cada. **Legendas** sincronizadas palavra a palavra são queimadas no vídeo, e o **branding** (logo do YouTube Shorts + `@usuário`) fica no topo **com borda branca**.
9. O `.mp4` final vai para `output/`, é registrado em `videos.txt` e publicado automaticamente no **YouTube** (Data API v3). Roda sempre, independente da flag `-usa`.

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH. No Windows: `winget install Gyan.FFmpeg` (reabra o terminal depois)
- O fundo é montado a partir das próprias imagens (não há fundo de cor); a resolução (padrão vertical 9:16, `1080x1920`) é configurável por `VIDEO_LARGURA`/`VIDEO_ALTURA`.
- Chaves de API (quatro):
  - **OpenAI** — em [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (sumarização das trends, roteiro e descrição das mídias com `gpt-5.6-luna`).
  - **X API** — Consumer Key + Secret do app em [developer.x.com](https://developer.x.com) (coleta dos posts de quem você segue e download das mídias; pay-per-use).
  - **Firecrawl** — em [firecrawl.dev](https://firecrawl.dev) (busca das imagens via Search API com `sources=["images"]`).
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
python main.py        # público brasileiro (conteúdo em português)
python main.py -usa   # público americano (tudo em inglês)
```

Com `-usa`, todo o material — escolha do tema, título, descrição, texto narrado e hashtags — é produzido em inglês americano e direcionado 100% ao público dos EUA (a coleta também prioriza o que está dominando a conversa por lá), e a narração usa a voz americana configurada em `ELEVENLABS_VOICE_ID_USA`.

O resultado fica em uma pasta por execução:

```
output/
└── 2026-06-10_titulo-do-dia/
    ├── roteiro.json     # tema, título, descrição, texto e consultas de imagem
    ├── imagem_1.jpg …   # imagens-chave baixadas da web
    ├── narracao.mp3     # narração TTS
    └── video_final.mp4  # este é o que você publica
```

## Ajustes no .env

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `X_USERNAME` | — | Seu @ no X (sem @): a coleta pega os posts das contas que você segue |
| `X_ACCOUNTS` | vazio | Opcional: usa somente estas contas no lugar da lista de seguidos |
| `X_MAX_POSTS` | `60` | Teto de posts lidos por execução (a X API cobra por post lido) |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados |
| `NUM_TRENDS` | `10` | Quantas trends mais faladas do X coletar para escolher a do vídeo |
| `NUM_NOTICIAS` | `6` | Quantas notícias (Firecrawl news) buscar para enriquecer a trend |
| `TEXT_MODEL` | `gpt-5.6-luna` | Modelo do roteiro, da sumarização das trends e da visão |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `45` | Duração-alvo da narração em segundos (a duração final segue o áudio; com o corte de silêncios, 45s de alvo ≈ vídeo final de ~29s, a faixa que melhor retém) |
| `VIDEO_LARGURA` | `1080` | Largura do vídeo |
| `VIDEO_ALTURA` | `1920` | Altura do vídeo |
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

Os dois usam o mesmo `YOUTUBE_CLIENT_ID`/`YOUTUBE_CLIENT_SECRET` — muda só qual canal você seleciona no consentimento. Se você só configurar um dos tokens, o outro modo apenas avisa e pula a publicação (sem derrubar a execução).

Se as credenciais estiverem ausentes ou o upload falhar (rede, quota, token), o erro é apenas avisado — o vídeo continua salvo em `output/` e registrado em `videos.txt`.

## Como funciona o corte de silêncios

Depois da narração, o ffmpeg (`silencedetect`) localiza os silêncios e o pipeline os corta (`aselect`), deixando uma pequena folga em cada um para o áudio não ficar com trechos parados. O ponto crítico: os timestamps do alinhamento da ElevenLabs são **remapeados** para o novo áudio, então as legendas e a sincronização das imagens continuam corretas. Se não houver silêncio relevante (ou faltar ffmpeg), o áudio original é mantido. O roteiro também é escrito para ser dinâmico, rápido e direto ao ponto, reduzindo as pausas na origem.

## Como funcionam as legendas

A ElevenLabs retorna o tempo de fala de cada caractere (`/with-timestamps`), e o pipeline agrupa as palavras em legendas curtas (até ~18 caracteres), gravadas em `legendas.ass` e queimadas no vídeo pelo ffmpeg. Como sempre há imagem na tela, as legendas ficam na **parte inferior** (a 20% de altura) para não cobrir a imagem nítida. O estilo é texto **preto com borda branca**, na fonte **Barlow** (em `fonts/Barlow-Bold.ttf`; a Futura é comercial e não pode ser distribuída com o projeto — se você a tiver licenciada, basta trocar o `Fontname` em `pipeline/legendas.py`). O arquivo `alinhamento.json` de cada execução guarda os timestamps para depuração.

## Como funcionam as imagens-chave

O GPT define, para cada imagem, uma **consulta de busca** coerente com o fato da notícia (ex.: "Sam Altman GPT-6 launch keynote 2026") e o **trecho exato da narração** em que ela deve aparecer. Cada consulta vira uma chamada à **Firecrawl Search API** (`sources=["images"]`); o pipeline usa a URL original de cada resultado (`imageUrl`) e, como reserva, a página de origem (`url`), de onde tenta a og:image. As buscas rodam em sequência com um pequeno intervalo entre elas. O pipeline tenta os candidatos em ordem (maior resolução primeiro), segue para a og:image quando a URL é uma página, e valida o conteúdo (JPG/PNG/WebP, tamanho mínimo). Na montagem, as **8 a 10 imagens** cobrem 100% da narração (sem instante vazio): cada uma entra na janela proporcional à posição do seu trecho e fica na tela até a próxima começar (no máximo **10 segundos**), com **crossfade** na transição. O **fundo** é a própria imagem ampliada para cobrir a tela e **borrada**; por cima, a **imagem nítida em largura total com zoom suave**. Se uma busca não retornar imagem válida, ela é pulada e o vídeo segue com as demais.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (X API pay-per-use, ~US$ 0,005/post, teto `X_MAX_POSTS`) | ~US$ 0,30 com o padrão de 60 posts |
| Mídias dos posts da trend (X API, até 5 posts) | ~US$ 0,03 |
| Busca de imagens + notícias (Firecrawl Search) | ~2 créditos por consulta |
| GPT 5.6 Luna (sumarização das trends + seleção + roteiro + visão das mídias) | < US$ 0,04 |
| ElevenLabs (~1.000 caracteres por narração de 60s) | ~1.000 créditos do plano |

A lista de quem você segue é lida no máximo 1x por semana (cache em `seguindo.json`). O maior custo de API é a leitura de posts do X — ajuste `X_MAX_POSTS` para equilibrar cobertura e preço. O custo fixo segue sendo o plano da ElevenLabs: o gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana.

## Problemas comuns

- **Erro na coleta de posts** — confira `X_CONSUMER_KEY`/`X_CONSUMER_SECRET` e o saldo/plano do app em [developer.x.com](https://developer.x.com). Se a leitura da lista de seguidos for negada (403), preencha `X_ACCOUNTS` no `.env` com as contas desejadas.
- **Trocou as contas que segue e a coleta não refletiu** — apague `seguindo.json` (cache de 7 dias da lista de seguidos).
- **Erro/429 na busca de imagens** — confira a `FIRECRAWL_API_KEY` e o saldo de créditos no [dashboard do Firecrawl](https://firecrawl.dev); o pipeline já espaça as buscas e tenta de novo em 429.
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Imagem-chave ruim/errada** — apague a pasta da execução e rode de novo; os resultados do Firecrawl variam. Dá para editar `roteiro.json` e ajustar as consultas manualmente também.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 3)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` (e `--auth-youtube-usa`) de novo para reautorizar com o escopo de leitura. Sem isso, o vídeo ainda é gerado, só sem o filtro anti-repetição.
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
