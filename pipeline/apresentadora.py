"""Apresentadora do Short: o vídeo dela, gerado pelo Wan, em chroma key verde.

DESENHO (2026-09-03, pedido do usuário). Até aqui o Short era narração da
ElevenLabs sobre clipe do X. Agora ele tem uma APRESENTADORA no rodapé,
recortada por chroma key, e é ELA QUEM FALA: o áudio do Short deixa de ser TTS
e passa a ser o áudio que o `wan3.0-video-prime` gera junto com a imagem dela.
A ElevenLabs continua narrando o FORMATO LONGO, que não mudou.

Três consequências que mandam no resto do pipeline, todas medidas em 2026-09-03
contra a API real (25s, 480P, 1:1, 49s entre pedido e vídeo pronto):

1. O ÁUDIO É INTOCÁVEL. Ele está preso, quadro a quadro, aos lábios dela.
   Aparar silêncio ou acelerar — as duas coisas que o Short fazia com o MP3 da
   ElevenLabs — dessincronizariam a boca. Por isso `aparar_silencios` e
   `ajustar_ao_alvo` saem do caminho do Short (main.py).

2. A DURAÇÃO VIRA PEDIDO, NÃO MEDIDA. O modelo recebe `duration` e devolve
   exatamente aquilo: no teste, as 50 palavras do roteiro couberam em
   0,0s → 24,84s dos 25s pedidos, sem cortar nada. Somem a segunda tentativa de
   narração e a faixa de velocidade — o texto não precisa mais ser reescrito
   para caber, porque quem se ajusta ao tempo é a fala dela.

3. ELA FALA MAIS DEVAGAR. 50 palavras em 25s são 2,00 palavras/s, contra as
   2,90 da ElevenLabs a 1,05x (PALAVRAS_POR_SEGUNDO=2,76). Um Short de 25s cai
   de ~72 para ~50 palavras, e é por PALAVRAS_POR_SEGUNDO_WAN que o orçamento
   do roteirista passa a ser convertido (escritor._faixa_palavras).

O que NÃO fica aqui: o alinhamento das legendas. Sem o `with-timestamps` da
ElevenLabs, ele é reconstruído transcrevendo o áudio dela
(audio.alinhar_por_transcricao), e não pelo modelo de vídeo.
"""

import json
import subprocess
import time
from base64 import b64encode
from pathlib import Path

import requests

from .config import Config

RAIZ = Path(__file__).resolve().parent.parent

# A FOTO DELA é o primeiro quadro do vídeo gerado — é o que amarra a identidade
# visual da apresentadora de um Short para o outro. Fundo verde de estúdio, já
# quadrada (1254x1254), que é a proporção em que o vídeo é pedido.
IMAGEM = RAIZ / "apresentadora.png"

API_BASE = "https://dashscope-intl.aliyuncs.com/api/v1"
ROTA_GERAR = "/services/aigc/video-generation/video-synthesis"
ROTA_TAREFA = "/tasks/"

MODELO = "wan3.0-video-prime"
# 1:1 em 480P sai em 632x632 (medido). Ela ocupa menos de 3/4 da largura do
# Short, então 480P já entrega mais pixel do que o quadro usa e 720P só
# dobraria a conta (US$ 0,068/s contra US$ 0,14/s).
RESOLUCAO = "480P"
PROPORCAO = "1:1"

# Faixa de duração do modelo. O Short cabe inteiro numa geração só.
DUR_MIN_S = 2
DUR_MAX_S = 30

# RITMO DE FALA DELA, medido (as 50 palavras faladas do roteiro em 25,0s de
# vídeo, conferidas na transcrição do áudio devolvido). É a régua que converte
# segundos em palavras no roteiro do Short, no lugar de
# PALAVRAS_POR_SEGUNDO * velocidade.
PALAVRAS_POR_SEGUNDO_WAN = 2.00

