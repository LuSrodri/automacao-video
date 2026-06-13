"""Busca das imagens-chave reais na web via Web Search (Image Search) da xAI.

Cada assunto vira uma chamada própria ao grok com `enable_image_search`
(rodam em paralelo): pedidos pequenos fazem o modelo realmente usar a
ferramenta. As URLs diretas dos arquivos vêm nas annotations (url_citation)
da resposta; os embeds markdown do texto entram como candidatos extras.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from openai import OpenAI

from .config import Config

INSTRUCAO_BUSCA = """\
Use image search to find real images of: {consulta}

High resolution, no watermarks, no collages. Embed the 3 best results in
your reply as markdown images, exactly as image search returned them
(direct image file URLs). Reply with the embeds only, no other text.\
"""

PADRAO_EMBED = re.compile(r"!\[[^\]]*\]\((https?://[^\s)]+)\)")

# Assinaturas de formatos aceitos (o ffmpeg lê todos)
MAGICAS = {
    b"\xff\xd8\xff": ".jpg",
    b"\x89PNG": ".png",
    b"RIFF": ".webp",
}

TAMANHO_MINIMO = 5_000  # bytes; descarta thumbnails/ícones minúsculos

PADRAO_OG_IMAGE = re.compile(
    r"<meta[^>]+(?:property|name)=[\"'](?:og:image|twitter:image)[\"'][^>]+"
    r"content=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
PADRAO_OG_IMAGE_INVERTIDO = re.compile(
    r"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+"
    r"(?:property|name)=[\"'](?:og:image|twitter:image)[\"']",
    re.IGNORECASE,
)


def _extensao(conteudo: bytes) -> str | None:
    for magia, ext in MAGICAS.items():
        if conteudo.startswith(magia):
            return ext
    return None


def _requisitar(url: str) -> bytes | None:
    try:
        resp = requests.get(
            url,
            timeout=60,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as erro:
        print(f"[aviso] Falha ao baixar {url}: {erro}")
        return None


def _baixar(url: str, destino_sem_ext: Path) -> Path | None:
    """Baixa a imagem; se a URL for uma página HTML, tenta a og:image dela."""
    conteudo = _requisitar(url)
    if conteudo is None:
        return None

    ext = _extensao(conteudo)
    if ext is None:
        # Provavelmente uma página: procura a imagem de destaque (og:image)
        html = conteudo[:200_000].decode("utf-8", errors="ignore")
        achado = PADRAO_OG_IMAGE.search(html) or PADRAO_OG_IMAGE_INVERTIDO.search(html)
        if not achado:
            return None
        url_og = achado.group(1)
        if url_og.startswith("//"):
            url_og = "https:" + url_og
        conteudo = _requisitar(url_og)
        if conteudo is None:
            return None
        ext = _extensao(conteudo)
        if ext is None:
            return None

    if len(conteudo) < TAMANHO_MINIMO:
        print(f"[aviso] Imagem de {url} é pequena demais, pulando")
        return None

    destino = destino_sem_ext.with_suffix(ext)
    destino.write_bytes(conteudo)
    return destino


def _candidatos(resposta) -> list[str]:
    """URLs candidatas: annotations url_citation primeiro, embeds depois."""
    urls: list[str] = []
    for item in getattr(resposta, "output", None) or []:
        if getattr(item, "type", "") != "message":
            continue
        for parte in getattr(item, "content", None) or []:
            for ann in getattr(parte, "annotations", None) or []:
                if getattr(ann, "type", "") == "url_citation" and getattr(ann, "url", None):
                    urls.append(ann.url)
    urls.extend(PADRAO_EMBED.findall(resposta.output_text))
    return list(dict.fromkeys(urls))


def _buscar_um(cliente: OpenAI, cfg: Config, consulta: str) -> list[str]:
    try:
        resposta = cliente.responses.create(
            model=cfg.search_model,
            input=[
                {
                    "role": "user",
                    "content": INSTRUCAO_BUSCA.format(consulta=consulta),
                }
            ],
            tools=[{"type": "web_search", "enable_image_search": True}],
        )
    except Exception as erro:
        print(f"[aviso] Busca de imagem falhou para '{consulta}': {erro}")
        return []
    return _candidatos(resposta)


def buscar_imagens(cfg: Config, itens: list[dict], pasta: Path) -> list[dict]:
    """Busca e baixa as imagens; devolve [{"caminho": Path, "trecho": str}, ...]."""
    cliente = OpenAI(api_key=cfg.xai_api_key, base_url="https://api.x.ai/v1")

    itens = itens[:12]
    print(f"[imagens] Buscando {len(itens)} imagens na web via xAI (em paralelo)...")
    with ThreadPoolExecutor(max_workers=len(itens)) as executor:
        listas_urls = list(
            executor.map(
                lambda item: _buscar_um(cliente, cfg, item["consulta"]), itens
            )
        )

    baixadas: list[dict] = []
    for i, (item, urls) in enumerate(zip(itens, listas_urls), 1):
        if not urls:
            print(f"[aviso] Nenhuma imagem encontrada para: {item['consulta']}")
            continue
        for url in urls[:5]:
            caminho = _baixar(url, pasta / f"imagem_{i}")
            if caminho:
                baixadas.append({"caminho": caminho, "trecho": item.get("trecho", "")})
                print(f"[imagens] {caminho.name} <- {url}")
                break
        else:
            print(f"[aviso] Todos os candidatos falharam para: {item['consulta']}")

    if not baixadas:
        print("[aviso] Nenhuma imagem-chave baixada; o vídeo sairá sem overlays.")
    return baixadas
