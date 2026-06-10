"""Geração do vídeo com Grok Imagine (image-to-video) a partir do clipe.png.

Durações acima de 10s são divididas em segmentos de até 10s, gerados em
paralelo a partir do mesmo clipe.png — cada um narrando uma parte do texto —
e concatenados com ffmpeg na ordem da narração.
"""

import base64
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from .config import Config
from .edicao import concatenar

API_BASE = "https://api.x.ai/v1"
TIMEOUT_GERACAO = 15 * 60  # segundos
INTERVALO_POLL = 5  # segundos

SEGMENTO_MAX = 10  # segundos por segmento gerado

SEM_TEXTO = (
    " Important: do not render any on-screen text, captions, subtitles, "
    "lettering, words, or typography anywhere in the video."
)


class GeracaoFalhou(RuntimeError):
    def __init__(self, status: str, code: str, message: str):
        super().__init__(f"{status}: {code} {message}".strip())
        self.status = status
        self.code = code
        self.message = message


def _imagem_para_data_uri(caminho: Path) -> str:
    b64 = base64.b64encode(caminho.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _segmentar(total: int) -> list[int]:
    """Divide a duração total em segmentos de até SEGMENTO_MAX segundos."""
    segmentos = []
    restante = total
    while restante > 0:
        segmentos.append(min(SEGMENTO_MAX, restante))
        restante -= segmentos[-1]
    return segmentos


def _dividir_texto(texto: str, segmentos: list[int]) -> list[str]:
    """Reparte o texto entre os segmentos, proporcional à duração de cada um.

    Prefere quebrar em fim de frase, para cada segmento narrar frases
    completas; se não houver frases suficientes, quebra por palavras.
    """
    if len(segmentos) == 1:
        return [texto]

    frases = re.split(r"(?<=[.!?…])\s+", texto.strip())
    total = sum(segmentos)
    total_palavras = len(texto.split())

    if len(frases) >= len(segmentos):
        alvos = [
            total_palavras * sum(segmentos[: i + 1]) / total
            for i in range(len(segmentos) - 1)
        ]
        # Acumulado de palavras após cada frase
        acumulados, contagem = [], 0
        for frase in frases:
            contagem += len(frase.split())
            acumulados.append(contagem)

        # Para cada alvo, escolhe o fim de frase mais próximo, garantindo ao
        # menos uma frase para cada parte restante
        limites, anterior = [], 0
        for k, alvo in enumerate(alvos):
            maximo = len(frases) - (len(segmentos) - k - 1)
            candidatos = range(anterior + 1, maximo + 1)
            if not candidatos:
                break
            escolhido = min(candidatos, key=lambda i: abs(acumulados[i - 1] - alvo))
            limites.append(escolhido)
            anterior = escolhido

        if len(limites) == len(segmentos) - 1:
            limites = [0, *limites, len(frases)]
            partes = [
                " ".join(frases[limites[i]:limites[i + 1]])
                for i in range(len(segmentos))
            ]
            if all(p.strip() for p in partes):
                return partes

    # Reserva: divisão proporcional por palavras
    palavras = texto.split()
    partes, inicio, acumulado = [], 0, 0
    for dur in segmentos:
        acumulado += dur
        fim = round(len(palavras) * acumulado / total)
        partes.append(" ".join(palavras[inicio:fim]).strip())
        inicio = fim
    return [p if p else texto for p in partes]


def _iniciar(cfg: Config, payload: dict) -> str:
    resp = requests.post(
        f"{API_BASE}/videos/generations",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.xai_api_key}",
        },
        json={"model": cfg.video_model, **payload},
        timeout=60,
    )
    if resp.status_code == 401:
        raise SystemExit("XAI_API_KEY inválida (HTTP 401). Verifique o .env.")
    if 400 <= resp.status_code < 500:
        raise GeracaoFalhou("rejeitado", str(resp.status_code), resp.text[:300])
    resp.raise_for_status()
    return resp.json()["request_id"]


def _aguardar(cfg: Config, request_id: str) -> str:
    """Faz polling até o vídeo ficar pronto e devolve a URL."""
    limite = time.monotonic() + TIMEOUT_GERACAO
    while True:
        if time.monotonic() > limite:
            raise SystemExit(
                "Tempo limite excedido aguardando o Grok Imagine. "
                f"Consulte o request_id {request_id} mais tarde."
            )

        resultado = requests.get(
            f"{API_BASE}/videos/{request_id}",
            headers={"Authorization": f"Bearer {cfg.xai_api_key}"},
            timeout=30,
        )
        resultado.raise_for_status()
        dados = resultado.json()
        status = dados["status"]

        if status == "done":
            return dados["video"]["url"]
        if status in ("failed", "expired"):
            erro = dados.get("error", {})
            raise GeracaoFalhou(status, erro.get("code", ""), erro.get("message", ""))
        time.sleep(INTERVALO_POLL)


def _gerar_segmento(
    cfg: Config, imagem_uri: str, texto: str, duracao: int, destino: Path
) -> Path:
    request_id = _iniciar(
        cfg,
        {
            "prompt": texto + SEM_TEXTO,
            "image": {"url": imagem_uri},
            "duration": duracao,
            "aspect_ratio": cfg.video_aspect_ratio,
            "resolution": cfg.video_resolucao,
        },
    )
    url = _aguardar(cfg, request_id)
    download = requests.get(url, timeout=300)
    download.raise_for_status()
    destino.write_bytes(download.content)
    return destino


def gerar_video(cfg: Config, texto_video: str, destino: Path) -> Path:
    segmentos = _segmentar(cfg.video_duracao)
    partes_texto = _dividir_texto(texto_video, segmentos)
    imagem_uri = _imagem_para_data_uri(cfg.clipe_path)

    if len(segmentos) == 1:
        print(f"[video] Gerando vídeo de {segmentos[0]}s ({cfg.video_aspect_ratio})...")
        try:
            _gerar_segmento(cfg, imagem_uri, partes_texto[0], segmentos[0], destino)
        except GeracaoFalhou as erro:
            raise SystemExit(f"Geração do vídeo falhou ({erro}).")
        print(f"[video] Salvo em {destino}")
        return destino

    print(
        f"[video] Gerando {len(segmentos)} segmentos em paralelo "
        f"({'+'.join(str(s) for s in segmentos)}s, {cfg.video_aspect_ratio})..."
    )
    caminhos = [
        destino.parent / f"parte_{i + 1}.mp4" for i in range(len(segmentos))
    ]
    with ThreadPoolExecutor(max_workers=len(segmentos)) as executor:
        tarefas = [
            executor.submit(_gerar_segmento, cfg, imagem_uri, txt, dur, caminho)
            for txt, dur, caminho in zip(partes_texto, segmentos, caminhos)
        ]
        for i, tarefa in enumerate(tarefas, start=1):
            try:
                tarefa.result()
                print(f"[video] Segmento {i}/{len(segmentos)} pronto")
            except GeracaoFalhou as erro:
                raise SystemExit(f"Segmento {i} falhou ({erro}).")

    print("[video] Concatenando segmentos...")
    concatenar(caminhos, destino)
    print(f"[video] Salvo em {destino}")
    return destino
