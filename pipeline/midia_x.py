"""Download das mídias (fotos e vídeos) dos posts originais da trend, via X API.

Usa a X API oficial v2 em modo pay-per-use (~US$ 0,005 por post/mídia lida):
um único GET /2/tweets com `expansions=attachments.media_keys` resolve todos os
posts da trend de uma vez. Fotos vêm por URL direta (pbs.twimg.com, pedida em
resolução original); vídeos vêm como variantes MP4, das quais baixamos a de
maior bitrate. A etapa é opcional: sem X_CONSUMER_KEY/SECRET no .env, ou em
qualquer falha da API, o pipeline segue só com as imagens da busca web.
"""

import re
import subprocess
from pathlib import Path

import requests

from .busca_imagens import _baixar as _baixar_imagem
from .config import Config
from .edicao import duracao_audio

TOKEN_ENDPOINT = "https://api.x.com/oauth2/token"
TWEETS_ENDPOINT = "https://api.x.com/2/tweets"

MAX_POSTS = 4  # posts consultados por vídeo (cada um custa ~US$ 0,005)
MAX_MIDIAS = 4  # mídias baixadas por vídeo (as primeiras encontradas)
MAX_VIDEO_BYTES = 60_000_000  # ~60 MB; vídeo maior que isso é descartado

PADRAO_ID_POST = re.compile(r"(?:x|twitter)\.com/[^/]+/status/(\d+)")


def _bearer(cfg: Config) -> str | None:
    """Token OAuth2 app-only a partir do consumer key/secret."""
    try:
        resp = requests.post(
            TOKEN_ENDPOINT,
            auth=(cfg.x_consumer_key, cfg.x_consumer_secret),
            data={"grant_type": "client_credentials"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]
    except (requests.RequestException, KeyError, ValueError) as erro:
        print(f"[aviso] X API: falha ao obter token ({erro}); etapa de mídias pulada")
        return None


def _ids_dos_posts(urls: list[str]) -> list[str]:
    ids = [m.group(1) for u in urls if (m := PADRAO_ID_POST.search(u))]
    return list(dict.fromkeys(ids))[:MAX_POSTS]


def _url_foto_original(url: str) -> str:
    """Pede a foto na resolução original (name=orig) mantendo a query existente."""
    return f"{url}{'&' if '?' in url else '?'}name=orig"


def _melhor_variante(variantes: list[dict]) -> str | None:
    """URL do MP4 de maior bitrate (as demais variantes são HLS/baixa qualidade)."""
    mp4s = [
        v for v in variantes
        if v.get("content_type") == "video/mp4" and v.get("url")
    ]
    if not mp4s:
        return None
    return max(mp4s, key=lambda v: v.get("bit_rate") or 0)["url"]


def _baixar_foto(url: str, destino_sem_ext: Path) -> Path | None:
    # Reaproveita o fluxo de fotos da busca web (verificação de formato, piso
    # de tamanho e teto de resolução).
    return _baixar_imagem(_url_foto_original(url), destino_sem_ext)


def _baixar_video(url: str, destino: Path) -> Path | None:
    try:
        with requests.get(url, timeout=120, stream=True) as resp:
            resp.raise_for_status()
            tamanho = int(resp.headers.get("Content-Length") or 0)
            if tamanho > MAX_VIDEO_BYTES:
                print(f"[aviso] Vídeo de {url} grande demais ({tamanho} bytes), pulando")
                return None
            baixado = 0
            with destino.open("wb") as arquivo:
                for pedaco in resp.iter_content(chunk_size=1 << 16):
                    baixado += len(pedaco)
                    if baixado > MAX_VIDEO_BYTES:
                        print(f"[aviso] Vídeo de {url} passou do teto durante o download")
                        arquivo.close()
                        destino.unlink(missing_ok=True)
                        return None
                    arquivo.write(pedaco)
        return destino
    except requests.RequestException as erro:
        print(f"[aviso] Falha ao baixar vídeo {url}: {erro}")
        destino.unlink(missing_ok=True)
        return None


def baixar_midias_posts(cfg: Config, urls_posts: list[str], pasta: Path) -> list[dict]:
    """Baixa as mídias dos posts; devolve [{"caminho": Path, "trecho": ""}, ...].

    Compatível com o formato de `buscar_imagens` — o `main.py` mescla as duas
    listas. Vídeos saem como .mp4 e a montagem (edicao.py) os detecta pela
    extensão.
    """
    if not (cfg.x_consumer_key and cfg.x_consumer_secret):
        return []
    ids = _ids_dos_posts(urls_posts)
    if not ids:
        return []

    token = _bearer(cfg)
    if token is None:
        return []

    print(f"[midia-x] Consultando {len(ids)} posts da trend na X API...")
    try:
        resp = requests.get(
            TWEETS_ENDPOINT,
            params={
                "ids": ",".join(ids),
                "expansions": "attachments.media_keys",
                "media.fields": (
                    "media_key,type,url,variants,preview_image_url,width,height"
                ),
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        dados = resp.json()
    except (requests.RequestException, ValueError) as erro:
        print(f"[aviso] X API: lookup dos posts falhou ({erro}); etapa pulada")
        return []

    midias = (dados.get("includes") or {}).get("media") or []
    if not midias:
        print("[midia-x] Nenhuma mídia anexada nos posts consultados")
        return []

    # De qual post veio cada mídia (para casar com as descrições do x_search)
    dono_da_midia: dict[str, str] = {}
    for post in dados.get("data") or []:
        for chave in (post.get("attachments") or {}).get("media_keys") or []:
            dono_da_midia.setdefault(chave, post.get("id", ""))

    baixadas: list[dict] = []
    for k, m in enumerate(midias[:MAX_MIDIAS], 1):
        tipo = m.get("type")
        caminho = None
        if tipo == "photo" and m.get("url"):
            caminho = _baixar_foto(m["url"], pasta / f"midia_x_{k}")
        elif tipo in ("video", "animated_gif"):
            url_mp4 = _melhor_variante(m.get("variants") or [])
            if url_mp4:
                caminho = _baixar_video(url_mp4, pasta / f"midia_x_{k}.mp4")
        if caminho:
            dur_s = None
            if caminho.suffix == ".mp4":
                try:
                    dur_s = duracao_audio(caminho)  # ffprobe format=duration
                except (subprocess.CalledProcessError, ValueError, OSError):
                    dur_s = None
            baixadas.append(
                {
                    "caminho": caminho,
                    "trecho": "",
                    "tipo": tipo,
                    "post_id": dono_da_midia.get(m.get("media_key", ""), ""),
                    "dur_s": dur_s,
                }
            )
            print(f"[midia-x] {caminho.name} ({tipo})")

    if not baixadas:
        print("[midia-x] Nenhuma mídia dos posts pôde ser baixada")
    return baixadas
