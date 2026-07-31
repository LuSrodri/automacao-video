"""Automação de vídeos de análise sobre tecnologia, inteligência artificial,
mercado de trabalho e mercado financeiro, a partir das trends do X.

Fluxo:
1. X API coleta os posts das últimas 24h da lista fixa de contas (CONTAS_PADRAO
   em config.py, ou X_ACCOUNTS no .env) por dois caminhos — busca por
   relevância e TIMELINE cronológica de um subconjunto rotativo das contas, que
   é o que enxerga o post fresco (vazamento, comunicado) ainda sem engajamento
   — e o GPT os sumariza nas 10 trends mais quentes, ordenadas pelo VALOR DA
   INFORMAÇÃO (vazamento, exclusivo, urgência, número inédito) antes do
   engajamento.
2. GPT classifica cada candidata (macrotema + imagem mental) — sem filtro
   nem score: todas as candidatas seguem vivas para a seleção.
3. GPT escolhe a trend: primeiro corte pelo VALOR DA INFORMAÇÃO (vazamento,
   exclusivo, urgência, número inédito), e entre as elegíveis decide pela
   audiência — recebe os últimos vídeos publicados do canal com as métricas
   reais (views/likes, YouTube Data API) e os campeões de retenção (YouTube
   Analytics). Regra dura: a escolhida passa por uma verificação
   anti-repetição (GPT confere se ela cobriria o mesmo fato de um vídeo
   publicado nas últimas 36h; se sim, sai da disputa e a seleção refaz).
   Define também uma consulta de notícias.
4. Firecrawl (sources=news) busca notícias recentes que complementam a trend.
5. GPT escreve o roteiro explicativo (análise/educacional) em tom adulto,
   citando as fontes (contas do X e veículos das notícias), na estrutura
   PERGUNTA ESQUISITA -> CONTEXTUALIZAÇÃO -> DESENVOLVIMENTO -> CONSEQUÊNCIA
   -> CONCLUSÃO, com a conclusão respondendo a pergunta de um jeito que emenda
   de volta nela quando o Short reinicia (loop).
6. X API baixa um POOL de clipes de vídeo dos posts originais da trend (mais
   do que os 3 que entram na montagem, como folga para a auditoria), junto das
   fotos dos posts, que alimentam as cartelas. Imagem estática nunca ocupa a
   tela; trend sem post com vídeo nem chega aqui — a seleção já a descarta.
7. AUDITORIA do material visual: o GPT (visão) descreve e CLASSIFICA cada
   clipe, o veto duro derruba material de telejornal e imagem com selo de
   emissora, e uma nota de pertinência (1-5) derruba o clipe que não mostra o
   que a narração diz. No formato longo o telejornal não é vetado: entra
   MARCADO como representação visual (dessaturado + etiqueta na tela). Zero
   clipe aprovado = SystemExit (o formato longo exige um piso maior). Roda
   antes do TTS para a reprovação não custar créditos.
8. ElevenLabs narra o texto (TTS), o pipeline acelera a narração conforme o
   formato (o Short é acelerado, o longo roda em velocidade normal) e corta os
   silêncios; os timestamps do alinhamento acompanham as duas coisas.
9. A IA planeja os cortes: um "editor de cortes" casa cada clipe aprovado com
   o momento exato da narração (citações do texto -> timestamps do
   alinhamento).
10. Infográficos animados: o GPT escolhe até 2 números reais da história e o
    pipeline renderiza contadores/barras minimalistas (Pillow) que sobem da
    base do vídeo para o terço superior.
11. Cartelas de imagem nos momentos-chave: foto do post da trend ou og:image
    da notícia, auditada igual aos clipes, emoldurada por cima do clipe quando
    a narração nomeia o que ela mostra (nunca em cima de um infográfico).
11b. Figuras geradas pelo gpt-image-2 (figuras.py): gráfico, tabela,
    infográfico, diagrama ou cartaz DESENHADO a partir dos números que a
    narração diz — ancorado na citação literal do trecho, e só com dado que a
    narração falou. Cartelas e figuras sobem de baixo do quadro e saem por
    cima.
12. ffmpeg monta: fundo = o próprio clipe borrado (cobertura total, sem
    instante vazio) + clipe nítido centrado + crossfade curto + legendas
    grandes (Archivo Black) + crédito de reprodução no canto superior direito
    ("Reprodução Imagem: X" + conta do post) + cartelas + figuras +
    infográficos. SEM música de fundo.
13. O resultado é salvo em output/ e registrado em videos.txt, e publicado no
    YouTube (o horário de publicação é o do cronjob que dispara a execução).

Formatos (o mesmo fluxo acima, com parâmetros diferentes):
- padrão: Short vertical 1080x1920 de ~60s, com legendas queimadas e narração
  ACELERADA (VIDEO_VELOCIDADE).
- `--long-take`: vídeo de ANÁLISE em 16:9 (1920x1080), de 90 a 120 segundos,
  SEM legendas e em velocidade NORMAL, para os dois canais (combina com
  `-usa`). O roteiro explica um acontecimento contemporâneo cruzando
  tecnologia/IA, negócios, mercado de trabalho e mercado financeiro, e o
  payload é o que aquilo muda para quem procura emprego ou está em transição de
  carreira. Usa até 8 clipes do X, até 4 infográficos, até 4 figuras geradas, e
  a descrição sai com a lista de fontes reais.
"""

