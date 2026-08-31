"""Enquadramento inteligente do clipe horizontal dentro do quadro vertical.

O PROBLEMA. Um clipe 16:9 num Short 9:16 sempre foi encaixado por `edicao.py`
com a barra borrada em cima e embaixo: o clipe nítido entra no maior tamanho
que CABE no quadro, centrado. Com fonte 1280x720 isso dá 1080x608 num quadro de
1920 de altura — 32% da tela e nada mais. Os outros 68% são desfoque do próprio
clipe, e num formato em que a tela inteira é o produto isso é espaço morto.

A saída é RECORTAR o clipe em vez de encolhê-lo, e mover o recorte para
acompanhar quem está em cena. Recorte de centro fixo não serve: decapita o
sujeito assim que ele sai do meio do quadro, que é o caso normal em filmagem de
rua, coletiva e câmera na mão.

O RECORTE VAI ATÉ 9:16 CHEIO (2026-08-31, pedido explícito do usuário). Até
aqui a largura da janela era governada por um teto de ampliação (UPSCALE_MAX,
1,6): a janela nunca era mais estreita que 675 px, o clipe enchia a tela na
proporção `altura da fonte / 1200` e o resto continuava sendo desfoque — 60% de
tela numa fonte 720p, que é a fonte normal do X. O teto SAIU. A janela é agora
exatamente a proporção do quadro, e o clipe preenche o quadro inteiro venha ele
de onde vier.

O CUSTO É NITIDEZ, e ele foi aceito de olho aberto: 9:16 de uma fonte 720p é
uma janela de 404 px que sobe 2,67x até os 1080 do quadro. Quanto menor a
fonte, pior — daí o fator de ampliação sair no log da montagem, para que a
conta apareça em vez de ficar implícita. Quem quiser o compromisso de volta não
reintroduz teto aqui: mexe no piso de resolução do clipe, lá na triagem.

QUEM GARANTE O PREENCHIMENTO NÃO É ESTE MÓDULO. `edicao.py` escala a camada
nítida por COBERTURA (`increase` + `crop`), então o quadro fica cheio mesmo sem
plano nenhum — só que aí o recorte é de centro fixo. Este módulo decide ONDE a
janela fica e como ela anda; devolver None aqui não devolve a barra borrada,
devolve a câmera parada no meio. Sem folga horizontal, sem quadro legível ou
sem OpenCV instalado é isso que acontece: acabamento degrada, não aborta (ao
contrário da diretriz de fail-fast que vale para API e chave).

COMO A TRAJETÓRIA CHEGA NO FFMPEG. Não por `sendcmd`: no formato longo os
clipes entram com `-stream_loop -1` (edicao.py) e comando de sendcmd dispara uma
vez só, morrendo no primeiro reinício do clipe. Em vez disso a trajetória vira
EXPRESSÃO no `x` do filtro `crop`, que o ffmpeg reavalia a cada quadro, no mesmo
idioma piecewise que `edicao._expr_progresso` já usa. Quando o clipe é mais
curto que a janela em que fica no ar, o tempo entra como `mod(t,span)` para a
trajetória dar a volta junto com a imagem.

O `mod` ficou inerte NO SHORT desde 2026-08-28, e de propósito: o loop saiu do
formato curto e as janelas passam a ser encaixadas no material
(`edicao._encaixar_no_material`), então lá a janela nunca é mais longa que o
clipe e o tempo entra como `t` puro. O ramo continua vivo para o formato longo,
que segue repetindo clipe.

POR QUE A EXPRESSÃO É CURTA. Ela só cabe porque a suavização não é um filtro
contínuo (savgol, média móvel) e sim um AJUSTE POR PATAMARES: a série de alvos é
aproximada por poucos trechos parados, ligados por rampas com aceleração nas
pontas. Isso é o que faz a câmera ler como operador humano — parado / movimento
/ parado — em vez de mola perseguindo o sujeito. Detecção ruim com câmera bem
amortecida fica boa; detecção perfeita com câmera crua fica enjoativa.

O ZOOM FICA TRAVADO POR CLIPE, de propósito. `crop` aceita expressão em `w`
também, mas largura variável reinicializa o `scale` seguinte a cada quadro e,
pior, muda o `w` que o `overlay` de `edicao.py` usa para centralizar — o clipe
tremeria na horizontal. Zoom contínuo respirando também é o que mais denuncia
automação.

Este módulo NÃO importa `edicao`: a dependência é de mão única (edicao ->
enquadramento). Por isso as dimensões da fonte chegam como argumento e o
smoothstep está duplicado aqui em vez de importado.
"""

