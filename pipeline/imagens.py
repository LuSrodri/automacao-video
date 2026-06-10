"""Geração das imagens-chave (logos e figuras públicas em estilo caricato)."""

import base64
from pathlib import Path

from openai import BadRequestError, OpenAI

from .config import Config

SUFIXO_ESTILO = (
    " Fun caricature cartoon style, bold colors, expressive. Single isolated "
    "subject, centered, no background, no scenery, transparent background, "
    "PNG with alpha channel. No text or lettering beyond what belongs to the "
    "logo itself."
)


def gerar_imagens(cfg: Config, itens: list[dict], pasta: Path) -> list[dict]:
    """Gera as imagens e devolve [{"caminho": Path, "trecho": str}, ...]."""
    cliente = OpenAI(api_key=cfg.openai_api_key)
    geradas: list[dict] = []

    for i, item in enumerate(itens[:3], start=1):
        prompt_final = item["prompt"].rstrip(".") + "." + SUFIXO_ESTILO
        print(f"[imagem] Gerando imagem {i}/{min(len(itens), 3)}...")

        try:
            resultado = _gerar(cliente, cfg, prompt_final)
        except Exception as erro:
            # Figuras públicas podem ser recusadas pela moderação; segue o
            # fluxo com as imagens que deram certo em vez de abortar tudo.
            print(f"[aviso] Imagem {i} falhou e será pulada: {erro}")
            continue

        destino = pasta / f"imagem_{i}.png"
        destino.write_bytes(base64.b64decode(resultado.data[0].b64_json))
        geradas.append({"caminho": destino, "trecho": item.get("trecho", "")})
        print(f"[imagem] Salva em {destino}")

    return geradas


def _gerar(cliente: OpenAI, cfg: Config, prompt: str):
    try:
        return cliente.images.generate(
            model=cfg.image_model,
            prompt=prompt,
            size="1024x1024",
            quality=cfg.image_quality,
            background="transparent",
            output_format="png",
            moderation="low",
        )
    except BadRequestError as erro:
        # gpt-image-2 não aceita background="transparent"; nesse caso gera
        # sem o parâmetro e avisa que a transparência não é garantida.
        if "background" not in str(erro).lower():
            raise
        print(
            f"[aviso] O modelo {cfg.image_model} não suporta fundo "
            "transparente nativo. Gerando sem o parâmetro; use "
            "IMAGE_MODEL=gpt-image-1.5 para transparência garantida."
        )
        return cliente.images.generate(
            model=cfg.image_model,
            prompt=prompt,
            size="1024x1024",
            quality=cfg.image_quality,
            output_format="png",
            moderation="low",
        )
