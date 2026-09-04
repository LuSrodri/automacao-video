"""Influencer do Short: a voz é da ElevenLabs, e o Wan faz o lipsync.

DESENHO (2026-09-04, pedido do usuário). Em 2026-09-03 o Short passou a ter uma
influencer no rodapé e o áudio dela vinha de dentro do modelo de vídeo: o Wan
recebia o roteiro em TEXTO, escolhia uma voz e devolvia imagem e fala juntas.
Agora a ordem se inverte — QUEM FALA É A ELEVENLABS, e o Wan só sincroniza os
lábios com o MP3 que recebe pronto:

    roteiro -> ElevenLabs (voz da influencer) -> MP3 + timestamps
            -> Wan (reference_image + reference_audio) -> vídeo dela falando

O MODELO É O MESMO de ontem (`wan3.0-video`), e continua sendo o que o
`WAN_MODELO` disser. O que mudou foi o MODO de chamada, e isso não foi escolha:

  - `first_frame` + `driving_audio` (o modo em que o vídeo saía até ontem, com
    áudio anexado) é RECUSADO pelo Wan3.0. Medido contra a API em 2026-09-04:
    a tarefa é aceita e falha logo depois com
    `InvalidParameter: Input should be 'first_frame', 'last_frame',
    'reference_image'...`. A FAQ da Alibaba diz o mesmo — `driving_audio` é do
    `wan2.7-i2v`, não do Wan3.0;
  - o modo que aceita áudio no Wan3.0 é o de REFERÊNCIA:
    `reference_image` + `reference_audio`, que é o que roda aqui.

TRÊS CONSEQUÊNCIAS MEDIDAS, todas contra a API real em 2026-09-04:

1. O ÁUDIO VOLTA INTEIRO E É O NOSSO. O vídeo devolvido traz a mesma onda do
   MP3 que subiu — correlação de 0,98 entre os dois —, com ~0,11s de silêncio
   colado na frente (1º som em 0,059s na entrada e 0,175s na saída). Por isso
   a narração do Short volta a ser o arquivo da ElevenLabs, e não o áudio
   extraído do vídeo: é a mesma fala, sem uma segunda passada de codec. O
   silêncio da frente é medido segmento a segmento e descontado
   (`_deslocamento` + `_encaixar`), senão a boca ficaria 0,11s atrás da voz.

2. O TETO DO ÁUDIO É 15s, E É DA API. Não é o teto do vídeo, que segue em 30s:
   `reference_audio` é material de REFERÊNCIA, e o Wan limita referência a 15s
   (vale igual para `reference_video`). Medido: um MP3 de 22,08s derruba a
   tarefa com `duration should be at most 15s, got 22.08s`, e o `-prime` recusa
   igual — 29,97s devolvem `duration should be at most 15s, got 29.975s`. Não
   há variante do modelo que aceite os 30s de uma vez. Como o Short nasce
   entre 13s e 25s (clipe de 15-30s dividido por MATERIAL_MARGEM, com teto de
   VIDEO_DURACAO), a narração é PARTIDA em pedaços de segundos inteiros e cada
   um vira uma geração, emendadas no fim. Um Short curto cabe em uma só.

3. O VERDE MUDOU E PASSOU A SER MEDIDO. No modo primeiro-quadro o fundo era o
   da própria influencer.png, e o chroma key podia ser constante. No modo
   referência o modelo REPINTA a cena: o verde saiu em 0x489850 (72,152,80)
   contra os 0x38AF33 (56,175,51) de ontem. Com os parâmetros de ontem
   (0,10/0,05) esse verde já come a regata branca dela (alpha 205) e o cabelo
   (68). Em vez de recalibrar uma constante que o modelo pode mudar na próxima
   geração, `cor_de_fundo` MEDE a borda do vídeo pronto e a montagem monta o
   filtro com a cor medida.

O que este módulo NÃO faz mais: gerar voz, escolher palavras e reconstruir
alinhamento. Os timestamps voltaram a vir de graça no `with-timestamps` da
ElevenLabs (audio.gerar_narracao), e com eles voltaram o corte de silêncio e o
ajuste de velocidade, que existiam antes de 2026-09-03 e eram impossíveis com o
áudio preso aos lábios — aqui o lipsync é feito DEPOIS, sobre o áudio já final.
"""

import json
import math
import os
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
import requests

from .config import Config

