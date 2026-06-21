# Automação de Vídeos — Notícias Tech & AI

Pipeline em Python que transforma as notícias de tech/AI mais quentes do X (Twitter) em um vídeo vertical narrado, pronto para publicar:

1. **Coleta** as threads de tech/AI mais discutidas das últimas 24h no X usando a **X Search da xAI** (com `from_date`/`to_date`). Opcionalmente restringe a contas específicas.
2. **GPT 5.4 mini** escolhe o tema do dia e gera título, descrição e o texto do vídeo (~60 segundos de narração). Antes de decidir, recebe os **últimos 9 vídeos já publicados no canal selecionado** (lidos da própria YouTube Data API, então funciona em qualquer ambiente, sem depender de estado local) e é instruído a **não repetir tema recente** — só repete um assunto se houver novidade real, e nesse caso deixa claro o que mudou.
3. **Firecrawl Search** encontra de **4 a 6 imagens reais** na web — fotos jornalísticas do próprio fato (pessoas, eventos e produtos da notícia), nada gerado por IA. As consultas são geradas para serem coerentes com a notícia, não ilustrações genéricas.
4. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere). O roteiro inclui **audio tags** (`[excited]`, `[whispers]`, `[sighs]`…) que ditam o tom e a emoção da voz — elas não são faladas nem aparecem nas legendas.
5. **ffmpeg** monta o vídeo sobre um **fundo branco**: cada imagem-chave entra **centralizada ocupando toda a largura**, **estática** (até **6 segundos** cada), sincronizada com o trecho da narração a que se refere (podem aparecer já no início). **Legendas** sincronizadas palavra a palavra são queimadas no vídeo: quando **não há imagem na tela** ficam **centralizadas no meio**; quando **há imagem**, descem para a **parte inferior** (a 20% de altura) — fonte Barlow, texto preto com borda branca.
6. O `.mp4` final vai para `output/` e a entrada (arquivo + título + descrição) é registrada em `videos.txt`.
7. **YouTube** — o vídeo é publicado automaticamente no canal (Data API v3), usando o título e a descrição do roteiro. Roda sempre, independente da flag `-usa`.

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH. No Windows: `winget install Gyan.FFmpeg` (reabra o terminal depois)
- O fundo é uma tela branca gerada pelo próprio ffmpeg; a resolução (padrão vertical 9:16, `1080x1920`) é configurável por `VIDEO_LARGURA`/`VIDEO_ALTURA`.
- Chaves de API (quatro):
  - **OpenAI** — em [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (roteiro com `gpt-5.4-mini`).
  - **xAI** — em [console.x.ai](https://console.x.ai) (coleta de posts via X Search).
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
| `X_ACCOUNTS` | vazio | Opcional: restringe a busca a contas específicas (máx. 20). Vazio = threads mais discutidas do dia |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados |
| `TEXT_MODEL` | `gpt-5.4-mini` | Modelo do roteiro |
| `SEARCH_MODEL` | `grok-4.3` | Modelo da xAI para a X Search (coleta de posts) |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `60` | Duração-alvo da narração em segundos (a duração final segue o áudio) |
| `VIDEO_LARGURA` | `1080` | Largura do vídeo (fundo branco) |
| `VIDEO_ALTURA` | `1920` | Altura do vídeo (fundo branco) |
| `YOUTUBE_CLIENT_ID` | — | Client ID OAuth (Google Cloud, tipo "Desktop app") |
| `YOUTUBE_CLIENT_SECRET` | — | Client secret OAuth |
| `YOUTUBE_REFRESH_TOKEN` | — | Canal português; preenchido por `--auth-youtube` |
| `YOUTUBE_REFRESH_TOKEN_USA` | — | Canal inglês (`-usa`); preenchido por `--auth-youtube-usa` |
| `YOUTUBE_PRIVACY` | `public` | `public`, `unlisted` ou `private` |
| `YOUTUBE_CATEGORY_ID` | `28` | Categoria do YouTube (28 = Science & Technology) |

## Publicação automática no YouTube

A publicação usa a **YouTube Data API v3** com OAuth e roda sempre, em qualquer modo (`-usa` ou não). A autorização pede o conjunto completo de escopos do YouTube (publicar, ler e gerenciar), então o mesmo refresh token também é usado para ler os últimos vídeos do canal (passo 2 do fluxo) e cobre features futuras sem reautenticar. Configure uma vez:

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

## Como funcionam as legendas

A ElevenLabs retorna o tempo de fala de cada caractere (`/with-timestamps`), e o pipeline agrupa as palavras em legendas curtas (até ~18 caracteres), gravadas em `legendas.ass` e queimadas no vídeo pelo ffmpeg. Quando **não há imagem na tela**, a legenda aparece **centralizada no meio**; quando **há imagem**, desce para a **parte inferior** (a 20% de altura) para não cobri-la. O estilo é texto **preto com borda branca**, na fonte **Barlow** (em `fonts/Barlow-Bold.ttf`; a Futura é comercial e não pode ser distribuída com o projeto — se você a tiver licenciada, basta trocar o `Fontname` em `pipeline/legendas.py`). O arquivo `alinhamento.json` de cada execução guarda os timestamps para depuração.

## Como funcionam as imagens-chave

O GPT define, para cada imagem, uma **consulta de busca** coerente com o fato da notícia (ex.: "Sam Altman GPT-6 launch keynote 2026") e o **trecho exato da narração** em que ela deve aparecer. Cada consulta vira uma chamada à **Firecrawl Search API** (`sources=["images"]`); o pipeline usa a URL original de cada resultado (`imageUrl`) e, como reserva, a página de origem (`url`), de onde tenta a og:image. As buscas rodam em sequência com um pequeno intervalo entre elas. O pipeline tenta os candidatos em ordem (maior resolução primeiro), segue para a og:image quando a URL é uma página, e valida o conteúdo (JPG/PNG/WebP, tamanho mínimo). Na montagem, cada imagem entra na janela de tempo proporcional à posição do trecho na narração — centralizada sobre o fundo branco, em largura total, **estática**, por **até 6 segundos**. Se uma busca não retornar imagem válida, ela é pulada e o vídeo segue com as demais.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta de posts (xAI: tokens grok-4.3 + tools a US$ 5/1.000 chamadas) | ~US$ 0,05–0,12 |
| Busca de imagens (Firecrawl Search) | ~2 créditos por consulta |
| GPT 5.4 mini (roteiro) | < US$ 0,01 |
| ElevenLabs (~1.000 caracteres por narração de 60s) | ~1.000 créditos do plano |

Em dinheiro de API (xAI + OpenAI + Firecrawl), cada vídeo sai por **centavos**. O custo real vira o plano da ElevenLabs: o plano gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana. Total estimado: **~US$ 6–7/mês**.

## Problemas comuns

- **Erro na coleta de posts** — verifique o saldo de créditos da xAI no [console.x.ai](https://console.x.ai).
- **Erro/429 na busca de imagens** — confira a `FIRECRAWL_API_KEY` e o saldo de créditos no [dashboard do Firecrawl](https://firecrawl.dev); o pipeline já espaça as buscas e tenta de novo em 429.
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **Imagem-chave ruim/errada** — apague a pasta da execução e rode de novo; os resultados do Firecrawl variam. Dá para editar `roteiro.json` e ajustar as consultas manualmente também.
- **Refresh token do YouTube expira em ~7 dias** — a tela de consentimento OAuth está em modo **Testing**. Publique-a (**OAuth consent screen > Publish app**) para o refresh token virar de longa duração, e rode `--auth-youtube` de novo.
- **`refresh_token` não retornado no `--auth-youtube`** — o Google só o devolve no primeiro consentimento. Remova o acesso em [myaccount.google.com/permissions](https://myaccount.google.com/permissions) e rode de novo.
- **Não lê os últimos vídeos do canal (passo 2)** — tokens autorizados antes da ampliação de escopos só tinham `youtube.upload`. Rode `--auth-youtube` (e `--auth-youtube-usa`) de novo para reautorizar com o escopo de leitura. Sem isso, o vídeo ainda é gerado, só sem o filtro anti-repetição.
- **Upload do YouTube falha com 403 (quota)** — cada upload consome 1.600 unidades; a cota padrão é 10.000/dia (~6 vídeos). Peça aumento no Google Cloud se precisar de mais.
