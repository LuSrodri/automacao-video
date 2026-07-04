"""Automação de vídeos de notícias de tech/AI, dev e mercado de trabalho de TI
a partir das trends do X.

Fluxo:
1. Coleta as 10 trends mais faladas das últimas 24h no X (X Search da xAI).
2. GPT escolhe a trend de maior apelo visual e chance de viralizar (evitando
   repetir os últimos vídeos do canal) e define uma consulta de notícias.
3. Firecrawl (sources=news) busca notícias recentes que complementam a trend.
4. GPT escreve o roteiro com curva de retenção (gancho nos 3s, desenvolvimento
   que prende, recompensa no final) e define de 8 a 10 imagens-chave.
5. X API (opcional) baixa as fotos e vídeos dos posts originais da trend, e o
   Firecrawl Search busca as demais imagens reais na web.
6. ElevenLabs narra o texto (TTS) e o pipeline corta os silêncios da narração.
7. A IA planeja os cortes: o x_search descreve as mídias dos posts (análise de
   imagem/vídeo) e um "editor de cortes" casa cada mídia com o momento exato da
   narração (citações do texto -> timestamps do alinhamento).
8. ffmpeg monta: fundo = a própria imagem borrada (cobertura total, sem instante
   vazio) + imagem nítida com zoom suave + crossfade + legendas + branding com
   borda branca.
9. O resultado é salvo em output/ e registrado em videos.txt, e publicado no
   YouTube.
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime

from pipeline.audio import gerar_narracao
from pipeline.busca_imagens import buscar_imagens
from pipeline.config import carregar_config
from pipeline.cortes import planejar_cortes
from pipeline.edicao import duracao_audio, intervalos_imagens, montar_video
from pipeline.escritor import gerar_roteiro, selecionar_trend
from pipeline.legendas import gerar_legendas
from pipeline.midia_x import baixar_midias_posts
from pipeline.noticias import buscar_noticias
from pipeline.registro import registrar
from pipeline.silencio import aparar_silencios
from pipeline.x_client import coletar_trends, descrever_midias_posts
from pipeline.youtube import autenticar as autenticar_youtube
from pipeline.youtube import publicar as publicar_youtube
from pipeline.youtube import ultimos_publicados


def _slug(texto: str, limite: int = 40) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite].rstrip("-") or "video"


def _trend_escolhida(trends: list[dict], nome: str) -> dict:
    """Localiza a trend escolhida pela seleção (por nome, com folga p/ paráfrase)."""
    alvo = nome.strip().lower()
    for t in trends:
        if t["trend"].strip().lower() == alvo:
            return t
    for t in trends:
        candidato = t["trend"].strip().lower()
        if candidato and (candidato in alvo or alvo in candidato):
            return t
    return trends[0]


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
    parser.add_argument(
        "--auth-youtube",
        action="store_true",
        help="Autoriza o canal português e salva o refresh token no .env",
    )
    parser.add_argument(
        "--auth-youtube-usa",
        action="store_true",
        help="Autoriza o canal inglês e salva YOUTUBE_REFRESH_TOKEN_USA no .env",
    )
    args = parser.parse_args()

    cfg = carregar_config()
    if args.auth_youtube or args.auth_youtube_usa:
        autenticar_youtube(cfg, usa=args.auth_youtube_usa)
        return

    if args.usa:
        cfg.publico = "usa"
        print("[config] Modo USA: conteúdo em inglês para o público americano")

    trends = coletar_trends(cfg)
    recentes = ultimos_publicados(cfg, n=9)
    selecao = selecionar_trend(cfg, trends, videos_recentes=recentes)
    noticias = buscar_noticias(cfg, selecao["consulta_noticias"])
    roteiro = gerar_roteiro(cfg, selecao, trends, noticias)

    pasta = cfg.output_dir / f"{datetime.now():%Y-%m-%d}_{_slug(roteiro['titulo'])}"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "roteiro.json").write_text(
        json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    trend_video = _trend_escolhida(trends, selecao["trend"])
    midias_x = baixar_midias_posts(cfg, trend_video.get("posts") or [], pasta)
    imagens = buscar_imagens(cfg, roteiro["imagens"], pasta)
    narracao, alinhamento = gerar_narracao(
        cfg, roteiro["texto_video"], pasta / "narracao.mp3"
    )
    narracao, alinhamento, _ = aparar_silencios(narracao, alinhamento)

    largura, altura = cfg.video_largura, cfg.video_altura
    duracao = duracao_audio(narracao) + 0.6

    # Posicionamento automático (reserva): imagens perto dos seus trechos e
    # mídias do X espalhadas, com a primeira abrindo o gancho.
    sobreposicoes = _sobreposicoes(roteiro["texto_video"], imagens)
    sobreposicoes += [
        {
            "caminho": m["caminho"],
            "inicio_frac": k / max(len(midias_x), 1),
            "fim_frac": None,
        }
        for k, m in enumerate(midias_x)
    ]

    # Planejador de cortes: a IA casa cada mídia com o momento da narração.
    # As mídias do X são descritas pela análise de imagem/vídeo do x_search;
    # as da web, pela consulta/trecho do roteirista.
    descricoes = (
        descrever_midias_posts(cfg, trend_video.get("posts") or [])
        if midias_x
        else {}
    )
    midias_plano = [
        {
            "caminho": m["caminho"],
            "tipo": m.get("tipo", ""),
            "dur_s": m.get("dur_s"),
            "origem": "x",
            "descricao": descricoes.get(
                m.get("post_id", ""), "mídia anexada a um post original da trend"
            ),
        }
        for m in midias_x
    ] + [
        {
            "caminho": img["caminho"],
            "tipo": "photo",
            "dur_s": None,
            "origem": "web",
            "descricao": (
                f"imagem buscada por \"{img.get('consulta', '')}\"; ilustra o "
                f"trecho: \"{img.get('trecho', '')}\""
            ),
        }
        for img in imagens
    ]
    plano = planejar_cortes(
        cfg, roteiro["texto_video"], midias_plano, alinhamento, duracao
    )
    if plano:
        sobreposicoes = plano
        (pasta / "cortes.json").write_text(
            json.dumps(
                [
                    {"midia": str(p["caminho"].name), "inicio_s": p["inicio_s"]}
                    for p in plano
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

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
        handle=cfg.handle_do_publico,
    )

    registrar(cfg, video_final, roteiro["titulo"], roteiro["descricao"])

    url_youtube = publicar_youtube(
        cfg,
        video_final,
        roteiro["titulo"],
        roteiro["descricao"],
        tags=roteiro.get("tags"),
    )

    print("\nConcluído!")
    print(f"  Vídeo final: {video_final}")
    print(f"  Título: {roteiro['titulo']}")
    print(f"  Descrição: {roteiro['descricao']}")
    if url_youtube:
        print(f"  YouTube: {url_youtube}")


if __name__ == "__main__":
    main()