import argparse
import json
import re
import unicodedata
from datetime import datetime

from pipeline.audio import gerar_narracao
from pipeline.auditoria import auditar_midias
from pipeline.cartelas import gerar_cartelas
from pipeline.classificacao import classificar_trends
from pipeline.config import (
    LONGO_MAX_S,
    LONGO_MIN_CLIPES_APROVADOS,
    LONGO_MIN_S,
    ativar_formato_longo,
    carregar_config,
)
from pipeline.cortes import planejar_cortes
from pipeline.edicao import (
    RESPIRO_FINAL,
    duracao_audio,
    intervalos_imagens,
    montar_video,
)
from pipeline.escritor import gerar_roteiro, selecionar_trend
from pipeline.figuras import gerar_figuras
from pipeline.grafico import gerar_graficos
from pipeline.legendas import gerar_legendas
from pipeline.midia_x import baixar_midias_posts, descrever_midias
from pipeline.noticias import buscar_noticias
from pipeline.registro import registrar
from pipeline.silencio import aparar_silencios
from pipeline.thumbnail import gerar_thumbnail
from pipeline.x_client import buscar_posts_com_video, coletar_trends
from pipeline.youtube import autenticar as autenticar_youtube
from pipeline.youtube import publicar as publicar_youtube
from pipeline.youtube import top_retencao, ultimos_publicados


def _slug(texto: str, limite: int = 40) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite].rstrip("-") or "video"


