"""Busca das imagens-chave reais na web via Firecrawl Search API.

Cada assunto vira uma consulta à API do Firecrawl
(https://api.firecrawl.dev/v2/search) com `sources: ["images"]`. De cada
resultado pegamos a URL original da imagem (`imageUrl`) e, como reserva, a
página de origem (`url`), de onde tentamos a og:image. As buscas rodam em
sequência com um pequeno intervalo entre elas.
"""

import re
import time
from pathlib import Path

import requests

from .config import Config

FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v2/search"
INTERVALO_REQ = 0.5  # s entre chamadas (margem para o limite de taxa do Firecrawl)
RESULTADOS_POR_BUSCA = 15  # quantos resultados pedir por consulta (mais opções boas)
LADO_MINIMO = 600  # px; menor lado "bom" — imagens deste tamanho p/ cima vêm primeiro
LADO_RECUSA = 200  # px; piso duro: abaixo disto é ícone/sprite, sempre descartado

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


def _dimensoes_bytes(c: bytes) -> tuple[int, int]:
    """Lê (largura, altura) do cabeçalho sem dependência externa.

    Cobre JPEG/PNG/WebP (os formatos aceitos em MAGICAS). Devolve (0, 0)
    quando não consegue determinar — nesse caso o chamador não rejeita.
    """
    try:
        if c.startswith(b"\x89PNG") and len(c) >= 24:
            return (int.from_bytes(c[16:20], "big"), int.from_bytes(c[20:24], "big"))
        if c.startswith(b"\xff\xd8"):  # JPEG: varre os marcadores até o SOF
            i, sof = 2, {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB}
            while i + 9 < len(c):
                if c[i] != 0xFF:
                    i += 1
                    continue
                marcador = c[i + 1]
                if marcador in sof:
                    alt = int.from_bytes(c[i + 5 : i + 7], "big")
                    larg = int.from_bytes(c[i + 7 : i + 9], "big")
                    return (larg, alt)
                i += 2 + int.from_bytes(c[i + 2 : i + 4], "big")  # pula o segmento
        if c.startswith(b"RIFF") and c[8:12] == b"WEBP":
            chunk = c[12:16]
            if chunk == b"VP8X" and len(c) >= 30:
                larg = int.from_bytes(c[24:27], "little") + 1
                alt = int.from_bytes(c[27:30], "little") + 1
                return (larg, alt)
            if chunk == b"VP8 " and len(c) >= 30:
                larg = int.from_bytes(c[26:28], "little") & 0x3FFF
                alt = int.from_bytes(c[28:30], "little") & 0x3FFF
                return (larg, alt)
            if chunk == b"VP8L" and len(c) >= 25:
                b = int.from_bytes(c[21:25], "little")
                return ((b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1)
    except (ValueError, IndexError):
        pass
    return (0, 0)


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
        print(f"[aviso] Imagem de {url} é pequena demais (bytes), pulando")
        return None

    larg, alt = _dimensoes_bytes(conteudo)
    if larg and alt and min(larg, alt) < LADO_RECUSA:
        print(f"[aviso] Imagem de {url} é ícone/sprite ({larg}x{alt}), pulando")
        return None

    destino = destino_sem_ext.with_suffix(ext)
    destino.write_bytes(conteudo)
    return destino


def _lado_menor(bloco: dict) -> int:
    """Menor lado (px) informado pelo Firecrawl; 0 quando a dimensão não veio."""
    try:
        return min(int(bloco.get("imageWidth", 0)), int(bloco.get("imageHeight", 0)))
    except (TypeError, ValueError):
        return 0


def _candidatos(dados: dict) -> list[str]:
    """URLs candidatas em ordem de preferência (maior resolução primeiro).

    O Firecrawl devolve cada imagem com a URL original (`imageUrl`), as
    dimensões (`imageWidth`/`imageHeight`) e a página de origem (`url`). A
    qualidade vem da ordem, não do descarte: como o download para no primeiro
    candidato que funciona, basta pôr os maiores na frente para o vídeo 1080p
    sempre pegar a melhor imagem que baixar. Tiers: imagens grandes → imagens
    pequenas/sem dimensão → páginas de origem (último recurso, para a consulta
    nunca ficar sem imagem; daí tentamos a og:image).
    """
    imagens = (dados.get("data") or {}).get("images") or []

    grandes: list[tuple[int, str]] = []
    pequenas: list[tuple[int, str]] = []
    paginas: list[str] = []
    for img in imagens:
        url = img.get("imageUrl")
        if url:
            lado = _lado_menor(img)
            destino = pequenas if lado and lado < LADO_MINIMO else grandes
            destino.append((lado, url))
        pagina = img.get("url")
        if pagina:
            paginas.append(pagina)

    # maior primeiro; dimensão 0 (desconhecida) por último dentro do tier
    chave_ord = lambda x: (x[0] == 0, -x[0])  # noqa: E731
    grandes.sort(key=chave_ord)
    pequenas.sort(key=chave_ord)
    ordenadas = [u for _, u in grandes] + [u for _, u in pequenas] + paginas
    return list(dict.fromkeys(ordenadas))


def _detalhe_erro(erro: Exception) -> str:
    """Extrai o motivo real do corpo de erro do Firecrawl, quando houver."""
    resp = getattr(erro, "response", None)
    if resp is None:
        return ""
    try:
        corpo_json = resp.json() or {}
    except ValueError:
        corpo = (resp.text or "").strip()
        return f" | corpo: {corpo[:300]}" if corpo else ""
    detalhe = corpo_json.get("error") or corpo_json.get("details")
    return f" | Firecrawl: {detalhe}" if detalhe else ""


def _buscar_um(cfg: Config, consulta: str) -> list[str]:
    headers = {
        "Authorization": f"Bearer {cfg.firecrawl_api_key}",
        "Content-Type": "application/json",
    }
    corpo = {
        "query": consulta,
        "sources": ["images"],
        "limit": RESULTADOS_POR_BUSCA,
    }
    for tentativa in range(3):
        try:
            resp = requests.post(
                FIRECRAWL_ENDPOINT, headers=headers, json=corpo, timeout=60
            )
            if resp.status_code == 429:  # limite de taxa: espera e tenta de novo
                time.sleep(1.5 * (tentativa + 1))
                continue
            resp.raise_for_status()
            return _candidatos(resp.json())
        except (requests.RequestException, ValueError) as erro:
            print(
                f"[aviso] Busca de imagem (Firecrawl) falhou para '{consulta}': "
                f"{erro}{_detalhe_erro(erro)}"
            )
            return []
    print(f"[aviso] Firecrawl limitou as buscas (429) para: {consulta}")
    return []


def buscar_imagens(cfg: Config, itens: list[dict], pasta: Path) -> list[dict]:
    """Busca e baixa as imagens; devolve [{"caminho": Path, "trecho": str}, ...]."""
    itens = itens[:6]
    print(f"[imagens] Buscando {len(itens)} imagens via Firecrawl Search...")

    # Sequencial e com um pequeno intervalo entre as chamadas.
    baixadas: list[dict] = []
    for i, item in enumerate(itens, 1):
        if i > 1:
            time.sleep(INTERVALO_REQ)
        urls = _buscar_um(cfg, item["consulta"])
        if not urls:
            print(f"[aviso] Nenhuma imagem encontrada para: {item['consulta']}")
            continue
        for url in urls[:6]:
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
