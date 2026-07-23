# Automação de Vídeos — Geopolítica, Inteligência, IA & Tech

Pipeline em Python que transforma as trends mais quentes de geopolítica, inteligência, IA e tech no X (Twitter) em um vídeo vertical narrado, em formato explicativo (análise/educacional), pronto para publicar:

1. **Coleta** os posts das últimas 24h da **lista fixa de contas** do canal (`CONTAS_PADRAO` em `pipeline/config.py`; `X_ACCOUNTS` no `.env` a substitui) via X API oficial v2, pay-per-use, com teto de leitura configurável, e o **GPT** os sumariza nas **10 trends mais quentes** — notícias, lançamentos, novidades, curiosidades e tretas — cada uma com resumo, engajamento e uma nota de apelo visual.
2. **GPT 5.6 Luna** classifica cada candidata (**macrotema** + **imagem mental**) — sem filtro nem score: todas as candidatas seguem vivas para a seleção.
3. **GPT 5.6 Luna** escolhe a trend guiado **somente pela audiência**: recebe os **últimos 100 vídeos publicados no canal selecionado com as métricas reais** (views/likes em tempo real, YouTube Data API) e os **campeões de retenção** (YouTube Analytics), e escolhe a candidata com a maior chance de performar com esse público — repetir o tipo de conteúdo que está performando é bem-vindo. Duas regras duras, aplicadas em código: **o mesmo macrotema não emenda mais de 4 vídeos seguidos** e a **verificação anti-repetição** — o GPT confere se a escolhida cobriria o **mesmo fato** de um vídeo publicado nas últimas 36h sem desenvolvimento novo; se sim, ela sai da disputa e a seleção refaz (se todas as candidatas caírem em uma das regras, não há vídeo).
4. **Firecrawl (sources=news)** busca **notícias recentes** sobre a trend escolhida (título, link, resumo e data) para complementar o material com fatos, nomes e números corretos (falha aqui não aborta: o roteiro segue com o resumo e os posts do X).
5. **GPT 5.6 Luna** escreve o roteiro **explicativo (análise/educacional) em tom adulto**, **sempre citando as fontes** (as contas do X que originaram a trend e os veículos das notícias do Firecrawl): para um adulto leigo (o público real: homens de 25-54) com metade da atenção — frases com **ritmo de fala natural** (8 a 16 palavras, teto 20, alternando curtas de impacto com mais cheias), uma ideia por frase, **vocabulário preciso de telejornal** (sem jargão de nicho nem sigla sem explicação), tom de furo de notícia (nunca infantil), estrutura fixa **HOOK (imagem chocante, 0-2s) → FATO (até a metade, com âncora pró-leigo quando o assunto é de nicho) → IMPLICAÇÃO única (segunda metade) → CORTE em tensão que emenda no hook (loop)**, sem CTA falado. O **título e a descrição são autossuficientes** (teste do leigo: sem nome de nicho, sem cauda de suspense; a descrição entrega o fato com a fonte, não é teaser) e prometem **exatamente** o que o vídeo entrega. Uma **auditoria pró-leigo** (chamada própria ao GPT) confere título, descrição e narração contra essas regras e pede **uma reescrita** quando reprova. O roteiro inclui **audio tags** (`[excited]`, `[whispers]`…) que ditam o tom da voz e define de **8 a 10 imagens-chave**.
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
  - **X API** — Consumer Key + Secret do app em [developer.x.com](https://developer.x.com) (coleta dos posts das contas acompanhadas e download das mídias; pay-per-use).
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

O pipeline é **fail-fast**: credenciais ausentes/quebradas, falha ao ler os últimos vídeos ou os campeões de retenção, classificação indisponível, verificação de vídeo repetido indisponível e falha no upload — tudo isso derruba a execução com erro explícito (para o agendador poder alertar), em vez de seguir e degradar o vídeo em silêncio. As leituras do canal acontecem logo no início, antes de qualquer chamada paga (X/OpenAI). **Exceção (Firecrawl)**: falha na busca de notícias ou de imagens só gera aviso no log e a execução segue (o roteiro sai do resumo/posts do X; o vídeo, das mídias do X) — aborta somente se não sobrar **nenhum** material visual. Se o upload falhar, o vídeo continua salvo em `output/` e registrado em `videos.txt` para publicação manual.

## Como funciona o corte de silêncios

Depois da narração, o ffmpeg (`silencedetect`) localiza os silêncios e o pipeline os corta (`aselect`), deixando uma pequena folga em cada um para o áudio não ficar com trechos parados. O ponto crítico: os timestamps do alinhamento da ElevenLabs são **remapeados** para o novo áudio, então as legendas e a sincronização das imagens continuam corretas. Se não houver silêncio relevante (ou faltar ffmpeg), o áudio original é mantido. O roteiro também é escrito para ser dinâmico, rápido e direto ao ponto, reduzindo as pausas na origem.

## Como funcionam as legendas

A ElevenLabs retorna o tempo de fala de cada caractere (`/with-timestamps`), e o pipeline agrupa as palavras em legendas curtas (até ~18 caracteres), gravadas em `legendas.ass` e queimadas no vídeo pelo ffmpeg. Como sempre há imagem na tela, as legendas ficam na **parte inferior** (a 20% de altura) para não cobrir a imagem nítida. O estilo é texto **preto com borda branca**, na fonte **Barlow** (em `fonts/Barlow-Bold.ttf`; a Futura é comercial e não pode ser distribuída com o projeto — se você a tiver licenciada, basta trocar o `Fontname` em `pipeline/legendas.py`). O arquivo `alinhamento.json` de cada execução guarda os timestamps para depuração.

## Como funcionam as imagens-chave

O GPT define, para cada imagem, uma **consulta de busca** coerente com o fato da notícia (ex.: "Sam Altman GPT-6 launch keynote 2026") e o **trecho exato da narração** em que ela deve aparecer. Cada consulta vira uma chamada à **Firecrawl Search API** (`sources=["images"]`); o pipeline usa a URL original de cada resultado (`imageUrl`) e, como reserva, a página de origem (`url`), de onde tenta a og:image. As buscas rodam em sequência com um pequeno intervalo entre elas. O pipeline tenta os candidatos em ordem (maior resolução primeiro), segue para a og:image quando a URL é uma página, e valida o conteúdo (JPG/PNG/WebP, tamanho mínimo). Na montagem, as **8 a 10 imagens** cobrem 100% da narração (sem instante vazio): cada uma entra na janela proporcional à posição do seu trecho e fica na tela até a próxima começar (no máximo **10 segundos**), com **crossfade** na transição. O **fundo** é a própria imagem ampliada para cobrir a tela e **borrada**; por cima, a **imagem nítida em largura total com zoom suave**. Se uma busca não retornar imagem válida, ela é pulada e o vídeo segue com as demais.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (X API pay-per-use, ~US$ 0,005/post, teto `X_MAX_POSTS`) | ~US$ 1,00 com o padrão de 200 posts |
| Mídias dos posts da trend (X API, até 5 posts) | ~US$ 0,03 |
| Busca de imagens + notícias (Firecrawl Search) | ~2 créditos por consulta |
| GPT 5.6 Luna (sumarização das trends + seleção + roteiro + visão das mídias) | < US$ 0,04 |
| ElevenLabs (~1.000 caracteres por narração de 60s) | ~1.000 créditos do plano |

O maior custo de API é a leitura de posts do X — ajuste `X_MAX_POSTS` para equilibrar cobertura e preço. O custo fixo segue sendo o plano da ElevenLabs: o gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana.

## Problemas comuns

- **Erro na coleta de posts** — confira `X_CONSUMER_KEY`/`X_CONSUMER_SECRET` e o saldo/plano do app em [developer.x.com](https://developer.x.com).
- **Quer mudar as contas acompanhadas** — edite `CONTAS_PADRAO` em `pipeline/config.py`, ou preencha `X_ACCOUNTS` no `.env` para substituir a lista sem mexer no código.
- **Erro/429 na busca de imagens** — confira a `FIRECRAWL_API_KEY` e o saldo de créditos no [dashboard do Firecrawl](https://firecrawl.dev); o pipeline já espaça as buscas e tenta de novo em 429.
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Imagem-chave ruim/errada** — apague a pasta da execução e rode de novo; os resultados do Firecrawl variam. Dá para editar `roteiro.json` e ajustar as consultas manualmente também.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 3)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` (e `--auth-youtube-usa`) de novo para reautorizar com os escopos de leitura. Sem isso a execução aborta logo no início (a leitura alimenta a seleção guiada pela audiência e o teto de macrotemas seguidos).
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