RAIZ = Path(__file__).resolve().parent.parent

# A FOTO DELA é a referência de identidade que amarra a influencer de um Short
# para o outro. Fundo verde de estúdio, já quadrada (1254x1254), que é a
# proporção em que o vídeo é pedido. No modo referência ela não é mais o
# primeiro quadro literal do vídeo — é o rosto, o corpo e a roupa que o modelo
# tem de manter.
IMAGEM = RAIZ / "influencer.png"

API_BASE = "https://dashscope-intl.aliyuncs.com/api/v1"
ROTA_GERAR = "/services/aigc/video-generation/video-synthesis"
ROTA_TAREFA = "/tasks/"
ROTA_UPLOAD = "/uploads"

# DE VOLTA AO `-prime` (2026-09-04, 3ª mudança do dia, pedido do usuário). Ele
# tinha saído de manhã por custo — é a variante ACELERADA, US$ 0,068/s contra
# US$ 0,035/s do normal em 480P —, e volta agora que o Short depende de um
# lipsync que ainda está sendo acertado: com o -prime a rodada de teste é ~3x
# mais rápida (46s contra 123s medidos em 12s de vídeo), e num assunto em que se
# gera para conferir, esperar custa mais que o dobro do preço. A conta sobe
# ~US$ 0,42 num Short de 13s. O env var segue existindo para a volta ser uma
# troca de valor e não um deploy.
MODELO = os.getenv("WAN_MODELO", "wan3.0-video-prime").strip() or "wan3.0-video-prime"
# 1:1 em 480P sai em 624x624 (medido no modo referência). Ela ocupa menos de
# 3/4 da largura do Short, então 480P já entrega mais pixel do que o quadro usa
# e 720P só dobraria a conta.
RESOLUCAO = "480P"
PROPORCAO = "1:1"

# TETO DO ÁUDIO DE REFERÊNCIA, imposto pela API (ver o cabeçalho). Narração
# maior que isto é partida em pedaços; cada pedaço é uma geração.
AUDIO_MAX_S = 15
# Faixa de duração de vídeo do modelo. Um pedaço nunca chega perto do teto.
DUR_MIN_S = 2
DUR_MAX_S = 30

# CHROMA KEY: só o PLANO B. A cor real vem medida do vídeo pronto
# (`cor_de_fundo`), porque no modo referência o fundo é repintado a cada
# geração. Estes números são os de 2026-09-04: cor medida no primeiro vídeo de
# referência e a janela de similaridade/mistura varrida em cima dele — em
# 0,08/0,02 os cantos ficam em alpha 1, o rosto e a regata em 255 e a borda do
# cabelo em 170. Acima de 0,12 o filtro começa a comer a regata branca.
CHROMA_COR = "0x489850"
CHROMA_SIMILARIDADE = 0.08
CHROMA_MISTURA = 0.02

# SEM DESPILL, de propósito, como desde 2026-09-03. O `despill` do ffmpeg tira
# o verde refletido, mas lavava a regata BRANCA dela para lilás (canal verde do
# tecido caindo de 107 para 62). A franja verde que sobra na borda do cabelo é
# pequena e some na escala em que ela entra no quadro.

# TAMANHO E LUGAR NO QUADRO. A fração é do LADO do quadrado sobre a LARGURA do
# vídeo: 0,72 de 1080 são 778px, e a influencer recortada ocupa ~435px de
# largura, com o topo da cabeça em ~61% da altura. Isso a deixa no terço de
# baixo, abaixo da legenda e sem cobrir o miolo do clipe.
LARGURA_FRAC = 0.72

# Quanto esperar a fila do Wan. Medido no modo referência: 134s para 10s de
# vídeo. Os pedaços são pedidos TODOS DE UMA VEZ e esperados depois, então dois
# pedaços custam o tempo do mais lento, não a soma. O teto é generoso de
# propósito: a alternativa a esperar é perder a execução inteira do cron.
ESPERA_MAX_S = 900
ESPERA_PASSO_S = 10


def _abortar(motivo: str) -> None:
    """Falha de credencial ou de API aborta a execução (diretriz de 2026-07-15).

    A influencer não tem plano B: ela é a cara do Short desde 2026-09-03.
    Seguir sem ela publicaria o vídeo sem quem o narra na tela.
    """
    raise SystemExit(f"[influencer] {motivo}")


