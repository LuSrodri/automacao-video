# Automação de Vídeos — Notícias Tech & AI

Pipeline em Python que transforma as notícias de tech/AI mais quentes do X (Twitter) em um vídeo vertical narrado, pronto para publicar:

1. **Coleta** as threads de tech/AI mais discutidas das últimas 24h no X usando a **X Search da xAI** (com `from_date`/`to_date`). Opcionalmente restringe a contas específicas.
2. **GPT 5.4 mini** escolhe o tema do dia e gera título, descrição e o texto do vídeo (~60 segundos de narração).
3. **Web Search da xAI** (modo image search) encontra de **3 a 5 imagens reais** na web — logos, fotos de figuras públicas, produtos — nada gerado por IA.
4. **ElevenLabs** narra o texto (modelo `eleven_v3`, com timestamps por caractere). O roteiro inclui **audio tags** (`[excited]`, `[whispers]`, `[sighs]`…) que ditam o tom e a emoção da voz — elas não são faladas nem aparecem nas legendas.
5. **ffmpeg** monta o vídeo: os **vídeos de fundo pré-gravados são intercalados em ordem aleatória** (sem repetir o mesmo em sequência, mudos) até cobrir a narração; cada imagem-chave entra **centralizada ocupando toda a largura**, com **zoom-in lento**, enquanto o **fundo fica borrado**; as imagens aparecem sincronizadas com o trecho da narração a que se referem. **Legendas** sincronizadas palavra a palavra são queimadas no vídeo: durante a primeira frase aparecem centralizadas na tela, depois centralizadas na parte inferior — fonte Barlow, texto preto com borda branca.
6. O `.mp4` final vai para `output/` e a entrada (arquivo + título + descrição) é registrada em `videos.txt`.

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH. No Windows: `winget install Gyan.FFmpeg` (reabra o terminal depois)
- **Vídeos de fundo** na raiz do projeto, casando com o padrão `FUNDO_GLOB` (padrão: `av paulista*.mp4`). Ideal: verticais 9:16; eles são sorteados a cada execução e rodam em loop, sem áudio.
- Chaves de API (três):
  - **OpenAI** — em [platform.openai.com/api-keys](https://platform.openai.com/api-keys) (roteiro com `gpt-5.4-mini`).
  - **xAI** — em [console.x.ai](https://console.x.ai) (coleta de posts via X Search + busca de imagens via Web Search).
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

# 3. Coloque os vídeos de fundo na raiz do projeto
#    (ex.: "av paulista 1.mp4", "av paulista 2.mp4", "av paulista 3.mp4")
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
| `SEARCH_MODEL` | `grok-4.3` | Modelo da xAI para X Search e Web Search |
| `ELEVENLABS_VOICE_ID` | `czvzJwIVS2asEKnthV40` | Voz da narração em português ([voice library](https://elevenlabs.io/app/voice-library)) |
| `ELEVENLABS_VOICE_ID_USA` | `POPWFdpTM8Mn2ZQEagyQ` | Voz da narração no modo `-usa` |
| `ELEVENLABS_MODEL` | `eleven_v3` | Modelo TTS (suporta português e audio tags de emoção) |
| `VIDEO_DURACAO` | `60` | Duração-alvo da narração em segundos (a duração final segue o áudio) |
| `FUNDO_GLOB` | `av paulista*.mp4` | Padrão dos vídeos de fundo na raiz do projeto |

## Como funcionam as legendas

A ElevenLabs retorna o tempo de fala de cada caractere (`/with-timestamps`), e o pipeline agrupa as palavras em legendas curtas (até ~18 caracteres), gravadas em `legendas.ass` e queimadas no vídeo pelo ffmpeg. A primeira frase da narração aparece **centralizada na tela** (gancho de abertura); as demais ficam **centralizadas na parte inferior**. O estilo é texto **preto com borda branca**, na fonte **Barlow** (em `fonts/Barlow-Bold.ttf`; a Futura é comercial e não pode ser distribuída com o projeto — se você a tiver licenciada, basta trocar o `Fontname` em `pipeline/legendas.py`). O arquivo `alinhamento.json` de cada execução guarda os timestamps para depuração.

## Como funcionam as imagens-chave

O GPT define, para cada imagem, uma **consulta de busca** (ex.: "OpenAI official logo", "Sam Altman portrait photo") e o **trecho exato da narração** em que ela deve aparecer. Cada consulta vira uma chamada própria ao Grok (`web_search` com `enable_image_search`, em paralelo); as URLs diretas dos arquivos vêm nas *annotations* da resposta, com os embeds markdown como reserva. O pipeline tenta os candidatos em ordem, segue para a og:image quando a URL é uma página, e valida o conteúdo (JPG/PNG/WebP, tamanho mínimo). Na montagem, cada imagem entra na janela de tempo proporcional à posição do trecho na narração — centralizada, em largura total, com zoom-in de ~12% e o fundo borrado enquanto estiver na tela. Se uma busca não retornar imagem válida, ela é pulada e o vídeo segue com as demais.

## Custo estimado por vídeo

| Etapa | Custo |
| --- | --- |
| Coleta + busca de imagens (xAI: tokens grok-4.3 + tools a US$ 5/1.000 chamadas) | ~US$ 0,05–0,12 |
| GPT 5.4 mini (roteiro) | < US$ 0,01 |
| ElevenLabs (~1.000 caracteres por narração de 60s) | ~1.000 créditos do plano |

Em dinheiro de API (xAI + OpenAI), cada vídeo sai por **centavos**. O custo real vira o plano da ElevenLabs: o plano gratuito dá 10k créditos/mês (~10 vídeos) e o **Starter (US$ 5/mês, 30k créditos)** cobre folgado 3 vídeos/semana. Total estimado: **~US$ 6–7/mês**.

## Problemas comuns

- **Erro na coleta de posts ou na busca de imagens** — verifique o saldo de créditos da xAI no [console.x.ai](https://console.x.ai).
- **HTTP 401 na ElevenLabs** — chave errada no `.env`; **422** — texto/parâmetros inválidos (a mensagem detalha).
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal.
- **`Nenhum vídeo de fundo encontrado`** — confira os arquivos na raiz e o `FUNDO_GLOB`.
- **Imagem-chave ruim/errada** — apague a pasta da execução e rode de novo; as buscas do Grok variam. Dá para editar `roteiro.json` e ajustar as consultas manualmente também.