def _com_fontes(
    descricao: str, trend: dict, noticias: list[dict], publico: str
) -> str:
    """Anexa à descrição os links reais que embasaram a análise (formato longo).

    Só URLs que o pipeline realmente coletou (posts do X da trend escolhida e
    notícias do Firecrawl) — nada gerado pelo modelo.
    """
    urls = list(dict.fromkeys(
        [u for u in (trend.get("posts") or []) if u]
        + [n.get("url", "") for n in noticias if n.get("url")]
    ))[:10]
    if not urls:
        return descricao
    titulo = "Sources:" if publico == "usa" else "Fontes:"
    return descricao + "\n\n" + titulo + "\n" + "\n".join(f"- {u}" for u in urls)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gera o vídeo de notícias do dia.")
    parser.add_argument(
        "-usa",
        action="store_true",
        help="Conteúdo 100%% dedicado ao público americano (tudo em inglês)",
    )
    parser.add_argument(
        "--long-take",
        action="store_true",
        help=(
            "Vídeo LONGO de análise: 16:9, de 90 a 120 segundos, sem legendas "
            "(combina com -usa)"
        ),
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

    if args.long_take:
        ativar_formato_longo(cfg)
        print(
            f"[config] Formato LONGO: {cfg.video_largura}x{cfg.video_altura} "
            f"(16:9), alvo de {cfg.video_duracao}s (faixa {LONGO_MIN_S}-"
            f"{LONGO_MAX_S}s), até {cfg.max_clipes} clipes, sem legendas"
        )

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

    marca = "_longo" if cfg.formato == "longo" else ""
    pasta = (
        cfg.output_dir
        / f"{datetime.now():%Y-%m-%d}{marca}_{_slug(roteiro['titulo'])}"
    )
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "roteiro.json").write_text(
        json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # O OBJETO da trend vem da própria seleção (selecionar_trend) — é o mesmo
    # que o roteiro usou, então os clipes baixados são sempre da trend certa.
    trend_video = selecao["trend_obj"]

    # Busca ABERTA por clipes do assunto (só no formato longo): as 50 contas do
    # canal raramente têm vários clipes do MESMO fato, que é o que 90-120s de
    # tela pedem. Entra depois da seleção porque buscar para cada candidata
    # custaria uma consulta por candidata — em troca, a busca não socorre uma
    # candidata que já tenha sido barrada no portão da seleção.
    extras = buscar_posts_com_video(cfg, selecao.get("consulta_noticias", ""))
    if extras:
        urls = trend_video.get("posts") or []
        # `posts` vem com os posts de vídeo na frente (x_client), e o lookup de
        # mídias corta a lista no teto — então os achados entram logo depois
        # deles, antes dos posts só de texto, senão seriam cortados fora.
        n_video = trend_video.get("posts_com_video") or 0
        novos = [u for u in extras if u not in urls]
        trend_video["posts"] = urls[:n_video] + novos + urls[n_video:]
        trend_video["posts_com_video"] = n_video + len(novos)

    clipes, fotos = baixar_midias_posts(cfg, trend_video.get("posts") or [], pasta)
    if not clipes:
        raise SystemExit(
            "Nenhum clipe de vídeo baixado dos posts da trend — o formato é "
            "montado só com clipes do X (imagem estática é proibida); "
            "abortando."
        )

    # AUDITORIA do material visual, antes do ElevenLabs: o GPT com visão
    # descreve e classifica cada clipe do pool, o veto duro derruba material de
    # telejornal/emissora e a nota de pertinência derruba o clipe que não
    # mostra o que a narração diz. Rodar aqui (e não depois da narração, como
    # a descrição das mídias rodava) faz a reprovação custar zero crédito de
    # TTS.
    laudos = descrever_midias(cfg, clipes)
    clipes = auditar_midias(
        cfg, roteiro["texto_video"], clipes, laudos,
        limite=cfg.max_clipes, rotulo="clipe", pasta=pasta,
    )
    piso = LONGO_MIN_CLIPES_APROVADOS if cfg.formato == "longo" else 1
    if len(clipes) < piso:
        raise SystemExit(
            f"Auditoria aprovou {len(clipes)} clipe(s), abaixo do piso de "
            f"{piso} para o formato {cfg.formato} — o vídeo sairia mostrando "
            "material de telejornal ou cena que não condiz com a narração; "
            f"abortando. O detalhe está em {pasta / 'auditoria_clipe.json'}."
        )

    narracao, alinhamento = gerar_narracao(
        cfg, roteiro["texto_video"], pasta / "narracao.mp3"
    )
    narracao, alinhamento, _ = aparar_silencios(narracao, alinhamento)

    largura, altura = cfg.video_largura, cfg.video_altura
    duracao = duracao_audio(narracao) + RESPIRO_FINAL

    # A duração final é a da narração: no formato longo ela precisa cair na
    # faixa pedida (90-120s). A faixa de palavras do roteirista já mira nisso;
    # este aviso existe porque o ritmo do TTS varia de narração para narração.
    if cfg.formato == "longo" and not LONGO_MIN_S <= duracao <= LONGO_MAX_S:
        print(
            f"[aviso] Narração de {duracao:.1f}s fora da faixa do formato "
            f"longo ({LONGO_MIN_S}-{LONGO_MAX_S}s); o vídeo segue, mas vale "
            "ajustar LONG_DURACAO se isso virar rotina."
        )

    # Posicionamento automático (reserva): clipes espalhados uniformemente,
    # com o primeiro abrindo o gancho.
    sobreposicoes = [
        {
            "caminho": m["caminho"],
            "inicio_frac": k / max(len(clipes), 1),
            "fim_frac": None,
            "conta": m.get("conta", ""),
            "representacao": bool(m.get("representacao")),
        }
        for k, m in enumerate(clipes)
    ]

    # Planejador de cortes: a IA casa cada clipe com o momento da narração.
    # Os clipes já vêm auditados, com a descrição da visão dentro de cada um —
    # descrever o arquivo real evita casar a narração com a cena errada e
    # melhora a escolha do primeiro clipe, o que decide o swipe.
    midias_plano = [
        {
            "caminho": m["caminho"],
            "tipo": m.get("tipo", ""),
            "dur_s": m.get("dur_s"),
            "conta": m.get("conta", ""),
            "descricao": (
                m.get("descricao") or "clipe anexado a um post original da trend"
            ),
        }
        for m in clipes
    ]
    plano = planejar_cortes(
        cfg, roteiro["texto_video"], midias_plano, alinhamento, duracao
    )
    if plano:
        # O plano volta só com caminho/tempos; a conta de origem (crédito de
        # reprodução na tela) e a marcação de representação visual (material de
        # telejornal no formato longo) são reanexadas pelo caminho do arquivo.
        conta_por_caminho = {str(m["caminho"]): m.get("conta", "") for m in clipes}
        repr_por_caminho = {
            str(m["caminho"]): bool(m.get("representacao")) for m in clipes
        }
        for p in plano:
            p["conta"] = conta_por_caminho.get(str(p["caminho"]), "")
            p["representacao"] = repr_por_caminho.get(str(p["caminho"]), False)
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

    # Formato longo é SEM legendas queimadas (pedido do usuário): a narração
    # se sustenta sozinha e a tela fica limpa para o clipe.
    legendas = None
    if cfg.formato != "longo":
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
    # história, no terço superior, subindo da base.
    graficos = gerar_graficos(
        cfg, roteiro["texto_video"], noticias, alinhamento, duracao, pasta
    )

    # Cartelas: a imagem do momento-chave (foto do post da trend ou og:image da
    # notícia) entra emoldurada por cima do clipe. Recebe as janelas dos
    # infográficos para não haver duas sobreposições ao mesmo tempo.
    cartelas = gerar_cartelas(
        cfg,
        roteiro["texto_video"],
        fotos,
        noticias,
        alinhamento,
        duracao,
        pasta,
        ocupadas=[(g["inicio_s"], g["inicio_s"] + g["dur_s"]) for g in graficos],
    )

    # Figuras geradas (gpt-image-2): gráfico, tabela, infográfico, diagrama ou
    # cartaz DESENHADO a partir dos números que a narração diz. Entra por
    # último na fila de sobreposições porque é a camada mais cara — o que já
    # está marcado pelos infográficos e pelas cartelas é desviado aqui.
    ocupadas = [
        (c["inicio_s"], c["inicio_s"] + c["dur_s"]) for c in graficos + cartelas
    ]
    figuras = gerar_figuras(
        cfg,
        roteiro["texto_video"],
        trend_video,
        noticias,
        alinhamento,
        duracao,
        pasta,
        ocupadas=ocupadas,
    )

    video_final = montar_video(
        narracao,
        sobreposicoes,
        pasta / "video_final.mp4",
        largura,
        altura,
        legendas=legendas,
        graficos=graficos,
        cartelas=cartelas,
        figuras=figuras,
        publico=cfg.publico,
        formato=cfg.formato,
    )

    # No formato longo a descrição leva as fontes reais (posts do X e veículos
    # das notícias que embasaram a análise): o vídeo é educacional e cita as
    # fontes na narração — quem quiser conferir precisa dos links.
    descricao = roteiro["descricao"]
    if cfg.formato == "longo":
        descricao = _com_fontes(descricao, trend_video, noticias, cfg.publico)

    registrar(cfg, video_final, roteiro["titulo"], descricao)

    # Capa customizada (só no longo, onde a thumbnail decide o clique — no
    # Short o feed mostra o vídeo rodando). Falha aqui não aborta: o YouTube
    # cai na capa automática e o vídeo vai ao ar do mesmo jeito.
    capa = None
    if cfg.formato == "longo":
        capa = gerar_thumbnail(
            cfg, video_final, roteiro["titulo"], roteiro["texto_video"], pasta
        )

    url_youtube = publicar_youtube(
        cfg,
        video_final,
        roteiro["titulo"],
        descricao,
        tags=roteiro.get("tags"),
        thumbnail=capa,
        comentario=roteiro.get("comentario"),
    )

    print("\nConcluído!")
    print(f"  Vídeo final: {video_final}")
    print(f"  Título: {roteiro['titulo']}")
    print(f"  Descrição: {roteiro['descricao']}")
    print(f"  YouTube: {url_youtube}")


if __name__ == "__main__":
    main()