def _cabecalhos(cfg: Config, assincrono: bool) -> dict:
    cab = {
        "Authorization": f"Bearer {cfg.qwen_api_key}",
        "Content-Type": "application/json",
        # Sem isto o Wan não consegue LER as URLs `oss://` que o upload
        # devolve, e a tarefa falha dizendo que o arquivo não existe.
        "X-DashScope-OssResourceResolve": "enable",
    }
    if assincrono:
        cab["X-DashScope-Async"] = "enable"
    return cab


def _subir(cfg: Config, arquivo: Path) -> str:
    """Sobe um arquivo ao armazenamento temporário do DashScope (URL `oss://`).

    O ÁUDIO NÃO PODE IR EM BASE64. A imagem pode — e ia, até ontem —, mas o
    `reference_audio` só aceita URL pública ou `oss://` (conferido na
    referência da API e no comportamento real). Como o pipeline não tem onde
    publicar um MP3, o caminho é este: o DashScope dá uma credencial de upload,
    o arquivo vai para um bucket temporário dele (válido por 48h) e o modelo o
    lê pela URL `oss://`. É de graça e não sai da casa da própria API.
    """
    try:
        resp = requests.get(
            API_BASE + ROTA_UPLOAD,
            params={"action": "getPolicy", "model": MODELO},
            headers={"Authorization": f"Bearer {cfg.qwen_api_key}"},
            timeout=60,
        )
    except requests.RequestException as e:
        _abortar(f"Falha de rede ao pedir credencial de upload: {e}")
    if resp.status_code in (401, 403):
        _abortar(
            f"QWEN_API_KEY recusada pelo QwenCloud (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )
    if resp.status_code != 200:
        _abortar(
            f"QwenCloud recusou a credencial de upload (HTTP "
            f"{resp.status_code}): {resp.text[:300]}"
        )

    dados = (resp.json() or {}).get("data") or {}
    faltando = [
        c
        for c in ("upload_host", "upload_dir", "oss_access_key_id", "policy", "signature")
        if not dados.get(c)
    ]
    if faltando:
        _abortar(f"Credencial de upload incompleta (sem {', '.join(faltando)}).")

    chave = f"{dados['upload_dir']}/{arquivo.name}"
    campos = {
        "OSSAccessKeyId": dados["oss_access_key_id"],
        "policy": dados["policy"],
        "Signature": dados["signature"],
        "key": chave,
        "x-oss-object-acl": dados.get("x_oss_object_acl", "private"),
        "x-oss-forbid-overwrite": dados.get("x_oss_forbid_overwrite", "true"),
        "success_action_status": "200",
    }
    try:
        with arquivo.open("rb") as fh:
            envio = requests.post(
                dados["upload_host"], data=campos, files={"file": fh}, timeout=300
            )
    except requests.RequestException as e:
        _abortar(f"Falha de rede ao subir {arquivo.name}: {e}")
    if envio.status_code not in (200, 204):
        _abortar(
            f"Upload de {arquivo.name} recusado (HTTP {envio.status_code}): "
            f"{envio.text[:300]}"
        )
    return "oss://" + chave


def _prompt(publico: str) -> str:
    """O prompt do Wan: quem ela é, como se comporta e qual é o fundo.

    O QUE SAIU DAQUI FOI A FALA. Até ontem o roteiro inteiro ia dentro do
    prompt, entre aspas, porque era o prompt que ditava o que ela dizia. Agora
    quem diz é o Áudio 1, e mandar o texto junto seria pedir ao modelo que
    resolvesse uma redundância — no melhor caso ele obedeceria ao áudio, no
    pior tentaria conciliar os dois.

    O QUE FICOU É O REGISTRO, palavra por palavra como estava: influencer e não
    apresentadora de telejornal (2026-09-04), ombros soltos, gesto assimétrico,
    sorriso que vem e vai. E o FUNDO VERDE, que aqui é ainda mais importante
    que ontem: no modo referência o modelo repinta a cena, então "liso,
    uniforme, sem sombras e sem objetos" é o que segura o chroma key de pé.
    """
    idioma = "inglês americano" if publico == "usa" else "português do Brasil"
    return (
        "A mesma mulher da Imagem 1, uma influencer jovem e carismática "
        "gravando um vídeo casual para as redes sociais dela, enquadrada da "
        "cintura para cima, diante de um fundo CHROMA KEY VERDE liso, uniforme "
        "e totalmente sem textura, sem sombras e sem objetos. Câmera fixa, sem "
        "zoom, sem corte e sem movimento de câmera. Iluminação de estúdio "
        "suave. Ela fala o Áudio 1 em "
        f"{idioma}, com os lábios sincronizados exatamente com ele. O clima é "
        "DESCONTRAÍDO e espontâneo, nada de apresentadora de telejornal: ela "
        "fala olhando para a câmera como quem conta uma novidade para um "
        "amigo, com os ombros soltos e a postura relaxada, sorrindo de leve e "
        "naturalmente entre as frases, levantando as sobrancelhas, inclinando "
        "a cabeça de vez em quando e gesticulando de um jeito solto e "
        "assimétrico com as mãos. Expressão viva e informal, sem rigidez e sem "
        "gesto ensaiado. Nenhuma outra voz, nenhuma música e nenhum ruído além "
        "do Áudio 1."
    )


# --- Áudio: medir, partir, comparar -----------------------------------------


def _pcm(arquivo: Path, taxa: int = 16000) -> np.ndarray:
    """Decodifica qualquer arquivo (MP3 ou MP4) em mono PCM para medição."""
    saida = arquivo.with_suffix(".medicao.wav")
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-v", "error",
            "-i", str(arquivo),
            "-vn", "-ac", "1", "-ar", str(taxa), "-c:a", "pcm_s16le",
            str(saida),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not saida.is_file():
        _abortar(
            f"ffmpeg não conseguiu ler o áudio de {arquivo.name}: "
            f"{(proc.stderr or '')[-300:]}"
        )
    with wave.open(str(saida)) as w:
        dados = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    saida.unlink(missing_ok=True)
    return dados.astype(np.float64)


def _duracao(arquivo: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "csv=p=0", str(arquivo),
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        _abortar(f"ffprobe não mediu a duração de {arquivo.name}.")
        return 0.0


def _cortes(narracao: Path) -> list[tuple[int, int]]:
    """Onde partir a narração: pedaços de segundos INTEIROS, de até 15s.

    INTEIROS porque o `duration` do Wan é inteiro. Pedir 12 para um pedaço de
    12,4s deixaria o modelo resolver 0,4s de fala sobrando do jeito dele, e
    ninguém sabe qual é esse jeito; com o corte no segundo cheio, o pedido e o
    material são a mesma coisa e o vídeo volta do tamanho exato do pedaço.

    ONDE, dentro disso, é escolhido pelo SILÊNCIO: entre os segundos cheios
    candidatos, ganha o mais quieto. Cortar no meio de uma palavra não estraga
    o áudio (ele é remontado inteiro, do arquivo original) mas faz o modelo
    começar o segmento seguinte com a boca no meio de um fonema, e é isso que
    a escolha evita. O último pedaço fecha no segundo cheio ACIMA da duração,
    com o resto virando silêncio — a montagem corta o excedente.
    """
    total = _duracao(narracao)
    fim = int(math.ceil(total - 0.01))
    n = max(1, math.ceil(fim / AUDIO_MAX_S))
    if n == 1:
        return [(0, max(DUR_MIN_S, fim))]

    # Envelope de energia em janelas de 10ms, para achar os trechos quietos.
    amostras = _pcm(narracao)
    janela = 160
    quadros = len(amostras) // janela
    energia = np.array(
        [
            np.sqrt((amostras[i * janela : (i + 1) * janela] ** 2).mean() + 1e-9)
            for i in range(quadros)
        ]
    )

    def quietude(segundo: int) -> float:
        centro = segundo * 100
        return float(energia[max(0, centro - 20) : centro + 20].mean())

    bordas = [0]
    for k in range(1, n):
        alvo = fim * k / n
        # Candidatos: os segundos cheios em volta do alvo que respeitam o teto
        # dos dois lados (o pedaço que fecha e o que abre).
        menor = max(bordas[-1] + DUR_MIN_S, int(math.ceil(fim - AUDIO_MAX_S * (n - k))))
        maior = min(bordas[-1] + AUDIO_MAX_S, fim - DUR_MIN_S)
        if menor > maior:
            menor = maior = min(bordas[-1] + AUDIO_MAX_S, fim - DUR_MIN_S)
        candidatos = [s for s in range(menor, maior + 1) if abs(s - alvo) <= 2.5] or [
            int(round(min(max(alvo, menor), maior)))
        ]
        bordas.append(min(candidatos, key=quietude))
    bordas.append(fim)
    return [(bordas[i], bordas[i + 1] - bordas[i]) for i in range(len(bordas) - 1)]


def _pedaco(narracao: Path, inicio: int, duracao: int, destino: Path) -> Path:
    """Recorta [inicio, inicio+duracao) da narração, com a duração EXATA.

    O `apad` sem fim mais o `-t` são o que garante a duração EXATA: o último
    pedaço acaba antes do segundo cheio (a fala termina em 22,08s de um pedaço
    que vai até 23) e o silêncio completa o resto. Sem isso o arquivo sairia
    com 11,08s onde o pedido diz 12, e o modelo resolveria a diferença do jeito
    dele. O `apad=whole_dur` foi tentado primeiro e MEDIDO não completando o
    pedaço — daí a dupla.
    """
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-v", "error",
            "-i", str(narracao),
            "-ss", str(inicio),
            "-af", "apad",
            "-t", str(duracao),
            "-c:a", "libmp3lame", "-b:a", "128k",
            str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not destino.is_file():
        _abortar(
            f"ffmpeg não conseguiu recortar o pedaço {inicio}-{inicio+duracao}s "
            f"da narração: {(proc.stderr or '')[-300:]}"
        )
    medida = _duracao(destino)
    if abs(medida - duracao) > 0.05:
        _abortar(
            f"O pedaço {inicio}-{inicio+duracao}s saiu com {medida:.2f}s em vez "
            f"de {duracao}s — o vídeo gerado não encaixaria na narração."
        )
    return destino


def _deslocamento(pedaco: Path, segmento: Path) -> float:
    """Quanto de silêncio o Wan colou na FRENTE do áudio devolvido, em segundos.

    O modelo devolve a mesma onda que recebeu, atrasada — 0,116s no vídeo de
    calibração. Como o vídeo é gerado em cima do áudio ATRASADO, os lábios
    também estão atrasados, e sem descontar isso ela ficaria falando um décimo
    de segundo depois da voz (a voz na frente da imagem é o lado que o olho
    percebe primeiro).

    É MEDIDO, não constante: casa as duas ondas por correlação cruzada (FFT) e
    devolve o deslocamento do pico. Se a medida vier absurda (fora de 0-1s) ou
    fraca, devolve 0 — melhor não mexer do que mexer errado.
    """
    a = _pcm(pedaco)
    b = _pcm(segmento)
    n = min(len(a), len(b))
    if n < 16000:
        return 0.0
    x, y = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    tamanho = 1 << int(np.ceil(np.log2(2 * n)))
    cc = np.fft.irfft(
        np.fft.rfft(y, tamanho) * np.conj(np.fft.rfft(x, tamanho)), tamanho
    )
    norma = float(np.sqrt((x * x).sum() * (y * y).sum())) + 1e-9
    pico = int(np.argmax(cc[: 16000 * 2]))          # só atrasos de até 2s
    forca = float(cc[pico]) / norma
    desloc = pico / 16000.0
    if forca < 0.2 or not 0.0 <= desloc <= 1.0:
        print(
            f"[influencer] aviso: deslocamento do segmento não confiável "
            f"(pico {forca:.2f} em {desloc:.3f}s); seguindo sem descontar."
        )
        return 0.0
    return desloc


def _encaixar(segmento: Path, desloc: float, duracao: int, destino: Path) -> Path:
    """Tira o silêncio da frente e devolve o segmento com a duração pedida.

    Corta `desloc` segundos do começo (é ali que a boca está parada esperando o
    áudio começar) e repõe o mesmo tanto no fim CONGELANDO o último quadro
    (`tpad=stop_mode=clone`). Assim cada segmento continua com exatamente os
    segundos que a narração reservou para ele, e a emenda com o segmento
    seguinte cai no lugar certo — sem isso o atraso se acumularia de pedaço em
    pedaço.

    O congelado dura ~0,11s no fim de um pedaço, que é onde o corte procurou
    silêncio: três quadros parados dentro de uma pausa.

    SEM ÁUDIO (`-an`): a narração do Short é o MP3 da ElevenLabs, e a montagem
    usa este arquivo só como imagem. Carregar a cópia AAC da mesma fala só
    daria chance de as duas se desencontrarem na emenda.
    """
    filtro = (
        f"trim=start={desloc:.3f}:end={duracao},setpts=PTS-STARTPTS,"
        f"tpad=stop_mode=clone:stop_duration={desloc:.3f}"
    )
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-v", "error",
            "-i", str(segmento),
            "-an", "-vf", filtro,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not destino.is_file():
        _abortar(
            f"ffmpeg não conseguiu encaixar o segmento {segmento.name}: "
            f"{(proc.stderr or '')[-300:]}"
        )
    return destino


def _emendar(segmentos: list[Path], destino: Path) -> Path:
    """Cola os segmentos em um vídeo só (concat demuxer, sem recodificar)."""
    if len(segmentos) == 1:
        segmentos[0].replace(destino)
        return destino
    lista = destino.parent / "influencer_segmentos.txt"
    lista.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in segmentos), encoding="utf-8"
    )
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", str(lista),
            "-c", "copy", str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not destino.is_file():
        _abortar(
            f"ffmpeg não conseguiu emendar os {len(segmentos)} segmentos da "
            f"influencer: {(proc.stderr or '')[-300:]}"
        )
    return destino


