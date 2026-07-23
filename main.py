"""Automação de vídeos de notícias de geopolítica, inteligência, IA e tech
a partir das trends do X.

Fluxo:
1. X API coleta os posts das últimas 24h da lista fixa de contas (CONTAS_PADRAO
   em config.py, ou X_ACCOUNTS no .env) e o GPT os sumariza nas 10 trends mais
   quentes (notícias, novidades, tretas).
2. GPT classifica cada candidata (macrotema + imagem mental) — sem filtro
   nem score: todas as candidatas seguem vivas para a seleção.
3. GPT escolhe a trend guiado SOMENTE pela audiência: recebe os últimos
   vídeos publicados do canal com as métricas reais (views/likes, YouTube
   Data API) e os campeões de retenção (YouTube Analytics) e escolhe a
   candidata com a maior chance de performar com esse público. Regras duras:
   o mesmo macrotema não emenda mais de 4 vídeos seguidos, e a escolhida
   passa por uma verificação anti-repetição (GPT confere se ela cobriria o
   mesmo fato de um vídeo publicado nas últimas 36h; se sim, sai da disputa
   e a seleção refaz). Define também uma consulta de notícias.
4. Firecrawl (sources=news) busca notícias recentes que complementam a trend.
5. GPT escreve o roteiro explicativo (análise/educacional) em tom adulto,
   citando as fontes (contas do X e veículos das notícias), com HOOK -> FATO
   -> IMPLICAÇÃO -> CORTE emendando no hook para rodar em loop, e define de
   8 a 10 imagens-chave.
6. X API baixa as fotos e vídeos dos posts originais da trend, e o Firecrawl
   Search busca as demais imagens reais na web.
7. ElevenLabs narra o texto (TTS) e o pipeline corta os silêncios da narração.
8. A IA planeja os cortes: o GPT (visão) descreve TODAS as mídias baixadas
   (dos posts do X e da web) e um "editor de cortes" casa cada mídia com o
   momento exato da narração (citações do texto -> timestamps do alinhamento).
9. Infográficos animados: o GPT escolhe até 2 números reais da história e o
   pipeline renderiza contadores/barras minimalistas (Pillow) que sobem da
   base do vídeo para o terço superior, no lugar do branding.
10. ffmpeg monta: fundo = a própria imagem borrada (cobertura total, sem
    instante vazio) + imagem nítida com zoom suave + crossfade + legendas +
    infográficos + branding com borda branca (+ trilha de fundo opcional).
11. O resultado é salvo em output/ e registrado em videos.txt, e publicado no
    YouTube (o horário de publicação é o do cronjob que dispara a execução).
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime

from pipeline.audio import gerar_narracao
from pipeline.busca_imagens import buscar_imagens
from pipeline.classificacao import classificar_trends
from pipeline.config import carregar_config
from pipeline.cortes import planejar_cortes
from pipeline.edicao import (
    RESPIRO_FINAL,
    duracao_audio,
    intervalos_imagens,
    montar_video,
)
from pipeline.escritor import gerar_roteiro, selecionar_trend
from pipeline.grafico import gerar_graficos
from pipeline.legendas import gerar_legendas
from pipeline.midia_x import baixar_midias_posts, descrever_midias
from pipeline.noticias import buscar_noticias
from pipeline.registro import registrar
from pipeline.silencio import aparar_silencios
from pipeline.x_client import coletar_trends
from pipeline.youtube import autenticar as autenticar_youtube
from pipeline.youtube import publicar as publicar_youtube
from pipeline.youtube import top_retencao, ultimos_publicados


def _slug(texto: str, limite: int = 40) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite].rstrip("-") or "video"


def _sobreposicoes(texto_video: str, imagens: list[dict]) -> list[dict]:
    """Posiciona cada imagem na fração da narração em que seu trecho ocorre.

    As imagens vêm em ordem de narração, então a busca avança um cursor: se o
    texto repete uma frase, cada trecho casa com a ocorrência a partir da
    imagem anterior — não sempre com a primeira do texto.
    """
    resultado = []
    texto_baixo = texto_video.lower()
    cursor = 0
    for img in imagens:
        trecho = img["trecho"].strip().lower()
        pos = texto_baixo.find(trecho, cursor) if trecho else -1
        if pos < 0 and trecho:
            pos = texto_baixo.find(trecho)
        if pos < 0:
            resultado.append(
                {"caminho": img["caminho"], "inicio_frac": None, "fim_frac": None}
            )
        else:
            cursor = pos + 1
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

    # Leituras do canal PRIMEIRO (fail-fast): se as credenciais do YouTube
    # estiverem quebradas, aborta antes de qualquer chamada paga (X, OpenAI) —
    # e sem os recentes (com as métricas) a seleção pela audiência é cega.
    recentes = ultimos_publicados(cfg, n=100)
    campeoes = top_retencao(cfg, n=6)

    trends = classificar_trends(cfg, coletar_trends(cfg))

    selecao = selecionar_trend(
        cfg, trends, videos_recentes=recentes, campeoes=campeoes
    )
    noticias = buscar_noticias(cfg, selecao["consulta_noticias"])
    roteiro = gerar_roteiro(
        cfg, selecao, trends, noticias,
        videos_recentes=recentes, campeoes=campeoes,
    )

    pasta = cfg.output_dir / f"{datetime.now():%Y-%m-%d}_{_slug(roteiro['titulo'])}"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "roteiro.json").write_text(
        json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # O OBJETO da trend vem da própria seleção (selecionar_trend) — é o mesmo
    # que o roteiro usou, então as mídias baixadas são sempre da trend certa.
    trend_video = selecao["trend_obj"]
    midias_x = baixar_midias_posts(cfg, trend_video.get("posts") or [], pasta)
    imagens = buscar_imagens(cfg, roteiro["imagens"], pasta)
    if not imagens and not midias_x:
        raise SystemExit(
            "Nenhum material visual disponível (zero imagens da web e zero "
            "mídias dos posts do X) — o vídeo sairia sem nenhuma imagem na "
            "tela; abortando."
        )
    narracao, alinhamento = gerar_narracao(
        cfg, roteiro["texto_video"], pasta / "narracao.mp3"
    )
    narracao, alinhamento, _ = aparar_silencios(narracao, alinhamento)

    largura, altura = cfg.video_largura, cfg.video_altura
    duracao = duracao_audio(narracao) + RESPIRO_FINAL

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
    # O GPT com visão descreve TODAS as mídias baixadas — as dos posts do X e
    # as da web (o que a busca devolve muitas vezes não é o que a consulta
    # pediu; descrever o arquivo real evita casar a narração com uma imagem
    # errada e melhora a escolha da primeira imagem, a que decide o swipe).
    para_visao = midias_x + [
        {"caminho": img["caminho"], "consulta": img.get("consulta", "")}
        for img in imagens
    ]
    descricoes = descrever_midias(cfg, para_visao) if para_visao else {}
    midias_plano = [
        {
            "caminho": m["caminho"],
            "tipo": m.get("tipo", ""),
            "dur_s": m.get("dur_s"),
            "origem": "x",
            "descricao": descricoes.get(
                str(m["caminho"]), "mídia anexada a um post original da trend"
            ),
        }
        for m in midias_x
    ] + [
        {
            "caminho": img["caminho"],
            "tipo": "photo",
            "dur_s": None,
            "origem": "web",
            "descricao": descricoes.get(
                str(img["caminho"]),
                f"imagem buscada por \"{img.get('consulta', '')}\"; ilustra o "
                f"trecho: \"{img.get('trecho', '')}\"",
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

    # Infográficos animados: contadores/barras com os números reais da
    # história, no terço superior (no lugar do branding), subindo da base.
    graficos = gerar_graficos(
        cfg, roteiro["texto_video"], noticias, alinhamento, duracao, pasta
    )

    video_final = montar_video(
        narracao,
        sobreposicoes,
        pasta / "video_final.mp4",
        largura,
        altura,
        legendas=legendas,
        handle=cfg.handle_do_publico,
        graficos=graficos,
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
    print(f"  YouTube: {url_youtube}")


if __name__ == "__main__":
    main()
