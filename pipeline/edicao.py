"""Montagem final do vídeo com ffmpeg.

O fundo é uma tela branca; a narração TTS entra como trilha. Cada imagem-chave
entra centralizada ocupando toda a largura, com zoom-in lento, sincronizada com
o trecho da narração a que se refere.
"""

import subprocess
import shutil
from pathlib import Path

from .config import RAIZ

FPS = 30
ZOOM_TOTAL = 0.16  # quanto a imagem cresce ao longo da exibição
MIN_EXIBICAO = 2.0  # segundos mínimos de exibição de cada imagem
FOLGA = 0.25  # intervalo entre uma imagem e a seguinte
FADE = 0.35  # duração do fade de entrada/saída da imagem

# Branding discreto no topo: logo do YouTube Shorts + @usuário do canal.
LOGO_PADRAO = RAIZ / "assets" / "YouTube-Shorts-Logo.png"
FONTE_HANDLE = RAIZ / "fonts" / "Barlow-Bold.ttf"
LOGO_LARGURA_FRAC = 0.30  # largura do logo como fração da largura do vídeo
LOGO_OPACIDADE = 0.55  # opacidade do logo (0 a 1)
LOGO_Y_FRAC = 0.06  # distância do topo como fração da altura
HANDLE_OPACIDADE = 0.65  # opacidade do nome de usuário
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


def _calcular_janelas(
    sobreposicoes: list[dict], duracao: float
) -> list[tuple[float, float] | None]:
    """Converte frações da narração em janelas (início, fim) em segundos.

    Devolve uma lista alinhada com `sobreposicoes`; None indica que não
    sobrou espaço no vídeo para exibir aquela imagem.
    """
    janelas = []
    passo = duracao / max(len(sobreposicoes), 1)
    for i, s in enumerate(sobreposicoes):
        if s.get("inicio_frac") is None:
            # Sem sincronização conhecida: distribui uniformemente
            ini, fim = i * passo + 0.3, (i + 1) * passo - 0.3
        else:
            ini = s["inicio_frac"] * duracao
            fim = max(s["fim_frac"] * duracao, ini + MIN_EXIBICAO)
        janelas.append((ini, fim))

    # Remove sobreposições entre janelas consecutivas (a lista já chega
    # ordenada pelo início da narração)
    ajustadas: list[tuple[float, float] | None] = []
    fim_anterior = 0.0
    for ini, fim in janelas:
        ini = max(0.0, ini, fim_anterior + FOLGA)
        fim = min(max(fim, ini + MIN_EXIBICAO), duracao - 0.1)
        if fim - ini < 1.0:
            # Sem espaço restante no vídeo para esta imagem
            ajustadas.append(None)
            continue
        ajustadas.append((ini, fim))
        fim_anterior = fim
    return ajustadas


def intervalos_imagens(
    sobreposicoes: list[dict], duracao: float
) -> list[tuple[float, float]]:
    """Janelas (início, fim) em que alguma imagem está na tela.

    Usado pelas legendas para decidir a posição de cada trecho (centralizado
    quando não há imagem; mais abaixo quando há). Determinístico: produz as
    mesmas janelas que `montar_video` usa para posicionar as imagens.
    """
    janelas = _calcular_janelas(_ordenar(sobreposicoes), duracao)
    return [j for j in janelas if j is not None]


def _caminho_filtro(caminho: Path) -> str:
    """Escapa um caminho Windows para uso dentro de filter_complex."""
    return str(caminho).replace("\\", "/").replace(":", "\\:")