# --- Geração -----------------------------------------------------------------


def gerar(cfg: Config, narracao: Path, destino: Path) -> Path:
    """Gera o vídeo da influencer com os lábios sincronizados com `narracao`.

    Devolve o caminho do MP4 (624x624, 30fps, SEM áudio), pronto para o chroma
    key da montagem. A duração é a da narração arredondada para cima, no
    segundo cheio — a montagem já corta o excedente no `-t` dela.
    """
    if not cfg.qwen_api_key:
        _abortar(
            "QWEN_API_KEY ausente — sem ela o Short sairia sem a influencer "
            "que o narra na tela."
        )
    if not IMAGEM.is_file():
        _abortar(
            f"Foto da influencer ausente ({IMAGEM}) — é ela que fixa a "
            "identidade dela de um vídeo para o outro."
        )
    if not narracao.is_file():
        _abortar(f"Narração ausente ({narracao}) — é ela que move a boca dela.")

    pedacos = _cortes(narracao)
    total = sum(d for _, d in pedacos)
    print(
        f"[influencer] {_duracao(narracao):.1f}s de narração em "
        f"{len(pedacos)} geração(ões) de {[d for _, d in pedacos]}s "
        f"({MODELO}, {RESOLUCAO}, {PROPORCAO})."
    )
    if any(d > AUDIO_MAX_S for _, d in pedacos):
        _abortar(
            f"Pedaço acima do teto de {AUDIO_MAX_S}s do reference_audio "
            f"({[d for _, d in pedacos]}) — a API recusaria a geração."
        )

    imagem_url = _subir(cfg, IMAGEM)

    # PEDE TODOS DE UMA VEZ e só depois espera: as gerações correm em paralelo
    # no QwenCloud, então dois pedaços custam o tempo do mais lento (~135s
    # medidos para 10s de vídeo) em vez da soma.
    tarefas = []
    for i, (inicio, duracao) in enumerate(pedacos):
        arquivo = _pedaco(
            narracao, inicio, duracao, destino.parent / f"narracao_p{i}.mp3"
        )
        corpo = {
            "model": MODELO,
            "input": {
                "prompt": _prompt(cfg.publico),
                "media": [
                    {"type": "reference_image", "url": imagem_url},
                    {"type": "reference_audio", "url": _subir(cfg, arquivo)},
                ],
            },
            "parameters": {
                "resolution": RESOLUCAO,
                "ratio": PROPORCAO,
                "duration": duracao,
                "audio": True,
                # O prompt_extend REESCREVE o prompt antes de gerar, e o que
                # está escrito aqui é o que segura o fundo verde de pé.
                "prompt_extend": False,
                "watermark": False,
            },
        }
        try:
            resp = requests.post(
                API_BASE + ROTA_GERAR,
                headers=_cabecalhos(cfg, assincrono=True),
                json=corpo,
                timeout=180,
            )
        except requests.RequestException as e:
            _abortar(f"Falha de rede ao pedir o vídeo da influencer: {e}")
        if resp.status_code in (401, 403):
            _abortar(
                f"QWEN_API_KEY recusada pelo QwenCloud (HTTP "
                f"{resp.status_code}): {resp.text[:300]}"
            )
        if resp.status_code != 200:
            _abortar(
                f"QwenCloud recusou a geração (HTTP {resp.status_code}): "
                f"{resp.text[:300]}"
            )
        tarefa = ((resp.json() or {}).get("output") or {}).get("task_id")
        if not tarefa:
            _abortar(f"Resposta do QwenCloud sem task_id: {resp.text[:300]}")
        tarefas.append((tarefa, arquivo, duracao))

    prontos = []
    t0 = time.time()
    for i, (tarefa, arquivo, duracao) in enumerate(tarefas):
        bruto = destino.parent / f"influencer_bruto{i}.mp4"
        _baixar(_esperar(cfg, tarefa, t0), bruto)
        desloc = _deslocamento(arquivo, bruto)
        print(
            f"[influencer] Segmento {i + 1}/{len(tarefas)}: {duracao}s, "
            f"silêncio de {desloc * 1000:.0f}ms na frente, descontado."
        )
        prontos.append(
            _encaixar(bruto, desloc, duracao, destino.parent / f"influencer_s{i}.mp4")
        )

    _emendar(prontos, destino)
    print(
        f"[influencer] Vídeo da influencer ({total}s, "
        f"{_duracao(destino):.1f}s medidos) salvo em {destino}"
    )
    return destino


