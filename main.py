"""Automação de vídeos de notícias tech/AI a partir de posts do X.

Fluxo:
1. Coleta posts das últimas 24h no X (X Search da xAI).
2. GPT escolhe o tema do dia e gera título, descrição e texto do vídeo (~60s).
3. Web Search da xAI busca de 3 a 12 imagens-chave reais na web.
4. ElevenLabs narra o texto (TTS).
5. ffmpeg monta: fundo branco + narração + imagens centralizadas em largura
   total, com zoom-in lento + legendas sincronizadas (centralizadas quando não
   há imagem, na parte inferior quando há).
6. O resultado é salvo em output/ e registrado em videos.txt.
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime

from pipeline.audio import gerar_narracao
from pipeline.busca_imagens import buscar_imagens
from pipeline.config import carregar_config
from pipeline.edicao import duracao_audio, intervalos_imagens, montar_video
from pipeline.escritor import gerar_roteiro
from pipeline.legendas import gerar_legendas
from pipeline.registro import registrar
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
    parser = argparse.ArgumentParser(description="Gera o vídeo de notícias do dia.")
    parser.add_argument(
        "-usa",
        action="store_true",
        help="Conteúdo 100%% dedicado ao público americano (tudo em inglês)",
    )
    args = parser.parse_args()

    cfg = carregar_config()
    if args.usa:
        cfg.publico = "usa"
        print("[config] Modo USA: conteúdo em inglês para o público americano")

    tweets = coletar_tweets(cfg)
    roteiro = gerar_roteiro(cfg, tweets)

    pasta = cfg.output_dir / f"{datetime.now():%Y-%m-%d}_{_slug(roteiro['titulo'])}"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "roteiro.json").write_text(
        json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    imagens = buscar_imagens(cfg, roteiro["imagens"], pasta)
    narracao, alinhamento = gerar_narracao(
        cfg, roteiro["texto_video"], pasta / "narracao.mp3"
    )

    largura, altura = cfg.video_largura, cfg.video_altura
    sobreposicoes = _sobreposicoes(roteiro["texto_video"], imagens)
    duracao = duracao_audio(narracao) + 0.6

    legendas = gerar_legendas(
        roteiro["texto_video"],
        alinhamento,
        duracao,
        largura,
        altura,
        pasta / "legendas.ass",
        intervalos_imagens=intervalos_imagens(sobreposicoes, duracao),
    )

    video_final = montar_video(
        narracao,
        sobreposicoes,
        pasta / "video_final.mp4",
        largura,
        altura,
        legendas=legendas,
    )

    registrar(cfg, video_final, roteiro["titulo"], roteiro["descricao"])

    print("\nConcluído!")
    print(f"  Vídeo final: {video_final}")
    print(f"  Título: {roteiro['titulo']}")
    print(f"  Descrição: {roteiro['descricao']}")


if __name__ == "__main__":
    main()
