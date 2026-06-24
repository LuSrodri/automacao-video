"""Montagem final do vídeo com ffmpeg.

O fundo de cada momento é a PRÓPRIA imagem daquele trecho, ampliada para cobrir
a tela toda e BORRADA; por cima entra a imagem nítida em largura total, com uma
animação suave de zoom (Ken Burns). As imagens cobrem 100% da narração — nunca
há um instante sem figura na tela — e fazem crossfade entre si. A narração TTS
(sem silêncios) é a trilha, e o branding (logo do Shorts + @usuário) fica no
topo com bordas brancas.
"""

import subprocess
import shutil
from pathlib import Path

from .config import RAIZ

FPS = 30
MIN_EXIBICAO = 2.0  # segundos mínimos de exibição de cada imagem
MAX_EXIBICAO = 10.0  # segundos máximos de exibição de cada imagem
CROSSFADE = 0.4  # duração do crossfade entre imagens consecutivas
FADE = 0.35  # duração do fade de entrada do branding
BLUR_SIGMA = 18  # intensidade do desfoque do fundo
ESCURECER = -0.05  # brilho aplicado ao fundo borrado (realça a imagem nítida)
ZOOM_MAX = 1.15  # zoom máximo da animação
ZOOM_RATE = 0.0008  # incremento de zoom por quadro

# Efeito sonoro de "woosh" tocado em cada transição entre imagens.
WOOSH = RAIZ / "assets" / "woosh.mp3"
WOOSH_VOL = 0.5  # volume do efeito relativo à narração

# Branding discreto no topo: logo do YouTube Shorts + @usuário do canal.
LOGO_PADRAO = RAIZ / "assets" / "YouTube-Shorts-Logo.png"
FONTE_HANDLE = RAIZ / "fonts" / "Barlow-Bold.ttf"
LOGO_LARGURA_FRAC = 0.30  # largura do logo como fração da largura do vídeo
LOGO_OPACIDADE = 0.85  # opacidade do logo (0 a 1)
LOGO_Y_FRAC = 0.06  # distância do topo como fração da altura
LOGO_BORDA_FRAC = 0.02  # espessura da borda branca do logo (fração da sua largura)
HANDLE_OPACIDADE = 0.9  # opacidade do nome de usuário
HANDLE_FONTE_FRAC = 0.030  # tamanho da fonte como fração da largura
HANDLE_GAP_FRAC = 0.80  # posição do @usuário dentro da caixa do logo


def _exigir_ffmpeg() -> None:
    for binario in ("ffmpeg", "ffprobe"):
        if shutil.which(binario) is None:
            raise SystemExit(
                f"{binario} não encontrado no PATH. "
                "Instale o ffmpeg (winget install Gyan.FFmpeg) e reabra o terminal."
            )


def _probe(arquivo: Path, entrada: str, fluxo: str = "v:0") -> str:
    saida = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", fluxo,
            "-show_entries", entrada,
            "-of", "csv=p=0",
            str(arquivo),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return saida.stdout.strip().splitlines()[0] if saida.stdout.strip() else ""


def duracao_audio(audio: Path) -> float:
    saida = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(audio),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(saida.stdout.strip())


def _dimensoes(imagem: Path) -> tuple[int, int]:
    valores = _probe(imagem, "stream=width,height").split(",")
    return int(valores[0]), int(valores[1])


def _ordenar(sobreposicoes: list[dict]) -> list[dict]:
    """Ordena as imagens pelo ponto da narração em que cada uma entra."""
    return sorted(
        sobreposicoes,
        key=lambda s: (s.get("inicio_frac") is None, s.get("inicio_frac") or 0.0),
    )


# Quanto puxar o início de cada imagem para a distribuição uniforme (0 = usa só
# o ponto do trecho, gerando durações bem irregulares; 1 = ignora o trecho e
# espaça tudo igual). 0.6 equilibra: cada imagem fica perto do momento da
# narração que ilustra, mas sem piscar nem eternizar.
PESO_UNIFORME = 0.6
# Piso de duração de cada imagem, como fração do passo médio (duração/n). Garante
# que nenhuma imagem fique pouco tempo demais na tela.
PISO_FRACAO_PASSO = 0.5


