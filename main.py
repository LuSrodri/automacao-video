"""Automação de vídeos de notícias tech/AI a partir de posts do X.

Fluxo:
1. Coleta posts recentes das contas configuradas no X.
2. GPT escolhe o tema do dia e gera título, descrição e texto do vídeo.
3. OpenAI Images gera 1 a 3 imagens-chave com fundo transparente.
4. Grok Imagine anima o clipe.png usando o texto do vídeo como prompt.
5. ffmpeg sobrepõe as imagens-chave no vídeo.
6. O resultado é salvo em output/ e registrado em videos.txt.
"""

import json
import re
import unicodedata
from datetime import datetime

from pipeline.config import carregar_config
from pipeline.edicao import editar_video
from pipeline.escritor import gerar_roteiro
from pipeline.imagens import gerar_imagens
from pipeline.registro import registrar
from pipeline.video import gerar_video
from pipeline.x_client import coletar_tweets


def _slug(texto: str, limite: int = 40) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite].rstrip("-") or "video"


def _sobreposicoes(texto_video: str, imagens: list[dict]) -> list[dict]:
    """Posiciona cada imagem na fração da narração em que seu trecho ocorre."""
    resultado = []
    for img in imagens:
        trecho = img["trecho"].strip()
        pos = texto_video.lower().find(trecho.lower()) if trecho else -1
        if pos < 0:
            resultado.append(
                {"caminho": img["caminho"], "inicio_frac": None, "fim_frac": None}
            )
        else:
            resultado.append(
                {
                    "caminho": img["caminho"],
                    "inicio_frac": pos / len(texto_video),
                    "fim_frac": (pos + len(trecho)) / len(texto_video),
                }
            )
    return resultado


def main() -> None:
    cfg = carregar_config()

    tweets = coletar_tweets(cfg)
    roteiro = gerar_roteiro(cfg, tweets)

    pasta = cfg.output_dir / f"{datetime.now():%Y-%m-%d}_{_slug(roteiro['titulo'])}"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "roteiro.json").write_text(
        json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    imagens = gerar_imagens(cfg, roteiro["imagens"], pasta)
    video_bruto = gerar_video(cfg, roteiro["texto_video"], pasta / "video_bruto.mp4")
    video_final = editar_video(
        video_bruto,
        _sobreposicoes(roteiro["texto_video"], imagens),
        pasta / "video_final.mp4",
    )

    registrar(cfg, video_final, roteiro["titulo"], roteiro["descricao"])

    print("\nConcluído!")
    print(f"  Vídeo final: {video_final}")
    print(f"  Título: {roteiro['titulo']}")
    print(f"  Descrição: {roteiro['descricao']}")


if __name__ == "__main__":
    main()