def _esperar(cfg: Config, tarefa: str, t0: float) -> str:
    """Acompanha a tarefa até SUCCEEDED e devolve a URL do vídeo."""
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
                f"[influencer] Segmento pronto em {time.time() - t0:.0f}s "
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
        _abortar(f"Falha ao baixar o vídeo da influencer: {e}")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(resp.content)
    tamanho = destino.stat().st_size
    if tamanho < 10_000:
        _abortar(f"Vídeo da influencer veio vazio ({tamanho} bytes).")


# --- Chroma key --------------------------------------------------------------


def cor_de_fundo(video: Path) -> str:
    """Mede o verde do fundo NESTE vídeo e devolve a cor em hexa.

    Existe porque o modo referência repinta a cena: o verde não é mais o da
    influencer.png, e nada garante que a próxima geração pinte o mesmo tom.
    Medido no vídeo de calibração de 2026-09-04, o fundo é estável DENTRO de um
    vídeo (desvio de 1,3 a 2,7 entre quadros) — o risco é entre vídeos, e é
    esse que a medição cobre.

    Como: mediana da BORDA (12px de cada lado) de 8 quadros espalhados. A borda
    é fundo em qualquer enquadramento de meio corpo, e a mediana ignora o
    quadro em que uma mecha de cabelo encosta na lateral.

    Devolve a constante calibrada se o OpenCV não estiver instalado ou se o que
    for medido não for verde — cor errada aqui apagaria pedaços dela.
    """
    try:
        import cv2  # noqa: PLC0415 — opcional, como no enquadramento
    except ImportError:
        print("[influencer] Sem OpenCV; chroma key na cor calibrada.")
        return CHROMA_COR

    cap = cv2.VideoCapture(str(video))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    amostras = []
    for quadro in np.linspace(0, max(total - 1, 0), 8, dtype=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(quadro))
        ok, imagem = cap.read()
        if not ok:
            continue
        borda = np.concatenate(
            [
                imagem[:12].reshape(-1, 3),
                imagem[-12:].reshape(-1, 3),
                imagem[:, :12].reshape(-1, 3),
                imagem[:, -12:].reshape(-1, 3),
            ]
        )
        amostras.append(np.median(borda, axis=0))
    cap.release()
    if not amostras:
        print("[influencer] Não li quadro nenhum; chroma key na cor calibrada.")
        return CHROMA_COR

    b, g, r = (int(round(v)) for v in np.median(np.array(amostras), axis=0))
    if not (g > r + 30 and g > b + 30):
        print(
            f"[influencer] Fundo medido em ({r},{g},{b}) não é verde; "
            "chroma key na cor calibrada."
        )
        return CHROMA_COR
    cor = f"0x{r:02X}{g:02X}{b:02X}"
    print(f"[influencer] Verde do fundo medido: {cor} ({r},{g},{b}).")
    return cor


def filtro_chroma(video: Path | None = None) -> str:
    """O filtro de chroma key, num lugar só, para a montagem e para os testes."""
    cor = cor_de_fundo(video) if video is not None else CHROMA_COR
    return f"chromakey={cor}:{CHROMA_SIMILARIDADE}:{CHROMA_MISTURA}"