def _calcular_janelas(
    sobreposicoes: list[dict], duracao: float
) -> list[tuple[float, float]]:
    """Janelas (início, fim) contíguas que cobrem TODA a narração.

    Cada imagem entra perto do ponto da narração do seu trecho e fica até a
    próxima entrar (a última vai até o fim), sem buracos. Para evitar durações
    irregulares (umas piscando, outras eternas), o início de cada imagem é uma
    MISTURA entre o ponto do trecho e uma distribuição uniforme, e um piso de
    duração impede janelas curtas demais. Imagens sem sincronização conhecida
    entram na posição uniforme.
    """
    n = len(sobreposicoes)
    if n == 0:
        return []

    passo = duracao / n
    piso = PISO_FRACAO_PASSO * passo

    inicios = []
    for i, s in enumerate(sobreposicoes):
        uniforme = i * passo
        frac = s.get("inicio_frac")
        if frac is None:
            inicios.append(uniforme)
        else:
            alvo = max(0.0, frac * duracao)
            inicios.append(PESO_UNIFORME * uniforme + (1 - PESO_UNIFORME) * alvo)

    # Garante ordem crescente, início em 0 e duração mínima (piso) em todas,
    # inclusive na última (reservando 'piso' para cada imagem ainda por vir).
    inicios[0] = 0.0
    for i in range(1, n):
        inicios[i] = max(inicios[i], inicios[i - 1] + piso)
        inicios[i] = min(inicios[i], duracao - (n - i) * piso)

    janelas = []
    for i in range(n):
        ini = inicios[i]
        fim = inicios[i + 1] if i + 1 < n else duracao
        janelas.append((ini, fim))
    return janelas


def intervalos_imagens(
    sobreposicoes: list[dict], duracao: float
) -> list[tuple[float, float]]:
    """Janelas em que há imagem na tela (com a cobertura total, é o vídeo todo).

    Mantido para as legendas decidirem a posição de cada trecho.
    """
    return _calcular_janelas(_ordenar(sobreposicoes), duracao)


def _caminho_filtro(caminho: Path) -> str:
    """Escapa um caminho Windows para uso dentro de filter_complex."""
    return str(caminho).replace("\\", "/").replace(":", "\\:")


def _texto_drawtext(texto: str) -> str:
    """Escapa um texto para uso dentro de text='...' do filtro drawtext."""
    return texto.replace("\\", "\\\\").replace("'", r"'\''")


def _par(valor: int) -> int:
    return valor if valor % 2 == 0 else valor + 1


