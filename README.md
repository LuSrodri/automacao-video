# Automação de Vídeos — Notícias Tech & AI

Pipeline em Python que transforma posts recentes do X (Twitter) em um vídeo curto pronto para publicar:

1. **Coleta** as threads de tech/AI mais discutidas das últimas 24h no X usando a ferramenta **X Search da xAI** (sem precisar de conta na X API). Opcionalmente, dá para restringir a contas específicas.
2. **GPT 5.4 mini** escolhe o tema do dia e gera título, descrição e o texto do vídeo.
3. **OpenAI Images** gera de 1 a 3 imagens-chave em PNG com fundo transparente — sempre logos de marcas ou figuras públicas ligadas à notícia, em estilo caricato.
4. **Grok Imagine 1.5** (xAI) anima a imagem base `clipe.png` usando o texto do vídeo como prompt, com instrução para não renderizar textos/legendas no vídeo.
5. **ffmpeg** sobrepõe as imagens-chave centralizadas na tela, cada uma na janela de tempo do trecho da narração a que se refere.
6. O `.mp4` final vai para `output/` e a entrada (arquivo + título + descrição) é registrada em `videos.txt`.

## Pré-requisitos

- **Python 3.10+**
- **ffmpeg** no PATH. No Windows: `winget install Gyan.FFmpeg` (reabra o terminal depois)
- Chaves de API (apenas duas):
  - **OpenAI** — em [platform.openai.com/api-keys](https://platform.openai.com/api-keys), com acesso aos modelos `gpt-5.4-mini` e `gpt-image-1.5`/`gpt-image-2` (geração de imagem pode exigir verificação da organização).
  - **xAI** — em [console.x.ai](https://console.x.ai). A mesma chave e os mesmos créditos cobrem a coleta de posts (ferramenta X Search, US$ 5/1.000 buscas) e a geração do vídeo (`grok-imagine-video`). Não é preciso ter conta na X API.

## Configuração inicial (uma vez só)

```powershell
# 1. Crie o ambiente virtual e instale as dependências
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Crie o .env a partir do exemplo e preencha as chaves
Copy-Item .env.example .env
notepad .env

# 3. Coloque a imagem base do vídeo na raiz do projeto
#    (é ela que o Grok Imagine vai animar)
#    -> clipe.png
```

Por padrão a coleta busca as threads de tech/AI mais discutidas do dia no X inteiro. Se preferir limitar a fontes específicas, preencha `X_ACCOUNTS` no `.env` (contas separadas por vírgula, sem `@`).

## Rodando

Toda vez que quiser gerar o vídeo do dia:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

O resultado fica em uma pasta por execução, por exemplo:

```
output/
└── 2026-06-09_openai-lanca-novo-modelo/
    ├── roteiro.json     # tema, título, descrição, texto e prompts gerados
    ├── imagem_1.png     # imagens-chave (fundo transparente)
    ├── imagem_2.png
    ├── video_bruto.mp4  # saída do Grok Imagine
    └── video_final.mp4  # vídeo editado (este é o que você publica)
```

E o `videos.txt` na raiz acumula o histórico:

```
data: 2026-06-09 14:32
arquivo: ...\output\2026-06-09_openai-lanca-novo-modelo\video_final.mp4
titulo: OpenAI lança novo modelo
descricao: ...
---
```

## Ajustes no .env

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `X_ACCOUNTS` | vazio | Opcional: restringe a busca a contas específicas (separadas por vírgula, máx. 20). Vazio = threads mais discutidas do dia |
| `JANELA_HORAS` | `24` | Idade máxima dos posts coletados |
| `TEXT_MODEL` | `gpt-5.4-mini` | Modelo de texto (tema, título, descrição, roteiro) |
| `SEARCH_MODEL` | `grok-4.3` | Modelo da xAI que executa a X Search na coleta |
| `IMAGE_MODEL` | `gpt-image-1.5` | Modelo das imagens-chave |
| `VIDEO_MODEL` | `grok-imagine-video-1.5-preview` | Modelo de vídeo da xAI (`grok-imagine-video` é a opção estável e mais barata) |
| `VIDEO_DURACAO` | `20` | Duração total em segundos (1–25) |
| `VIDEO_RESOLUCAO` | `480p` | `480p` (US$ 0,05/seg) ou `720p` (US$ 0,07/seg) |
| `VIDEO_ASPECT_RATIO` | `9:16` | Proporção do vídeo (`9:16`, `16:9`, `1:1`, `4:3`, `3:4`, `3:2`, `2:3`) |

### Como funcionam os 20 segundos

Durações acima de 10s são divididas em **segmentos de até 10s**, todos gerados **em paralelo** a partir do mesmo `clipe.png` — o texto do vídeo é repartido proporcionalmente entre eles, então cada segmento narra a sua parte. Ao final, o ffmpeg concatena tudo na ordem da narração. Com `VIDEO_DURACAO=20`, são 2 segmentos de 10s (duas chamadas cobradas ao Grok Imagine, mas que rodam ao mesmo tempo). Como cada segmento parte da mesma imagem base, há um corte de cena na junção — efeito de "novo take", comum em vídeos curtos. O limite total do pipeline é 25s.

### Sobre a proporção 9:16

A proporção é aplicada na geração. Como a fonte é o `clipe.png`, **use uma imagem já em 9:16** (ex.: 1080×1920); se o arquivo tiver outra proporção, a API estica a imagem para encaixar no formato, distorcendo o resultado.

### Como funcionam as imagens-chave

O GPT define para cada imagem um **logo de marca ou figura pública** ligada à notícia (estilo caricato) e o **trecho exato da narração** em que ela deve aparecer. O pipeline posiciona cada imagem na janela de tempo proporcional à posição desse trecho no texto, centralizada na tela com ~55% da largura do vídeo. Se a moderação da OpenAI recusar alguma figura pública, aquela imagem é pulada e o vídeo segue com as demais.

## Custo estimado por vídeo

Com os padrões do projeto (20s, 480p, busca aberta de trending), cada execução custa por volta de **US$ 1,75–2,20**:

| Etapa | Custo |
| --- | --- |
| Coleta via X Search da xAI (tokens do grok-4.3 + buscas a US$ 5/1.000) | ~US$ 0,03–0,06 |
| GPT 5.4 mini (roteiro) | < US$ 0,01 |
| gpt-image-1.5 (1–3 imagens) | US$ 0,10–0,50 |
| Grok Imagine 1.5 — 2×10s @ 480p (20s gerados + 2 entradas de imagem) | ~US$ 1,62 |

O `grok-imagine-video-1.5-preview` custa US$ 0,08/seg em 480p (US$ 0,14/seg em 720p) + US$ 0,01 por imagem de entrada. Usar `VIDEO_MODEL=grok-imagine-video` (US$ 0,05/seg) derruba o vídeo para ~US$ 1,02. Preços de junho/2026; confira as páginas de pricing da xAI e da OpenAI antes de escalar.

## Observação importante sobre as imagens transparentes

Pela documentação oficial da OpenAI, o **`gpt-image-2` não suporta fundo transparente** — requisições com `background: "transparent"` são rejeitadas para esse modelo. Quem suporta transparência nativa é o **`gpt-image-1.5`**, que por isso é o padrão do projeto.

Se você definir `IMAGE_MODEL=gpt-image-2`, o script detecta a rejeição, gera a imagem sem o parâmetro e avisa no console — mas nesse caso o PNG pode vir com fundo, e o overlay no vídeo fica como um cartão retangular em vez de um elemento recortado.

## Problemas comuns

- **Erro na coleta de posts** — verifique o saldo de créditos da xAI no [console.x.ai](https://console.x.ai) (a coleta usa a ferramenta X Search). Se a resposta vier sem JSON, rode de novo; o script mostra o trecho recebido para diagnóstico.
- **`ffmpeg não encontrado no PATH`** — instale o ffmpeg e reabra o terminal para o PATH atualizar.
- **Timeout no Grok Imagine** — a geração pode levar alguns minutos; o script aguarda até 15. Se estourar, rode de novo (o console da xAI também mostra o status pelo `request_id` impresso no log).
- **`Imagem base não encontrada`** — falta o `clipe.png` na raiz do projeto.