import os
import subprocess
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:  # ambiente sem as libs: o módulo inteiro vira no-op
    cv2 = None
    np = None

from .config import RAIZ


def ativo() -> bool:
    """Chave geral (`ZOOM_INTELIGENTE=0` desliga), lida na HORA DE USAR.

    Lida aqui e não numa constante de módulo de propósito: `load_dotenv` só roda
    dentro de `config.carregar_config()`, bem depois do import deste módulo. Uma
    constante avaliada no import enxergaria a variável de ambiente do Render mas
    NÃO a do arquivo `.env` local — a chave funcionaria em produção e falharia
    calada na bancada, que é o pior dos dois mundos.
    """
    return os.getenv("ZOOM_INTELIGENTE", "1") != "0"


MODELO_ROSTO = RAIZ / "assets" / "face_detection_yunet_2023mar.onnx"

# --- Amostragem -----------------------------------------------------------
# 6 quadros por segundo a 180 de altura. A trajetória é suave por construção;
# amostrar a 30 fps custaria 5x a decodificação para mover os mesmos patamares.
FPS_AMOSTRA = 6
ALTURA_AMOSTRA = 180

# --- Recorte --------------------------------------------------------------
# Abaixo desta folga horizontal não há curso de câmera que valha a pena: o
# recorte de `edicao.py` preenche o quadro do mesmo jeito, parado no centro.
FOLGA_MINIMA_FRAC = 0.08

# --- Câmera virtual -------------------------------------------------------
# Tolerância do patamar, em fração da largura do recorte. É TAMBÉM a deadzone:
# o sujeito passeia dentro dela sem que a câmera se mexa.
DEADZONE_FRAC = 0.12
# A câmera mira onde o sujeito ESTARÁ daqui a tanto tempo, em vez de correr
# atrás de onde ele esteve.
ANTECIPACAO_S = 0.25
# Movimento mais curto ou mais raso que isto é tremor, não decisão: é absorvido
# pelo patamar vizinho.
MOV_MIN_S = 0.5
MOV_MIN_FRAC = 0.04
MAX_MOVIMENTOS = 4
# Velocidade do pan, em larguras de recorte por segundo, e limites da rampa.
VEL_FRAC = 0.35
RAMPA_MIN_S = 0.4
RAMPA_MAX_S = 1.6
# Patamar mais curto que isto entre duas rampas não é pausa, é engasgo: as duas
# rampas viram uma só.
HOLD_MIN_S = 0.35

# --- Detecção -------------------------------------------------------------
CONF_ROSTO = 0.6
# Corte de cena medido pela FRAÇÃO do quadro que mudou muito, não pela
# diferença média: num corte quase todo pixel muda de uma vez, enquanto um
# sujeito andando mexe poucos por cento da tela. Em bancada os dois casos ficam
# em 1,000 e 0,000 — a média não separava nada (dois fundos de cor diferente e
# luma parecida davam 0,12, abaixo de qualquer limiar utilizável).
CORTE_DELTA = 25  # níveis de mudança que contam como "mudou"
CORTE_FRAC = 0.6  # fração do quadro que precisa mudar
# Pico mínimo (0-255) da diferença temporal para acreditar que há movimento.
# Medido no pico e não na média: um sujeito ocupando 2% da tela move a média em
# menos de um nível e some, por mais nítido que esteja o movimento.
MOVIMENTO_PISO = 12
# Acima disto o que se mexeu foi o quadro inteiro (pan, corte, tremida) e não
# um sujeito dentro dele.
MOVIMENTO_FRAC_MAX = 0.5