# CHROMA KEY CALIBRADO (2026-09-03), não chutado. O verde que o Wan devolve foi
# medido nos cantos de 4 quadros ao longo dos 25s: (56,175,51) com desvio de
# 5,6 no canal verde — fundo estável do começo ao fim. A varredura de
# similaridade × mistura mostrou uma janela larga em que o fundo zera o alpha e
# a apresentadora fica opaca (255) em todos os pontos de teste; 0,10/0,05 fica
# no meio dela, com folga dos dois lados. Acima de 0,15/0,05 o filtro começa a
# comer a pele dela (alpha 164 no rosto), que era o defeito da 1ª tentativa.
CHROMA_COR = "0x38AF33"
CHROMA_SIMILARIDADE = 0.10
CHROMA_MISTURA = 0.05

# SEM DESPILL, de propósito. O `despill` do ffmpeg tira o verde refletido, mas
# comparado lado a lado ele lavava a regata BRANCA dela para lilás (medido: o
# canal verde do tecido caindo de 107 para 62). A franja verde que sobra na
# borda do cabelo é pequena e some na escala em que ela entra no quadro; trocar
# a cor de uma peça de roupa por ela seria péssimo negócio.

# TAMANHO E LUGAR NO QUADRO. A fração é do LADO do quadrado sobre a LARGURA do
# vídeo: 0,72 de 1080 são 778px, e a apresentadora recortada ocupa ~435px de
# largura, com o topo da cabeça em ~61% da altura. Isso a deixa no terço de
# baixo, abaixo da legenda (centralizada na vertical, estilo "Centro" do
# legendas.py) e sem cobrir o miolo do clipe.
LARGURA_FRAC = 0.72

# Quanto esperar a fila do Wan. O teste real fechou em 49s; o teto é generoso
# porque a alternativa a esperar é perder a execução inteira do cron.
ESPERA_MAX_S = 900
ESPERA_PASSO_S = 10


def _texto_falado(texto: str) -> str:
    """Tira as audio tags do ElevenLabs (`[excited]`) do texto que vai ao Wan.

    O roteirista continua podendo escrevê-las porque o formato longo continua
    sendo narrado pela ElevenLabs, que as usa. O Wan não: ele leria "excited"
    em voz alta no meio da frase. As tags seguem no `texto_video` — é lá que as
    legendas e os cortes procuram posição de caractere, e os dois já sabem
    pular colchete.
    """
    saida, profundidade = [], 0
    for c in texto:
        if c == "[":
            profundidade += 1
            continue
        if c == "]":
            profundidade = max(0, profundidade - 1)
            continue
        if not profundidade:
            saida.append(c)
    return " ".join("".join(saida).split())


def _prompt(texto: str, publico: str) -> str:
    """O prompt do Wan: a cena, a câmera, o fundo e a fala LITERAL.

    A fala vai entre aspas e com a ordem explícita de não dizer mais nada. Foi
    assim que o teste de 2026-09-03 saiu palavra por palavra igual ao roteiro —
    a transcrição do áudio devolveu as 50 palavras do texto, na ordem.

    O fundo verde é pedido de novo aqui, em vez de confiado à foto: o modelo
    reencena os segundos inteiros, e um fundo que mudasse no meio quebraria o
    chroma key. Pedir "liso, uniforme, sem sombras" é o que segurou o desvio do
    verde em 5,6 ao longo do vídeo.
    """
    idioma = "inglês americano" if publico == "usa" else "português do Brasil"
    return (
        "A mesma mulher da imagem de referência, apresentadora de um canal de "
        "tecnologia, enquadrada da cintura para cima, em pé diante de um fundo "
        "CHROMA KEY VERDE liso, uniforme e totalmente sem textura, sem sombras "
        "e sem objetos. Câmera fixa, sem zoom, sem corte e sem movimento de "
        "câmera. Iluminação de estúdio suave. Ela olha direto para a câmera e "
        "fala com energia, gesticulando naturalmente com as mãos. Ela fala em "
        f'{idioma}, exatamente estas palavras e nada mais: "{texto}"'
    )


