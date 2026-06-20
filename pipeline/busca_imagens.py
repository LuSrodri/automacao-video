"""Busca das imagens-chave reais na web via Brave Image Search API.

Cada assunto vira uma consulta à API do Brave
(https://api.search.brave.com/res/v1/images/search). De cada resultado
pegamos a URL original em alta resolução (`properties.url`) e, como reserva,
a miniatura proxied (`thumbnail.src`). As buscas rodam em sequência com um
intervalo entre elas para respeitar o limite de ~1 req/s do plano gratuito.
"""

import re
import time
from pathlib import Path

import requests

from .config import Config

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/images/search"
INTERVALO_REQ = 1.05  # s entre chamadas (plano free do Brave: ~1 req/s)
RESULTADOS_POR_BUSCA = 10  # quantos resultados pedir por consulta

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


def _parametros_regiao(cfg: Config) -> dict[str, str]:
    """País e idioma da busca conforme o público (melhora a coerência)."""
    if cfg.publico == "usa":
        return {"country": "US", "search_lang": "en"}
    # Brave aceita só 'pt-br'/'pt-pt' como search_lang; 'pt' puro retorna 422.
    return {"country": "BR", "search_lang": "pt-br"}


def _candidatos(dados: dict) -> list[str]:
    """URLs candidatas: imagens originais primeiro, miniaturas como reserva."""
    resultados = dados.get("results") or []
    originais = [
        (r.get("properties") or {}).get("url")
        for r in resultados
        if (r.get("properties") or {}).get("url")
    ]
    miniaturas = [
        (r.get("thumbnail") or {}).get("src")
        for r in resultados
        if (r.get("thumbnail") or {}).get("src")
    ]
    return list(dict.fromkeys([*originais, *miniaturas]))


def _detalhe_erro(erro: Exception) -> str:
    """Extrai o motivo real do corpo de erro do Brave (código + detalhe).

    O Brave responde a falhas com um JSON {"error": {"code", "detail", ...}}.
    Sem isso o aviso mostra só "422 Client Error", escondendo a causa real
    (ex.: SUBSCRIPTION_TOKEN_INVALID ou search_lang fora do enum aceito).
    """
    resp = getattr(erro, "response", None)
    if resp is None:
        return ""
    try:
        erro_api = (resp.json() or {}).get("error") or {}
    except ValueError:
        corpo = (resp.text or "").strip()
        return f" | corpo: {corpo[:300]}" if corpo else ""
    partes = [str(p) for p in (erro_api.get("code"), erro_api.get("detail")) if p]
    return f" | Brave: {' - '.join(partes)}" if partes else ""


def _buscar_um(cfg: Config, consulta: str, regiao: dict[str, str]) -> list[str]:
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": cfg.brave_api_key,
    }
    params = {
        "q": consulta,
        "count": RESULTADOS_POR_BUSCA,
        "safesearch": "off",
        **regiao,
    }
    for tentativa in range(3):
        try:
            resp = requests.get(
                BRAVE_ENDPOINT, headers=headers, params=params, timeout=30
            )
            if resp.status_code == 429:  # limite de taxa: espera e tenta de novo
                time.sleep(1.5 * (tentativa + 1))
                continue
            resp.raise_for_status()
            return _candidatos(resp.json())
        except (requests.RequestException, ValueError) as erro:
            print(
                f"[aviso] Busca de imagem (Brave) falhou para '{consulta}': "
                f"{erro}{_detalhe_erro(erro)}"
            )
            return []
    print(f"[aviso] Brave limitou as buscas (429) para: {consulta}")
    return []


def buscar_imagens(cfg: Config, itens: list[dict], pasta: Path) -> list[dict]:
    """Busca e baixa as imagens; devolve [{"caminho": Path, "trecho": str}, ...]."""
    itens = itens[:12]
    regiao = _parametros_regiao(cfg)
    print(f"[imagens] Buscando {len(itens)} imagens via Brave Image Search...")

    # Sequencial e com intervalo: o plano gratuito do Brave aceita ~1 req/s.
    baixadas: list[dict] = []
    for i, item in enumerate(itens, 1):
        if i > 1:
            time.sleep(INTERVALO_REQ)
        urls = _buscar_um(cfg, item["consulta"], regiao)
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