def _suave(u: str) -> str:
    """smoothstep sobre uma expressão ffmpeg já normalizada em [0,1].

    Cópia deliberada de `edicao._suave` (edicao.py:311): importar de lá faria o
    import circular, e inverter a hierarquia dos módulos por causa de uma linha
    custa mais que duplicá-la.
    """
    return f"({u})*({u})*(3-2*({u}))"


def _largura_recorte(src_l: int, src_a: int, alvo_l: int, alvo_a: int) -> int | None:
    """A janela na PROPORÇÃO DO QUADRO, ou None se não houver curso de câmera.

    A largura é a do quadro cheio e ponto — o teto de ampliação saiu em
    2026-08-31 (ver o cabeçalho). O par ímpar é evitado porque o x264 exige
    dimensão par e o `crop` não arredonda sozinho.
    """
    if src_l <= 0 or src_a <= 0 or alvo_l <= 0 or alvo_a <= 0:
        return None
    # Fonte já tão estreita quanto o alvo: não há o que recortar na horizontal
    # (o que sobrar na vertical é a cobertura de `edicao.py` que resolve).
    if src_l * alvo_a <= alvo_l * src_a:
        return None
    crop_l = int(min(float(src_l), src_a * alvo_l / alvo_a))
    crop_l -= crop_l % 2
    if crop_l <= 0 or src_l - crop_l < FOLGA_MINIMA_FRAC * src_l:
        return None
    return crop_l