def _cabecalhos(cfg: Config, assincrono: bool) -> dict:
    cab = {
        "Authorization": f"Bearer {cfg.qwen_api_key}",
        "Content-Type": "application/json",
    }
    if assincrono:
        cab["X-DashScope-Async"] = "enable"
    return cab


def _abortar(motivo: str) -> None:
    """Falha de credencial ou de API aborta a execução (diretriz de 2026-07-15).

    A apresentadora não tem plano B: ela É a narração do Short desde
    2026-09-03. Seguir sem ela publicaria um vídeo mudo.
    """
    raise SystemExit(f"[apresentadora] {motivo}")


def gerar(cfg: Config, texto: str, duracao_s: float, destino: Path) -> Path:
    """Gera o vídeo da apresentadora falando `texto` em `duracao_s` segundos.

    Devolve o caminho do MP4 (632x632, 30fps, com áudio), pronto para o chroma
    key da montagem. A duração pedida é a duração entregue: o modelo ajusta o
    ritmo da fala ao tempo, não o contrário.
    """
    if not cfg.qwen_api_key:
        _abortar(
            "QWEN_API_KEY ausente — sem ela o Short sairia sem voz e sem "
            "apresentadora."
        )
    if not IMAGEM.is_file():
        _abortar(
            f"Foto da apresentadora ausente ({IMAGEM}) — é ela que fixa a "
            "identidade dela de um vídeo para o outro."
        )

    dur = int(round(max(DUR_MIN_S, min(DUR_MAX_S, duracao_s))))
    if abs(dur - duracao_s) > 0.6:
        print(
            f"[apresentadora] aviso: duração pedida de {duracao_s:.1f}s "
            f"ajustada para {dur}s (o modelo aceita {DUR_MIN_S}-{DUR_MAX_S}s "
            "inteiros)."
        )

    falado = _texto_falado(texto)
    if not falado:
        _abortar("Roteiro sem texto falado depois de tirar as audio tags.")

    corpo = {
        "model": MODELO,
        "input": {
            "prompt": _prompt(falado, cfg.publico),
            "media": [
                {
                    "type": "first_frame",
                    "url": "data:image/png;base64,"
                    + b64encode(IMAGEM.read_bytes()).decode(),
                }
            ],
        },
        "parameters": {
            "resolution": RESOLUCAO,
            "ratio": PROPORCAO,
            "duration": dur,
            "audio": True,
            # O prompt_extend REESCREVE o prompt antes de gerar. Aqui isso é
            # veneno: a fala entre aspas é o roteiro aprovado, e um reescritor
            # no meio do caminho poderia trocar as palavras que as legendas e
            # os cortes já contam como certas.
            "prompt_extend": False,
            "watermark": False,
        },
    }

    print(
        f"[apresentadora] Gerando {dur}s de apresentadora com {MODELO} "
        f"({RESOLUCAO}, {PROPORCAO}, {len(falado.split())} palavras)..."
    )
    try:
        resp = requests.post(
            API_BASE + ROTA_GERAR,
            headers=_cabecalhos(cfg, assincrono=True),
            json=corpo,
            timeout=180,
        )
    except requests.RequestException as e:
        _abortar(f"Falha de rede ao pedir o vídeo da apresentadora: {e}")
    if resp.status_code in (401, 403):
        _abortar(
            f"QWEN_API_KEY recusada pelo QwenCloud (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )
    if resp.status_code != 200:
        _abortar(
            f"QwenCloud recusou a geração (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )

    tarefa = ((resp.json() or {}).get("output") or {}).get("task_id")
    if not tarefa:
        _abortar(f"Resposta do QwenCloud sem task_id: {resp.text[:300]}")

    url = _esperar(cfg, tarefa)
    _baixar(url, destino)
    print(f"[apresentadora] Vídeo da apresentadora salvo em {destino}")
    return destino


def _esperar(cfg: Config, tarefa: str) -> str:
    """Acompanha a tarefa até SUCCEEDED e devolve a URL do vídeo."""
    t0 = time.time()
    while True:
        try:
            resp = requests.get(
                API_BASE + ROTA_TAREFA + tarefa,
                headers=_cabecalhos(cfg, assincrono=False),
                timeout=60,
            )
        except requests.RequestException as e:
            _abortar(f"Falha de rede ao consultar a tarefa {tarefa}: {e}")
        if resp.status_code != 200:
            _abortar(
                f"Consulta da tarefa {tarefa} falhou (HTTP "
                f"{resp.status_code}): {resp.text[:300]}"
            )
        saida = (resp.json() or {}).get("output") or {}
        estado = saida.get("task_status")
        if estado == "SUCCEEDED":
            url = saida.get("video_url")
            if not url:
                _abortar(f"Tarefa {tarefa} concluída sem video_url.")
            print(
                f"[apresentadora] Pronta em {time.time() - t0:.0f}s "
                f"(tarefa {tarefa})."
            )
            return url
        if estado in ("FAILED", "CANCELED", "UNKNOWN"):
            _abortar(
                f"Tarefa {tarefa} terminou em {estado}: "
                f"{json.dumps(saida, ensure_ascii=False)[:400]}"
            )
        if time.time() - t0 > ESPERA_MAX_S:
            _abortar(
                f"Tarefa {tarefa} passou de {ESPERA_MAX_S}s ainda em "
                f"{estado}; abortando para o cron não ficar pendurado."
            )
        time.sleep(ESPERA_PASSO_S)


def _baixar(url: str, destino: Path) -> None:
    """Baixa o MP4. A URL do QwenCloud expira em 24h — não serve de arquivo."""
    try:
        resp = requests.get(url, timeout=300)
        resp.raise_for_status()
    except requests.RequestException as e:
        _abortar(f"Falha ao baixar o vídeo da apresentadora: {e}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(resp.content)
    tamanho = destino.stat().st_size
    if tamanho < 10_000:
        _abortar(f"Vídeo da apresentadora veio vazio ({tamanho} bytes).")


def extrair_audio(video: Path, destino: Path) -> Path:
    """Separa a fala dela do vídeo — é ela que vira a narração do Short.

    SEM aparar, acelerar ou deslocar: qualquer uma das três desencostaria o
    áudio dos lábios. A duração sai igual à do vídeo, e é ela que a montagem
    usa como tamanho do Short.

    SAI EM WAV, não em MP3. O MP3 carrega um atraso de codificador (as amostras
    de priming do LAME) que os decodificadores só descontam quando acham a
    marcação gapless — e apostar a sincronia labial num metadado que pode não
    sobreviver ao próximo elo da cadeia seria um risco gratuito. PCM não tem
    esse problema, o arquivo é intermediário (o vídeo final sai em AAC de
    qualquer jeito) e 25 segundos ocupam ~4 MB de disco efêmero.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    comando = [
        "ffmpeg", "-y", "-hide_banner", "-v", "error",
        "-i", str(video),
        "-vn", "-c:a", "pcm_s16le",
        str(destino),
    ]
    proc = subprocess.run(comando, capture_output=True, text=True)
    if proc.returncode != 0 or not destino.is_file():
        _abortar(
            "ffmpeg não conseguiu separar o áudio da apresentadora: "
            f"{(proc.stderr or '')[-400:]}"
        )
    print(f"[apresentadora] Narração (voz dela) em {destino}")
    return destino


def filtro_chroma() -> str:
    """O filtro de chroma key, num lugar só, para a montagem e para os testes."""
    return f"chromakey={CHROMA_COR}:{CHROMA_SIMILARIDADE}:{CHROMA_MISTURA}"