def montar_video(
    narracao: Path,
    sobreposicoes: list[dict],
    destino: Path,
    largura: int,
    altura: int,
    legendas: Path | None = None,
    handle: str | None = None,
    logo: Path | None = LOGO_PADRAO,
) -> Path:
    """Monta o vídeo final com fundo borrado da própria imagem e zoom suave.

    `sobreposicoes`: [{"caminho": Path, "inicio_frac": float|None,
    "fim_frac": float|None}, ...] — frações (0 a 1) da narração em que a
    imagem entra; None usa distribuição uniforme. As imagens cobrem 100% da
    narração (sem instante vazio) e fazem crossfade entre si.

    `logo`/`handle`: branding no topo (logo do YouTube Shorts e @usuário), ambos
    com borda branca para destacar sobre o fundo da imagem.
    """
    _exigir_ffmpeg()

    duracao = duracao_audio(narracao) + 0.6

    sobreposicoes = _ordenar(sobreposicoes)
    janelas = _calcular_janelas(sobreposicoes, duracao)
    pares = list(zip(sobreposicoes, janelas))
    n = len(pares)
    for s, (ini, fim) in pares:
        if fim - ini > MAX_EXIBICAO + 0.01:
            print(
                f"[edicao] aviso: imagem fica {fim - ini:.1f}s na tela "
                f"(acima do alvo de {MAX_EXIBICAO:.0f}s)"
            )

    # Base preta (entrada 0); narração é a entrada 1. Com cobertura total, a
    # base só aparece se faltarem imagens.
    filtros = [f"[0:v]fps={FPS},format=rgba[base]"]
    corrente = "base"

    comando = [
        "ffmpeg", "-y", "-hide_banner",
        "-f", "lavfi",
        "-i", f"color=c=black:s={largura}x{altura}:r={FPS}:d={duracao:.2f}",
        "-i", str(narracao),
    ]

    for i, (s, (ini, fim)) in enumerate(pares):
        fim_render = min(fim + CROSSFADE, duracao)
        dur_render = fim_render - ini
        comando += ["-loop", "1", "-t", f"{dur_render:.2f}", "-i", str(s["caminho"])]

        idx = i + 2
        larg_img, alt_img = _dimensoes(s["caminho"])
        fg_h = _par(round(largura * alt_img / max(larg_img, 1)))

        fade_in = (
            f"fade=t=in:st=0:d={CROSSFADE}:alpha=1," if i > 0 else ""
        )
        fade_out = (
            f"fade=t=out:st={max(0.0, dur_render - CROSSFADE):.2f}:d={CROSSFADE}:alpha=1,"
            if i < n - 1 else ""
        )

        # Achata sobre BRANCO antes de dividir: imagens com fundo transparente
        # (logos, recortes em PNG) ganham um fundo branco sólido em vez de deixar
        # o vídeo vazar por trás. Fotos opacas não mudam (o branco fica coberto).
        filtros.append(f"color=c=white:s={larg_img}x{alt_img}:r={FPS}[wbg{i}]")
        filtros.append(f"[{idx}:v]fps={FPS},format=rgba[src{i}]")
        filtros.append(
            f"[wbg{i}][src{i}]overlay=0:0:shortest=1,format=rgba,"
            f"split[in_bg{i}][in_fg{i}]"
        )

        # Fundo: a própria imagem cobrindo a tela toda, borrada e levemente escura.
        filtros.append(
            f"[in_bg{i}]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
            f"crop={largura}:{altura},gblur=sigma={BLUR_SIGMA},"
            f"eq=brightness={ESCURECER},"
            f"{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[bg{i}]"
        )

        # Frente: imagem nítida em largura total com zoom suave (alterna a direção).
        if i % 2 == 0:
            zoom = f"min(1+{ZOOM_RATE}*on,{ZOOM_MAX})"
        else:
            zoom = f"max({ZOOM_MAX}-{ZOOM_RATE}*on,1.0)"
        filtros.append(
            f"[in_fg{i}]scale={largura}:-2,"
            f"zoompan=z='{zoom}':d=1:s={largura}x{fg_h}:fps={FPS}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
            f"format=rgba,{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[fg{i}]"
        )

        # Sobrepõe fundo e depois a frente, ambos ativos na janela (+ crossfade).
        filtros.append(
            f"[{corrente}][bg{i}]overlay=0:0:eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[b{i}]"
        )
        # "Woosh": a imagem nítida desliza para o centro durante o crossfade,
        # alternando o lado (direita/esquerda), em sincronia com o efeito sonoro.
        if i == 0:
            x_fg = "(W-w)/2"
        else:
            sinal = "+" if i % 2 == 0 else "-"
            prog = f"(1-min(1\\,(t-{ini:.2f})/{CROSSFADE:.2f}))"
            x_fg = f"(W-w)/2{sinal}(W+w)/2*{prog}"
        filtros.append(
            f"[b{i}][fg{i}]overlay={x_fg}:(H-h)/2:eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[f{i}]"
        )
        corrente = f"f{i}"

    if legendas is not None:
        fontes = RAIZ / "fonts"
        filtro_ass = f"ass='{_caminho_filtro(legendas)}'"
        if fontes.is_dir():
            filtro_ass += f":fontsdir='{_caminho_filtro(fontes)}'"
        filtros.append(f"[{corrente}]{filtro_ass}[vleg]")
        corrente = "vleg"

    # Branding no topo (sobre tudo). O logo é a última entrada do ffmpeg.
    usar_logo = logo is not None and Path(logo).is_file()
    if usar_logo:
        idx_logo = 2 + n
        comando += ["-loop", "1", "-i", str(logo)]
        log_l, log_a = _dimensoes(logo)
        largura_logo = round(largura * LOGO_LARGURA_FRAC)
        altura_logo = round(largura_logo * log_a / log_l)
        y_logo = round(altura * LOGO_Y_FRAC)
        borda = max(3, round(largura_logo * LOGO_BORDA_FRAC))
        # Borda branca: uma cópia branca do logo, um pouco maior, atrás do logo.
        filtros.append(
            f"[{idx_logo}:v]format=rgba,scale={largura_logo}:-1,split[lg][lg2]"
        )
        filtros.append(
            f"[lg2]lutrgb=r=255:g=255:b=255,scale={largura_logo + 2 * borda}:-1[halo]"
        )
        filtros.append(
            f"[halo][lg]overlay=(W-w)/2:(H-h)/2[logocb]"
        )
        filtros.append(
            f"[logocb]colorchannelmixer=aa={LOGO_OPACIDADE},"
            f"fade=t=in:st=0:d={FADE}:alpha=1[logo]"
        )
        filtros.append(
            f"[{corrente}][logo]overlay=(W-w)/2:{y_logo}:eof_action=pass[vlogo]"
        )
        corrente = "vlogo"

    if handle and FONTE_HANDLE.is_file():
        y_base = round(altura * LOGO_Y_FRAC)
        if usar_logo:
            y_handle = y_base + round(altura_logo * HANDLE_GAP_FRAC)
        else:
            y_handle = y_base
        fonte = round(largura * HANDLE_FONTE_FRAC)
        borda_txt = max(2, round(fonte * 0.12))
        filtros.append(
            f"[{corrente}]drawtext=fontfile='{_caminho_filtro(FONTE_HANDLE)}'"
            f":text='{_texto_drawtext(handle)}':fontcolor=black"
            f":borderw={borda_txt}:bordercolor=white"
            f":fontsize={fonte}"
            f":x=(w-text_w)/2:y={y_handle}"
            f":alpha='if(lt(t,{FADE}),{HANDLE_OPACIDADE}*t/{FADE},{HANDLE_OPACIDADE})'"
            f"[vbrand]"
        )
        corrente = "vbrand"

    # Efeito sonoro de woosh em cada transição (no instante em que a próxima
    # imagem começa a deslizar). A primeira imagem não tem transição de entrada.
    mapa_audio = "1:a"
    transicoes = [ini for _, (ini, _) in pares[1:]]
    if WOOSH.is_file() and transicoes:
        idx_woosh = 2 + n + (1 if usar_logo else 0)
        comando += ["-i", str(WOOSH)]
        m = len(transicoes)
        filtros.append(
            "[1:a]aformat=channel_layouts=stereo:sample_rates=44100[narr]"
        )
        filtros.append(
            f"[{idx_woosh}:a]asplit={m}" + "".join(f"[ws{k}]" for k in range(m))
        )
        rotulos = []
        for k, t in enumerate(transicoes):
            ms = max(0, round(t * 1000))
            filtros.append(
                f"[ws{k}]adelay={ms}:all=1,"
                f"aformat=channel_layouts=stereo:sample_rates=44100,"
                f"volume={WOOSH_VOL}[wd{k}]"
            )
            rotulos.append(f"[wd{k}]")
        filtros.append(
            f"[narr]{''.join(rotulos)}amix=inputs={m + 1}:normalize=0"
            f":duration=first,alimiter=limit=0.97[aout]"
        )
        mapa_audio = "[aout]"

    comando += [
        "-filter_complex", ";".join(filtros),
        "-map", f"[{corrente}]",
        "-map", mapa_audio,
        "-t", f"{duracao:.2f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(destino),
    ]

    print("[edicao] Montando vídeo final com ffmpeg...")
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise SystemExit(f"ffmpeg falhou:\n{resultado.stderr[-2000:]}")

    print(f"[edicao] Vídeo final salvo em {destino}")
    return destino