def _quadros(caminho: Path, ini_s: float, dur_s: float, src_l: int, src_a: int):
    """Decodifica a janela do clipe em quadros BGR pequenos.

    Por ffmpeg e não por `cv2.VideoCapture`: o `-ss` do OpenCV é impreciso e
    traria um segundo decodificador para dentro do processo. O cv2 aqui só
    DETECTA. Mesmo idioma de `midia_x._reduzir`.
    """
    larg = max(2, int(round(ALTURA_AMOSTRA * src_l / src_a / 2)) * 2)
    comando = [
        "ffmpeg", "-v", "error", "-nostdin",
        "-ss", f"{max(ini_s, 0.0):.2f}",
        "-t", f"{dur_s:.2f}",
        "-i", str(caminho),
        "-vf", f"fps={FPS_AMOSTRA},scale={larg}:{ALTURA_AMOSTRA}",
        "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    try:
        r = subprocess.run(comando, capture_output=True, check=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    passo = larg * ALTURA_AMOSTRA * 3
    n = len(r.stdout) // passo
    if n < 2:
        return None
    bruto = np.frombuffer(r.stdout[: n * passo], np.uint8)
    return bruto.reshape(n, ALTURA_AMOSTRA, larg, 3).copy()


def _cortes(quadros) -> set[int]:
    """Índices de amostra em que começa um plano novo."""
    cortes = set()
    for i in range(1, len(quadros)):
        d = np.abs(quadros[i].astype(np.int16) - quadros[i - 1].astype(np.int16))
        if float((d.mean(axis=2) > CORTE_DELTA).mean()) > CORTE_FRAC:
            cortes.add(i)
    return cortes


def _detector(larg: int, alt: int):
    if not MODELO_ROSTO.exists():
        return None
    try:
        return cv2.FaceDetectorYN.create(
            str(MODELO_ROSTO), "", (larg, alt), CONF_ROSTO, 0.3, 5000
        )
    except cv2.error:
        return None


def _alvo_rosto(det, quadro) -> tuple[float, float]:
    """Centroide horizontal dos rostos, ponderado por área x confiança."""
    try:
        _, rostos = det.detect(quadro)
    except cv2.error:
        return 0.0, 0.0
    if rostos is None or len(rostos) == 0:
        return 0.0, 0.0
    peso = rostos[:, 2] * rostos[:, 3] * rostos[:, 14]
    total = float(peso.sum())
    if total <= 0:
        return 0.0, 0.0
    cx = rostos[:, 0] + rostos[:, 2] / 2.0
    return float((cx * peso).sum() / total), 1.0


def _alvo_movimento(atual, anterior) -> tuple[float, float]:
    """Sem rosto: centroide do que se mexeu na diferença temporal.

    O limiar é relativo ao PICO da diferença, não um percentil fixo: quando o
    sujeito ocupa 2% da tela, o percentil 90 cai em cima do fundo parado e o
    centroide vira o centro do quadro — que é exatamente o que se queria evitar.
    """
    d = cv2.GaussianBlur(cv2.absdiff(atual, anterior), (0, 0), 3)
    pico = float(d.max())
    if pico < MOVIMENTO_PISO:
        return 0.0, 0.0  # plano parado: não há sujeito a seguir
    quente = d >= max(float(MOVIMENTO_PISO), pico * 0.5)
    if not (0 < quente.mean() <= MOVIMENTO_FRAC_MAX):
        return 0.0, 0.0
    coluna = np.where(quente, d.astype(np.float32), 0.0).sum(axis=0)
    total = float(coluna.sum())
    if total <= 0:
        return 0.0, 0.0
    x = float((np.arange(coluna.size) * coluna).sum() / total)
    return x, min(1.0, pico / 60.0)


def _alvos(quadros, cinza, cortes: set[int]) -> tuple:
    """Alvo horizontal por amostra, em pixels da AMOSTRA, com confiança.

    Cascata: rosto primeiro (é o que o espectador segue), saliência por
    movimento quando não há rosto, e nada quando o plano está parado — amostra
    sem confiança não vota, é interpolada pelas vizinhas do MESMO plano.

    Na primeira amostra de cada plano só o rosto vale: a diferença temporal ali
    compara quadros de planos DIFERENTES, e o que ela mede é o corte, não o
    sujeito. Em bancada esse alvo falso ancorava o plano inteiro na borda.
    """
    n, alt, larg = cinza.shape
    det = _detector(larg, alt)
    xs = np.full(n, larg / 2.0)
    conf = np.zeros(n)
    for i in range(n):
        if det is not None:
            x, c = _alvo_rosto(det, quadros[i])
            if c > 0:
                xs[i], conf[i] = x, c
                continue
        if i > 0 and i not in cortes:
            x, c = _alvo_movimento(cinza[i], cinza[i - 1])
            if c > 0:
                xs[i], conf[i] = x, c
    return xs, conf


def _planos(n: int, cortes: set[int]) -> list[tuple[int, int]]:
    """Intervalos [ini, fim) de cada plano da janela analisada."""
    limites = [0] + sorted(c for c in cortes if 0 < c < n) + [n]
    return [(a, b) for a, b in zip(limites, limites[1:]) if b > a]


def _centros(xs, conf, cortes: set[int], larg: int, src_l: int, crop_l: int):
    """Alvo por amostra em pixels da FONTE, já antecipado e dentro do quadro.

    Tudo aqui é POR PLANO. Interpolar amostra fraca por cima de um corte faz o
    plano seguinte herdar o alvo do anterior — em bancada, um plano inteiro sem
    sujeito detectável colava a câmera na borda direita porque era lá que o
    plano de trás tinha terminado. Plano sem nenhuma amostra confiável fica no
    centro, que é o palpite honesto quando não se sabe onde olhar.
    """
    alvo = np.full(len(xs), larg / 2.0)
    for a, b in _planos(len(xs), cortes):
        bons = np.flatnonzero(conf[a:b] > 0)
        if bons.size:
            alvo[a:b] = np.interp(np.arange(b - a), bons, xs[a:b][bons])
    alvo *= src_l / larg

    # Antecipação: mira onde o sujeito estará, não onde ele esteve. A derivada
    # também é por plano — velocidade medida através de um corte é ruído.
    centro = alvo.copy()
    for a, b in _planos(len(xs), cortes):
        if b - a >= 2:
            centro[a:b] += np.gradient(alvo[a:b]) * FPS_AMOSTRA * ANTECIPACAO_S
    return np.clip(centro, crop_l / 2, src_l - crop_l / 2)


def _patamares(valores, tol: float) -> list[list]:
    """Aproxima a série por trechos parados: segura enquanto o erro couber."""
    seg: list[list] = []
    i, n = 0, len(valores)
    while i < n:
        lo = hi = float(valores[i])
        j = i
        while j + 1 < n:
            nlo = min(lo, float(valores[j + 1]))
            nhi = max(hi, float(valores[j + 1]))
            if nhi - nlo > 2 * tol:
                break
            lo, hi, j = nlo, nhi, j + 1
        seg.append([i, j, (lo + hi) / 2.0])
        i = j + 1
    return seg


def _duracao(p: list) -> int:
    return p[1] - p[0]


def _limpar(seg: list[list], min_amostras: int, min_px: float, max_seg: int) -> list[list]:
    """Funde patamar curto demais ou raso demais — tremor não é decisão."""
    while len(seg) > 1:
        curtos = [k for k in range(len(seg)) if _duracao(seg[k]) + 1 < min_amostras]
        difs = [abs(seg[k + 1][2] - seg[k][2]) for k in range(len(seg) - 1)]
        if not curtos and min(difs) >= min_px and len(seg) <= max_seg:
            break
        if curtos:
            k = min(curtos, key=lambda i: _duracao(seg[i]))
            if k == 0:
                v = 0
            elif k == len(seg) - 1:
                v = k - 1
            elif abs(seg[k][2] - seg[k - 1][2]) <= abs(seg[k + 1][2] - seg[k][2]):
                v = k - 1
            else:
                v = k
        else:
            v = difs.index(min(difs))
        a, b = seg[v], seg[v + 1]
        na, nb = _duracao(a) + 1, _duracao(b) + 1
        seg[v : v + 2] = [[a[0], b[1], (a[2] * na + b[2] * nb) / (na + nb)]]
    return seg


def _trajetoria(centros, cortes: set[int], tol: float, crop_l: int) -> tuple[list, list]:
    """Patamares do clipe inteiro + se cada junção é um CORTE (salto seco).

    Cada plano é ajustado por si: interpolar por cima de um corte produz um pan
    fantasma no primeiro quadro do plano seguinte.
    """
    seg: list[list] = []
    saltos: list[bool] = []
    min_amostras = max(1, int(round(MOV_MIN_S * FPS_AMOSTRA)))
    for a, b in _planos(len(centros), cortes):
        plano = _limpar(
            _patamares(centros[a:b], tol),
            min_amostras,
            MOV_MIN_FRAC * crop_l,
            MAX_MOVIMENTOS,
        )
        if seg:
            saltos.append(True)  # junção entre planos: corte, não pan
        saltos += [False] * (len(plano) - 1)
        seg += [[a + p[0], a + p[1], p[2]] for p in plano]
    return seg, saltos


def _expressao(seg: list[list], saltos: list[bool], crop_l: int, tempo: str) -> str:
    """Soma de termos com porta, no idioma de `edicao._expr_progresso`."""
    if len(seg) == 1:
        return f"{seg[0][2]:.1f}"

    transicoes = []
    for k in range(len(seg) - 1):
        centro = (seg[k][1] + seg[k + 1][0]) / 2.0 / FPS_AMOSTRA
        dx = seg[k + 1][2] - seg[k][2]
        if saltos[k]:
            dur = 0.0
        else:
            dur = min(max(abs(dx) / (VEL_FRAC * crop_l), RAMPA_MIN_S), RAMPA_MAX_S)
            # A rampa não pode comer mais que o patamar vizinho mais curto.
            vizinho = min(_duracao(seg[k]), _duracao(seg[k + 1])) / FPS_AMOSTRA
            dur = min(dur, max(vizinho, 0.0))
        transicoes.append([centro - dur / 2, centro + dur / 2, seg[k][2], seg[k + 1][2]])

    # Duas rampas separadas por um patamar curto demais viram UMA rampa. Um
    # sujeito que atravessa o quadro inteiro produz vários patamares seguidos,
    # e respeitar todos daria uma escadinha com pausas de 0,2s — que não lê como
    # pausa, lê como engasgo. Corte (rampa de duração zero) nunca funde.
    i = 0
    while i < len(transicoes) - 1:
        a, b = transicoes[i], transicoes[i + 1]
        if a[1] > a[0] and b[1] > b[0] and b[0] - a[1] < HOLD_MIN_S:
            transicoes[i : i + 2] = [[a[0], b[1], a[2], b[3]]]
        else:
            i += 1

    termos: list[str] = []
    anterior = None
    for ini, fim, x0, x1 in transicoes:
        porta = (
            f"lt({tempo},{ini:.3f})"
            if anterior is None
            else f"gte({tempo},{anterior:.3f})*lt({tempo},{ini:.3f})"
        )
        termos.append(f"{porta}*{x0:.1f}")
        if fim > ini:
            u = f"(({tempo}-{ini:.3f})/{fim - ini:.3f})"
            termos.append(
                f"gte({tempo},{ini:.3f})*lt({tempo},{fim:.3f})"
                f"*({x0:.1f}+({x1 - x0:.1f})*{_suave(u)})"
            )
        anterior = fim
    termos.append(f"gte({tempo},{anterior:.3f})*{seg[-1][2]:.1f}")
    return "+".join(termos)


def planejar(
    caminho: Path,
    ini_s: float,
    dur_s: float,
    src_l: int,
    src_a: int,
    alvo_l: int,
    alvo_a: int,
) -> dict | None:
    """Recorte e trajetória do clipe, ou None para manter o encaixe de hoje.

    Devolve {"crop_l", "crop_a", "expr_x", "movimentos"}: a janela fixa e a
    expressão ffmpeg do canto ESQUERDO dela ao longo do tempo, em pixels da
    fonte. `ini_s` e `dur_s` são o mesmo `-ss`/`-t` com que a montagem põe o
    clipe no ar — a trajetória cobre exatamente o trecho que vai ao ar.
    """
    if not ativo() or cv2 is None or np is None:
        return None
    try:
        crop_l = _largura_recorte(src_l, src_a, alvo_l, alvo_a)
        if crop_l is None:
            return None

        quadros = _quadros(caminho, ini_s, dur_s, src_l, src_a)
        if quadros is None:
            return None
        cinza = np.stack([cv2.cvtColor(q, cv2.COLOR_BGR2GRAY) for q in quadros])

        cortes = _cortes(quadros)
        xs, conf = _alvos(quadros, cinza, cortes)
        if not (conf > 0).any():
            return None  # nada detectado: fica o recorte de centro fixo

        centro = _centros(xs, conf, cortes, cinza.shape[2], src_l, crop_l)

        seg, saltos = _trajetoria(centro, cortes, DEADZONE_FRAC * crop_l, crop_l)
        if not seg:
            return None
        # Do centro do sujeito para o canto esquerdo da janela, dentro do quadro.
        for p in seg:
            p[2] = min(max(p[2] - crop_l / 2, 0.0), float(src_l - crop_l))

        # O clipe deu menos quadros que a janela pedida: ele vai LOOPAR no ar
        # (`-stream_loop -1`), então a trajetória dá a volta junto.
        span = len(centro) / FPS_AMOSTRA
        tempo = f"mod(t,{span:.3f})" if span < dur_s - 0.05 else "t"

        return {
            "crop_l": crop_l,
            "crop_a": int(src_a),
            "expr_x": _expressao(seg, saltos, crop_l, tempo),
            "movimentos": len(seg) - 1,
        }
    except Exception:  # acabamento nunca derruba a montagem
        return None
