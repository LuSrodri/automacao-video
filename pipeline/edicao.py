"""Edição final: sobrepõe as imagens-chave no vídeo usando ffmpeg.

Cada imagem aparece centralizada na tela, durante a janela de tempo
correspondente ao trecho da narração a que ela se refere.
"""

import shutil
import subprocess
from pathlib import Path

FRACAO_OVERLAY = 0.55  # fração da largura do vídeo ocupada pela imagem-chave
MIN_EXIBICAO = 1.5  # segundos mínimos de exibição de cada imagem
FOLGA = 0.15  # intervalo entre uma imagem e a seguinte


def _exigir_ffmpeg() -> None:
    for binario in ("ffmpeg", "ffprobe"):
        if shutil.which(binario) is None:
            raise SystemExit(
                f"{binario} não encontrado no PATH. "
                "Instale o ffmpeg (winget install Gyan.FFmpeg) e reabra o terminal."
            )


def _probe(video: Path, entrada: str) -> str:
    saida = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", entrada,
            "-of", "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return saida.stdout.strip().split(",")[0]


def _tem_audio(video: Path) -> bool:
    saida = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "csv=p=0",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return bool(saida.stdout.strip())


def concatenar(videos: list[Path], destino: Path) -> Path:
    """Concatena os segmentos na ordem recebida, reencodando para uniformizar."""
    _exigir_ffmpeg()

    com_audio = all(_tem_audio(v) for v in videos)
    n = len(videos)
    if com_audio:
        filtro = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        filtro += f"concat=n={n}:v=1:a=1[v][a]"
        mapeamento = ["-map", "[v]", "-map", "[a]", "-c:a", "aac"]
    else:
        filtro = "".join(f"[{i}:v]" for i in range(n))
        filtro += f"concat=n={n}:v=1:a=0[v]"
        mapeamento = ["-map", "[v]"]

    comando = ["ffmpeg", "-y"]
    for video in videos:
        comando += ["-i", str(video)]
    comando += [
        "-filter_complex", filtro,
        *mapeamento,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(destino),
    ]

    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise SystemExit(f"ffmpeg falhou na concatenação:\n{resultado.stderr[-2000:]}")
    return destino


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
        ini = max(0.2, ini, fim_anterior + FOLGA)
        fim = min(max(fim, ini + MIN_EXIBICAO), duracao - 0.1)
        if fim - ini < 0.8:
            # Sem espaço restante no vídeo para esta imagem
            ajustadas.append(None)
            continue
        ajustadas.append((ini, fim))
        fim_anterior = fim
    return ajustadas


def editar_video(video: Path, sobreposicoes: list[dict], destino: Path) -> Path:
    """Aplica as imagens-chave.

    `sobreposicoes`: [{"caminho": Path, "inicio_frac": float|None,
    "fim_frac": float|None}, ...] — frações (0 a 1) da narração em que a
    imagem entra e sai; None usa distribuição uniforme.
    """
    _exigir_ffmpeg()

    if not sobreposicoes:
        shutil.copyfile(video, destino)
        return destino

    # Mantém janela e imagem pareadas: ordena pelo ponto da narração em que
    # cada imagem entra (sem sincronização conhecida vai para o final)
    sobreposicoes = sorted(
        sobreposicoes,
        key=lambda s: (s.get("inicio_frac") is None, s.get("inicio_frac") or 0.0),
    )

    duracao = float(_probe(video, "format=duration") or _probe(video, "stream=duration"))
    largura_overlay = int(int(_probe(video, "stream=width")) * FRACAO_OVERLAY) // 2 * 2
    janelas = _calcular_janelas(sobreposicoes, duracao)

    pares = [
        (s, j) for s, j in zip(sobreposicoes, janelas) if j is not None
    ]
    descartadas = len(sobreposicoes) - len(pares)
    if descartadas:
        print(f"[edicao] {descartadas} imagem(ns) sem espaço no vídeo, descartada(s)")
    if not pares:
        shutil.copyfile(video, destino)
        return destino

    filtros = []
    corrente = "0:v"
    for i, (_, (ini, fim)) in enumerate(pares):
        filtros.append(f"[{i + 1}:v]scale={largura_overlay}:-1[img{i}]")
        filtros.append(
            f"[{corrente}][img{i}]overlay=(W-w)/2:(H-h)/2"
            f":enable='between(t,{ini:.2f},{fim:.2f})'[v{i}]"
        )
        corrente = f"v{i}"

    comando = ["ffmpeg", "-y", "-i", str(video)]
    for s, _ in pares:
        comando += ["-i", str(s["caminho"])]
    comando += [
        "-filter_complex", ";".join(filtros),
        "-map", f"[{corrente}]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(destino),
    ]

    print("[edicao] Sobrepondo imagens-chave com ffmpeg...")
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise SystemExit(f"ffmpeg falhou:\n{resultado.stderr[-2000:]}")

    print(f"[edicao] Vídeo final salvo em {destino}")
    return destino