def _texto_drawtext(texto: str) -> str:
    """Escapa um texto para uso dentro de text='...' do filtro drawtext."""
    return texto.replace("\\", "\\\\").replace("'", r"'\''")


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
    """Monta o vídeo final sobre um fundo branco.

    `sobreposicoes`: [{"caminho": Path, "inicio_frac": float|None,
    "fim_frac": float|None}, ...] — frações (0 a 1) da narração em que a
    imagem entra e sai; None usa distribuição uniforme.

    `logo`/`handle`: branding discreto no topo — o logo do YouTube Shorts e o
    nome de usuário do canal (ex.: "@CanalDeTecnologia"). Cada um é opcional;
    o logo só entra se o arquivo existir e o @usuário só entra se informado.
    """
    _exigir_ffmpeg()

    duracao = duracao_audio(narracao) + 0.6

    # Mantém janela e imagem pareadas: ordena pelo ponto da narração em que
    # cada imagem entra (sem sincronização conhecida vai para o final)
    sobreposicoes = _ordenar(sobreposicoes)
    janelas = _calcular_janelas(sobreposicoes, duracao)
    pares = [(s, j) for s, j in zip(sobreposicoes, janelas) if j is not None]
    descartadas = len(sobreposicoes) - len(pares)
    if descartadas:
        print(f"[edicao] {descartadas} imagem(ns) sem espaço no vídeo, descartada(s)")

    # Fundo branco gerado pelo ffmpeg (entrada 0); narração é a entrada 1.
    filtros = [f"[0:v]fps={FPS},format=rgba[base]"]
    corrente = "base"

    fator_pad = 1 + ZOOM_TOTAL
    for i, (s, (ini, fim)) in enumerate(pares):
        img_l, img_a = _dimensoes(s["caminho"])
        altura_overlay = max(2, round(largura * img_a / img_l / 2) * 2)
        dur_j = fim - ini
        quadros = max(2, round(dur_j * FPS))
        # A imagem ganha uma borda transparente e o zoom avança sobre ela:
        # o quadro cresce de ~86% até 100% da largura, sem cortar conteúdo.
        # Sobre-amostragem (4x) + renderização em 2x com downscale final
        # eliminam o flicker do zoompan.
        filtros.append(
            f"[{i + 2}:v]format=rgba,scale={largura * 4}:-2,"
            f"pad=w=iw*{fator_pad}:h=ih*{fator_pad}"
            f":x=(ow-iw)/2:y=(oh-ih)/2:color=black@0.0,"
            f"zoompan=z='min(1+{ZOOM_TOTAL}*on/{quadros},{fator_pad})'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={quadros}:s={largura * 2}x{altura_overlay * 2}:fps={FPS},"
            f"scale={largura}:{altura_overlay},format=rgba,"
            f"fade=t=in:st=0:d={FADE}:alpha=1,"
            f"fade=t=out:st={max(0.0, dur_j - FADE):.2f}:d={FADE}:alpha=1,"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[img{i}]"
        )
        filtros.append(
            f"[{corrente}][img{i}]overlay=(W-w)/2:(H-h)/2"
            f":eof_action=pass:enable='between(t,{ini:.2f},{fim:.2f})'[v{i}]"
        )
        corrente = f"v{i}"

    if legendas is not None:
        fontes = RAIZ / "fonts"
        filtro_ass = f"ass='{_caminho_filtro(legendas)}'"
        if fontes.is_dir():
            filtro_ass += f":fontsdir='{_caminho_filtro(fontes)}'"
        filtros.append(f"[{corrente}]{filtro_ass}[vleg]")
        corrente = "vleg"

    # Branding no topo (sobre as legendas, sempre visível). O logo entra como
    # a última entrada do ffmpeg; seu índice vem depois do fundo, da narração
    # e de todas as imagens.
    usar_logo = logo is not None and Path(logo).is_file()
    if usar_logo:
        idx_logo = 2 + len(pares)
        log_l, log_a = _dimensoes(logo)
        largura_logo = round(largura * LOGO_LARGURA_FRAC)
        altura_logo = round(largura_logo * log_a / log_l)
        y_logo = round(altura * LOGO_Y_FRAC)
        filtros.append(
            f"[{idx_logo}:v]format=rgba,scale={largura_logo}:-1,"
            f"colorchannelmixer=aa={LOGO_OPACIDADE},"
            f"fade=t=in:st=0:d={FADE}:alpha=1[logo]"
        )
        filtros.append(
            f"[{corrente}][logo]overlay=(W-w)/2:{y_logo}:eof_action=pass[vlogo]"
        )
        corrente = "vlogo"

    if handle and FONTE_HANDLE.is_file():
        # Sem logo, ancora o @usuário no mesmo ponto onde o logo começaria.
        y_base = round(altura * LOGO_Y_FRAC)
        if usar_logo:
            y_handle = y_base + round(altura_logo * HANDLE_GAP_FRAC)
        else:
            y_handle = y_base
        filtros.append(
            f"[{corrente}]drawtext=fontfile='{_caminho_filtro(FONTE_HANDLE)}'"
            f":text='{_texto_drawtext(handle)}':fontcolor=black"
            f":fontsize={round(largura * HANDLE_FONTE_FRAC)}"
            f":x=(w-text_w)/2:y={y_handle}"
            f":alpha='if(lt(t,{FADE}),{HANDLE_OPACIDADE}*t/{FADE},{HANDLE_OPACIDADE})'"
            f"[vbrand]"
        )
        corrente = "vbrand"

    comando = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=white:s={largura}x{altura}:r={FPS}:d={duracao:.2f}",
        "-i", str(narracao),
    ]
    for s, _ in pares:
        comando += ["-i", str(s["caminho"])]
    if usar_logo:
        # -loop 1: o PNG é um único quadro; sem isso o logo apareceria só no
        # primeiro instante. O loop é limitado pela duração do vídeo (-t).
        comando += ["-loop", "1", "-i", str(logo)]
    comando += [
        "-filter_complex", ";".join(filtros),
        "-map", f"[{corrente}]",
        "-map", "1:a",
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
