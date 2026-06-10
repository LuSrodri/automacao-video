"""Montagem final do vídeo com ffmpeg.

O vídeo de fundo (mudo, em loop) recebe a narração TTS como trilha. Cada
imagem-chave entra centralizada ocupando toda a largura, com zoom-in lento,
enquanto o fundo fica borrado.
"""

import random
import shutil
import subprocess
from pathlib import Path

from .config import RAIZ

FPS = 30
ZOOM_TOTAL = 0.16  # quanto a imagem cresce ao longo da exibição
BLUR_SIGMA = 18
MIN_EXIBICAO = 2.0  # segundos mínimos de exibição de cada imagem
FOLGA = 0.25  # intervalo entre uma imagem e a seguinte
FADE = 0.35  # duração do fade de entrada/saída (imagem e blur)


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


def dimensoes_video(video: Path) -> tuple[int, int]:
    """Largura e altura do primeiro stream de vídeo."""
    _exigir_ffmpeg()
    return _dimensoes(video)


def _duracao_video(video: Path) -> float:
    saida = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(saida.stdout.strip())


def _sequencia_fundos(fundos: list[Path], duracao_alvo: float) -> list[Path]:
    """Sorteia fundos até cobrir a duração, sem repetir o mesmo em sequência."""
    sequencia: list[Path] = []
    total = 0.0
    anterior: Path | None = None
    duracoes = {f: _duracao_video(f) for f in fundos}
    while total < duracao_alvo:
        opcoes = [f for f in fundos if f != anterior] or fundos
        escolha = random.choice(opcoes)
        sequencia.append(escolha)
        total += duracoes[escolha]
        anterior = escolha
    return sequencia


def _calcular_janelas(
    sobreposicoes: list[dict], duracao: float, inicio_minimo: float = 0.0
) -> list[tuple[float, float] | None]:
    """Converte frações da narração em janelas (início, fim) em segundos.

    `inicio_minimo`: nenhuma imagem aparece antes desse instante (período da
    legenda de abertura); a primeira imagem entra logo depois dele.
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
        if i == 0 and inicio_minimo > 0:
            # A primeira imagem entra logo após a legenda de abertura
            ini = inicio_minimo + 0.2
            fim = max(fim, ini + MIN_EXIBICAO)
        janelas.append((ini, fim))

    # Remove sobreposições entre janelas consecutivas (a lista já chega
    # ordenada pelo início da narração)
    ajustadas: list[tuple[float, float] | None] = []
    fim_anterior = 0.0
    piso = max(0.2, inicio_minimo + 0.2)
    for ini, fim in janelas:
        ini = max(piso, ini, fim_anterior + FOLGA)
        fim = min(max(fim, ini + MIN_EXIBICAO), duracao - 0.1)
        if fim - ini < 1.0:
            # Sem espaço restante no vídeo para esta imagem
            ajustadas.append(None)
            continue
        ajustadas.append((ini, fim))
        fim_anterior = fim
    return ajustadas


def _caminho_filtro(caminho: Path) -> str:
    """Escapa um caminho Windows para uso dentro de filter_complex."""
    return str(caminho).replace("\\", "/").replace(":", "\\:")


def montar_video(
    fundos: list[Path] | Path,
    narracao: Path,
    sobreposicoes: list[dict],
    destino: Path,
    legendas: Path | None = None,
    inicio_imagens: float = 0.0,
) -> Path:
    """Monta o vídeo final.

    `fundos`: vídeos de fundo disponíveis; são sorteados e intercalados
    aleatoriamente (sem repetição consecutiva) até cobrir a narração.
    `sobreposicoes`: [{"caminho": Path, "inicio_frac": float|None,
    "fim_frac": float|None}, ...] — frações (0 a 1) da narração em que a
    imagem entra e sai; None usa distribuição uniforme.
    """
    _exigir_ffmpeg()

    if isinstance(fundos, Path):
        fundos = [fundos]
    duracao = duracao_audio(narracao) + 0.6
    sequencia = _sequencia_fundos(fundos, duracao)
    print(
        "[edicao] Sequência de fundos: "
        + " -> ".join(f.stem for f in sequencia)
    )
    largura = int(_probe(sequencia[0], "stream=width"))
    altura = int(_probe(sequencia[0], "stream=height"))

    # Mantém janela e imagem pareadas: ordena pelo ponto da narração em que
    # cada imagem entra (sem sincronização conhecida vai para o final)
    sobreposicoes = sorted(
        sobreposicoes,
        key=lambda s: (s.get("inicio_frac") is None, s.get("inicio_frac") or 0.0),
    )
    janelas = _calcular_janelas(sobreposicoes, duracao, inicio_imagens)
    pares = [(s, j) for s, j in zip(sobreposicoes, janelas) if j is not None]
    descartadas = len(sobreposicoes) - len(pares)
    if descartadas:
        print(f"[edicao] {descartadas} imagem(ns) sem espaço no vídeo, descartada(s)")

    n_fundos = len(sequencia)
    filtros = [
        f"[{k}:v]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
        f"crop={largura}:{altura},fps={FPS}[f{k}]"
        for k in range(n_fundos)
    ]
    filtros.append(
        "".join(f"[f{k}]" for k in range(n_fundos))
        + f"concat=n={n_fundos}:v=1:a=0[base]"
    )

    if pares:
        # Fundo borrado entra e sai em fade junto com cada imagem
        filtros.append("[base]split=2[nitido][p_blur]")
        filtros.append(
            f"[p_blur]gblur=sigma={BLUR_SIGMA},split={len(pares)}"
            + "".join(f"[bw{i}]" for i in range(len(pares)))
        )
        corrente = "nitido"
        for i, (_, (ini, fim)) in enumerate(pares):
            ini_b = max(0.0, ini - FADE)
            fim_b = min(duracao, fim + FADE)
            dur_b = fim_b - ini_b
            filtros.append(
                f"[bw{i}]trim=start={ini_b:.2f}:end={fim_b:.2f},"
                f"setpts=PTS-STARTPTS,format=rgba,"
                f"fade=t=in:st=0:d={FADE}:alpha=1,"
                f"fade=t=out:st={dur_b - FADE:.2f}:d={FADE}:alpha=1,"
                f"setpts=PTS+{ini_b:.2f}/TB[blur{i}]"
            )
            filtros.append(
                f"[{corrente}][blur{i}]overlay=0:0:eof_action=pass"
                f":enable='between(t,{ini_b:.2f},{fim_b:.2f})'[cb{i}]"
            )
            corrente = f"cb{i}"
    else:
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
            f"[{i + n_fundos + 1}:v]format=rgba,scale={largura * 4}:-2,"
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

    comando = ["ffmpeg", "-y"]
    for video in sequencia:
        comando += ["-i", str(video)]
    comando += ["-i", str(narracao)]
    for s, _ in pares:
        comando += ["-i", str(s["caminho"])]
    comando += [
        "-filter_complex", ";".join(filtros),
        "-map", f"[{corrente}]",
        "-map", f"{n_fundos}:a",
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
