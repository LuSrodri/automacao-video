"""Influencer do Short: a voz é da ElevenLabs, e o Wan faz o lipsync.

DESENHO (2026-09-04, 5ª mudança do dia). A ordem é a mesma desde a 3ª mudança
— quem fala é a ElevenLabs, e o Wan só sincroniza os lábios com o MP3 pronto:

    roteiro -> ElevenLabs (voz da influencer) -> MP3 + timestamps
            -> Wan (first_frame + driving_audio) -> vídeo dela falando

O QUE MUDOU FOI O MODELO, e por uma razão de leitura de documentação, não de
medição: o `wan3.0-video` NÃO TEM lipsync dirigido por áudio externo. O
`reference_audio` dele é referência de TIMBRE. O guia oficial do wan3.0 diz o
uso pretendido com todas as letras — "extract the voice characteristics from
Audio 1, and have the character say the following lines: '...'" —, ou seja: o
modelo CLONA a voz do áudio e GERA uma fala nova a partir do TEXTO do prompt, e
é a boca dessa fala gerada que ele sincroniza. Não existe, no wan3.0, "case os
lábios com este MP3".

Isso explica exatamente o que se viu:

  - o desenho de 2026-09-03 sincronizava porque o roteiro ia em TEXTO no
    prompt — havia fala gerada dirigindo a boca;
  - o de 2026-09-04 (3ª) não sincronizava porque o prompt tirou a fala. Não
    sobrou NADA dirigindo os lábios, e a boca aberta nos oito testes de
    /m/ /b/ /p/ era boca de idle, não lipsync errado;
  - o áudio voltar com correlação 0,98 nunca foi prova de sincronia: sem texto
    de fala o modelo passa a referência adiante como trilha. Áudio preservado
    não é áudio dirigindo.

Havia um segundo defeito no mesmo prompt, e ele some junto: as referências do
wan3.0 são endereçadas por TAG POSICIONAL ("Image 1", "Img 1", "Audio 1"), e o
prompt daqui mandava "Imagem 1" e "Áudio 1" em português — nem a identidade
dela estava amarrada à foto.

O MODO QUE FAZ O QUE ESTE MÓDULO PRECISA é o do `wan2.7-i2v`: `first_frame` +
`driving_audio`, do qual a referência da API diz, textualmente, "the model uses
it as a driving source for lip-sync and action timing". É o único modo
documentado no Model Studio em que áudio EXTERNO move a boca.

O QUE ISSO MUDA, ponto a ponto:

1. VOLTA O PRIMEIRO QUADRO. A influencer.png não é mais uma referência que o
   modelo reinterpreta: é literalmente o quadro 1 do vídeo. A identidade dela
   deixa de depender de o modelo "entender" a foto, e o FUNDO deixa de ser
   repintado a cada geração — o verde volta a ser o da própria foto. Por isso
   a constante de chroma key volta à calibração de 2026-09-03 (0x38AF33 em
   0,10/0,05, varrida em cima de saída real do modo primeiro-quadro). A
   medição em tempo de execução (`cor_de_fundo`) FICA: ela custa nada e agora
   é rede em vez de necessidade.

2. O TETO DE 15s DEIXA DE SER DO ÁUDIO E PASSA A SER DO VÍDEO. O
   `driving_audio` aceita de 2s a 30s; quem para em 15s é o `duration` do
   modelo. A narração continua partida em pedaços de segundos inteiros e
   emendada no fim, e por isso `_cortes`, `_pedaco`, `_deslocamento`,
   `_encaixar` e `_emendar` seguem valendo palavra por palavra. O que MUDOU é
   que os pedaços deixaram de correr em paralelo: cada um começa no ÚLTIMO
   QUADRO do anterior, porque começar todos na foto fazia a influencer voltar
   à pose do retrato no meio da frase, a cada emenda (ver `gerar`).

3. A RESOLUÇÃO SOBE. O wan2.7-i2v tem 720P e 1080P, sem 480P, e a proporção da
   saída SEGUE A DO PRIMEIRO QUADRO (não há `ratio`): a influencer.png é
   quadrada, então sai um quadrado de ~960x960 no lugar dos 624x624 de antes.
   Mais pixel do que o Short usa, e não há tier menor para pedir.

4. O CUSTO SOBE, e foi a alavanca aceita pelo usuário para ter lipsync de
   verdade. Não há variante barata: `driving_audio` só existe aqui.

O env var mudou de nome DE PROPÓSITO: `WAN_MODELO` ficou para trás porque os
dois modos têm payloads INCOMPATÍVEIS (`reference_image`/`reference_audio`
contra `first_frame`/`driving_audio`), e um valor velho de wan3.0 sobrevivendo
no ambiente derrubaria toda execução. Agora é `WAN_LIPSYNC_MODELO`.

O que este módulo NÃO faz: gerar voz, escolher palavras e reconstruir
alinhamento. Os timestamps vêm de graça no `with-timestamps` da ElevenLabs
(audio.gerar_narracao), e com eles seguem de pé o corte de silêncio e o ajuste
de velocidade — aqui o lipsync é feito DEPOIS, sobre o áudio já final.
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

# O MODELO DO LIPSYNC. `wan2.7-i2v` é o único do Model Studio cuja API aceita
# áudio EXTERNO como driver da boca (`driving_audio`); ver o cabeçalho. O env
# var MUDOU DE NOME (`WAN_MODELO` -> `WAN_LIPSYNC_MODELO`) porque os payloads
# dos dois modos são incompatíveis, e um valor velho de wan3.0 sobrando no
# ambiente derrubaria toda execução em vez de degradar.
MODELO = os.getenv("WAN_LIPSYNC_MODELO", "wan2.7-i2v").strip() or "wan2.7-i2v"
# O wan2.7-i2v tem 720P e 1080P, sem 480P — 720P é o piso. E NÃO HÁ `ratio`: a
# proporção da saída segue a do primeiro quadro, e a influencer.png é quadrada
# (1254x1254), então sai um quadrado de ~960x960. É mais pixel do que o Short
# usa, e não há tier menor para pedir.
RESOLUCAO = "720P"

# FAIXA DE UM PEDAÇO, que é a faixa do `duration` do modelo. O teto passou a
# ser do VÍDEO e não do áudio: o `driving_audio` aceita de 2s a 30s, e quem
# para em 15s é o `duration`. Narração maior que isto é partida; cada pedaço é
# uma geração.
DUR_MIN_S = 2
SEGMENTO_MAX_S = 15

# CHROMA KEY: só o PLANO B — a cor real vem medida do vídeo pronto
# (`cor_de_fundo`). Estes números voltaram a ser os de 2026-09-03, que é a
# calibração do modo PRIMEIRO QUADRO: com a influencer.png virando o quadro 1,
# o fundo é o verde dela e não mais um verde repintado pelo modelo. Em
# 0,10/0,05 os cantos ficam transparentes e o rosto e a regata branca ficam
# inteiros. RE-MEDIDO em saída real do wan2.7-i2v (2026-09-04): o verde sai em
# 0x2DAF2A, estável entre quadros (desvio de 1), e com esta cor e esta janela
# sobra 0,09% do fundo e o filtro come 0,2% do sujeito, em três quadros
# espalhados. A janela é estreita de verdade: em 0,16/0,08 ele come metade
# dela.
CHROMA_COR = "0x38AF33"
CHROMA_SIMILARIDADE = 0.10
CHROMA_MISTURA = 0.05

# SEM DESPILL, de propósito, como desde 2026-09-03. O `despill` do ffmpeg tira
# o verde refletido, mas lavava a regata BRANCA dela para lilás (canal verde do
# tecido caindo de 107 para 62). A franja verde que sobra na borda do cabelo é
# pequena e some na escala em que ela entra no quadro.

# TAMANHO E LUGAR NO QUADRO. A fração é do LADO do quadrado sobre a LARGURA do
# vídeo: 0,72 de 1080 são 778px, e a influencer recortada ocupa ~435px de
# largura, com o topo da cabeça em ~61% da altura. Isso a deixa no terço de
# baixo, abaixo da legenda e sem cobrir o miolo do clipe.
LARGURA_FRAC = 0.72

# Quanto esperar a fila do Wan, SOMANDO TODOS OS PEDAÇOS — o `t0` é criado uma
# vez em `gerar` e atravessa o laço. A doc do wan2.7-i2v fala em 1 a 5 minutos
# por tarefa, e medimos ~105s por pedaço; como os pedaços são encadeados (cada
# um começa no último quadro do anterior), o custo é a SOMA e não o máximo:
# ~210s nos dois pedaços de um Short típico. O teto é generoso de propósito: a
# alternativa a esperar é perder a execução inteira do cron.
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

    O ÁUDIO NÃO PODE IR EM BASE64. A imagem pode — a referência do wan2.7-i2v
    aceita base64 em `first_frame` —, mas o `driving_audio` só aceita URL
    pública ou `oss://` (a doc lista só "Public URL"). Como o pipeline não tem
    onde
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

    NÃO TEM TAG DE REFERÊNCIA, e é isso que o distingue do prompt de antes. No
    wan3.0 o material era endereçado por tag posicional ("Image 1", "Audio 1"),
    e este prompt mandava "Imagem 1" e "Áudio 1" em português — que o modelo
    não reconhece. No wan2.7-i2v não há tag nenhuma a acertar: a foto É o
    primeiro quadro e o MP3 É o driver, os dois pela `media`, e o prompt volta a
    ser só o que ele deve ser — a direção da cena.

    A FALA CONTINUA FORA DAQUI, agora por um motivo mais forte do que ontem.
    Quem dita os lábios é o `driving_audio`; mandar o roteiro junto seria pedir
    ao modelo que conciliasse duas fontes de fala, e a que ele obedecesse
    poderia não ser a nossa. O prompt DIZ que ela está falando (senão a boca
    fica parada) e CALA o que ela diz.

    O registro é o mesmo, palavra por palavra: influencer e não apresentadora de
    telejornal (2026-09-04), ombros soltos, gesto assimétrico, sorriso que vem e
    vai. E o FUNDO VERDE, que aqui é mais barato de segurar que no modo
    referência — ele já vem do primeiro quadro; o prompt só evita que o modelo
    invente objeto ou sombra em cima dele.
    """
    idioma = "inglês americano" if publico == "usa" else "português do Brasil"
    return (
        "Uma influencer jovem e carismática gravando um vídeo casual para as "
        "redes sociais dela, enquadrada da cintura para cima, diante de um "
        "fundo CHROMA KEY VERDE liso, uniforme e totalmente sem textura, sem "
        "sombras e sem objetos. Câmera fixa, sem zoom, sem corte e sem "
        "movimento de câmera. Iluminação de estúdio suave. Ela FALA o tempo "
        f"todo, em {idioma}, com os lábios sincronizados exatamente com o "
        "áudio, articulando cada sílaba, fechando os lábios nos sons de M, B e "
        "P e abrindo a boca nas vogais. O clima é DESCONTRAÍDO e espontâneo, "
        "nada de apresentadora de telejornal: ela fala olhando para a câmera "
        "como quem conta uma novidade para um amigo, com os ombros soltos e a "
        "postura relaxada, sorrindo de leve e naturalmente entre as frases, "
        "levantando as sobrancelhas, inclinando a cabeça de vez em quando e "
        "gesticulando de um jeito solto e assimétrico com as mãos. Expressão "
        "viva e informal, sem rigidez e sem gesto ensaiado. Nenhuma outra voz, "
        "nenhuma música e nenhum ruído além da fala dela."
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

    QUINZE POR CAUSA DO VÍDEO, não do áudio: o `driving_audio` do wan2.7-i2v
    aceita até 30s, mas o `duration` do modelo para em 15. Pedir mais devolveria
    um vídeo curto demais para o pedaço, com a boca parando antes da fala.

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
    n = max(1, math.ceil(fim / SEGMENTO_MAX_S))
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
        menor = max(bordas[-1] + DUR_MIN_S, int(math.ceil(fim - SEGMENTO_MAX_S * (n - k))))
        maior = min(bordas[-1] + SEGMENTO_MAX_S, fim - DUR_MIN_S)
        if menor > maior:
            menor = maior = min(bordas[-1] + SEGMENTO_MAX_S, fim - DUR_MIN_S)
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

    No modo referência o modelo devolvia a mesma onda que recebeu, atrasada —
    0,116s no vídeo de calibração. A medida vale igual aqui, e se o wan2.7-i2v
    não atrasar nada ela devolve 0 e nada é cortado. Como o vídeo é gerado em
    cima do áudio, um atraso no áudio é um atraso nos lábios
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


def _ultimo_quadro(video: Path, destino: Path) -> Path:
    """Extrai o ÚLTIMO quadro do segmento, para ele virar o quadro 1 do próximo.

    É o que costura a emenda (ver `gerar`). `-sseof -1` posiciona a leitura no
    último segundo e `-update 1` deixa cada quadro sobrescrever o anterior, de
    modo que o que sobra no arquivo é literalmente o último — sem precisar
    saber a duração nem contar quadros.
    """
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-v", "error",
            "-sseof", "-1", "-i", str(video),
            "-update", "1", "-frames:v", "1", str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0 or not destino.is_file():
        _abortar(
            f"ffmpeg não extraiu o último quadro de {video.name}: "
            f"{(proc.stderr or '')[-300:]}"
        )
    return destino


def gerar(cfg: Config, narracao: Path, destino: Path) -> Path:
    """Gera o vídeo da influencer com os lábios sincronizados com `narracao`.

    Devolve o caminho do MP4 (960x960, 30fps, SEM áudio), pronto para o chroma
    key da montagem. A duração é a da narração arredondada para cima, no
    segundo cheio — a montagem já corta o excedente no `-t` dela.

    OS PEDAÇOS SÃO ENCADEADOS, e isso custa tempo de propósito. Até aqui eles
    eram pedidos TODOS DE UMA VEZ e corriam em paralelo, o que fazia dois
    pedaços custarem o tempo do mais lento em vez da soma. O problema é que
    cada geração começa no `first_frame` que recebe: com a influencer.png em
    todos, TODO SEGMENTO recomeçava da mesma foto, e na emenda ela voltava de
    supetão para a pose parada do retrato — cabelo no lugar, cabeça centrada,
    sorriso de foto — no meio de uma frase. Medido no vídeo de 21s: em 11,98s
    ela está falando com a cabeça de lado, e em 12,00s é o retrato de novo.

    Como um Short nasce entre 13s e 26s e o `duration` para em 15s, DOIS
    pedaços é o caso comum, não a exceção — a emenda apareceria em quase todo
    vídeo. Por isso o quadro 1 de cada pedaço passou a ser o ÚLTIMO QUADRO do
    pedaço anterior: a pose atravessa a emenda e o corte deixa de existir.

    O preço é a serialização (~210s em vez de ~110s nos dois pedaços medidos),
    que cabe folgado no ESPERA_MAX_S e é barato perto de um salto visível no
    meio do Short.
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
        f"({MODELO}, {RESOLUCAO})."
    )
    if any(d > SEGMENTO_MAX_S for _, d in pedacos):
        _abortar(
            f"Pedaço acima do teto de {SEGMENTO_MAX_S}s do `duration` "
            f"({[d for _, d in pedacos]}) — a API recusaria a geração."
        )

    # O PRIMEIRO pedaço começa na FOTO — é ela que fixa a identidade da
    # influencer de um Short para o outro. Do segundo em diante, o quadro 1 vem
    # do pedaço anterior.
    quadro_inicial = IMAGEM
    prontos = []
    t0 = time.time()
    for i, (inicio, duracao) in enumerate(pedacos):
        arquivo = _pedaco(
            narracao, inicio, duracao, destino.parent / f"narracao_p{i}.mp3"
        )
        corpo = {
            "model": MODELO,
            "input": {
                "prompt": _prompt(cfg.publico),
                # `first_frame` + `driving_audio` é O modo de lipsync do
                # Model Studio: a imagem vira o quadro 1 e o MP3 move a boca.
                # Cada `type` só pode aparecer uma vez — por isso um pedaço
                # por tarefa.
                "media": [
                    {"type": "first_frame", "url": _subir(cfg, quadro_inicial)},
                    {"type": "driving_audio", "url": _subir(cfg, arquivo)},
                ],
            },
            "parameters": {
                # Sem `ratio` e sem `audio`: o wan2.7-i2v não tem nenhum dos
                # dois. A proporção sai da imagem, e o áudio do vídeo é o
                # próprio driver (que a montagem descarta — a narração que vai
                # ao ar é o MP3 da ElevenLabs).
                "resolution": RESOLUCAO,
                "duration": duracao,
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

        bruto = destino.parent / f"influencer_bruto{i}.mp4"
        _baixar(_esperar(cfg, tarefa, t0), bruto)
        desloc = _deslocamento(arquivo, bruto)
        print(
            f"[influencer] Segmento {i + 1}/{len(pedacos)}: {duracao}s, "
            f"silêncio de {desloc * 1000:.0f}ms na frente, descontado."
        )
        segmento = _encaixar(
            bruto, desloc, duracao, destino.parent / f"influencer_s{i}.mp4"
        )
        prontos.append(segmento)
        # O quadro 1 do próximo pedaço sai do arquivo JÁ ENCAIXADO, e não do
        # bruto: é este que vai ao ar, e é com ele que a emenda tem de casar.
        if i + 1 < len(pedacos):
            quadro_inicial = _ultimo_quadro(
                segmento, destino.parent / f"influencer_fim{i}.png"
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

    Nasceu no modo referência, em que o modelo REPINTAVA a cena e o verde
    mudava de geração para geração. No modo primeiro-quadro o fundo é o da
    própria influencer.png, então a constante voltou a ser confiável — mas a
    medição fica: ela custa oito quadros de leitura e cobre a deriva de tom que
    o modelo ainda pode introduzir ao longo dos segundos gerados.

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
