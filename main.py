"""Automação de vídeos de análise sobre o que está acontecendo, a partir das
trends do X.

SEM RECORTE TEMÁTICO (2026-08-16, pedido do usuário): qualquer assunto pode
virar vídeo — tecnologia, IA, negócios, trabalho, mercado, ciência, saúde,
política, mundo, esporte, cultura, crime, clima, consumo. Não há tema vetado
nem tema obrigatório; o que decide a pauta é o valor da informação e, entre as
candidatas, o que a audiência do canal assiste até o fim.

Fluxo:
1. X API coleta os posts da janela DA LISTA DO X (X_LIST_ID) —
   `/2/lists/{id}/tweets`, paginado e em ordem cronológica — e o GPT os
   sumariza nas 10 trends mais quentes, ordenadas pelo VALOR DA INFORMAÇÃO
   (vazamento, exclusivo, urgência, número inédito) antes do engajamento.
   Pôr ou tirar alguém da lista muda a pauta da próxima execução, sem commit
   nem deploy. É o CAMINHO ÚNICO desde 2026-08-22: o fallback pelas contas
   seguidas (busca por relevância em lotes de `from:` mais as timelines) foi
   removido, e falha de leitura agora aborta a execução em vez de deixar o
   vídeo sair de uma pauta pior sem ninguém ver.
2. GPT classifica cada candidata (macrotema + imagem mental) — sem filtro
   nem score: todas as candidatas seguem vivas para a seleção.
3. GPT escolhe a trend: primeiro corte pelo VALOR DA INFORMAÇÃO (vazamento,
   exclusivo, urgência, número inédito), e entre as elegíveis decide pela
   audiência — recebe os últimos vídeos publicados do canal com as métricas
   reais (views/likes, YouTube Data API) e a RÉGUA DE RETENÇÃO (YouTube
   Analytics). No SHORT a régua é ESTRITA (2026-08-22, os dois canais): entram
   os vídeos que passam AO MESMO TEMPO em engajamento > ENGAJAMENTO_MINIMO% e
   views acima do piso, limitados aos LIMITE_REFERENCIA melhores — e o único
   afrouxamento possível é baixar o piso de views de PASSO_FALLBACK_VIEWS em
   PASSO_FALLBACK_VIEWS até a lista sair do vazio. A RETENÇÃO saiu da régua do
   Short em 2026-08-22 (irrelevante para este canal, conferido no Studio).
   Cada campeão do Short ainda recebe um DOSSIÊ (pipeline/referencia.py):
   descrição publicada, a legenda do próprio vídeo e a leitura da capa, tudo
   montado em memória e descartado no fim da execução. No formato LONGO vale a
   régua anterior — retenção, teto e piso de engajamento que cede quando
   esvazia a lista. Regra dura: a escolhida passa por uma verificação anti-repetição
   (GPT confere se ela cobriria o mesmo fato de um vídeo publicado nas últimas
   36h; se sim, sai da disputa e a seleção refaz). Define também uma consulta
   curta do assunto (busca de clipes) e uma consulta de busca do YouTube.
4. PANORAMA DO DIA (SEO/GEO, pipeline/seo.py): a YouTube Data API devolve os
   vídeos que OUTROS canais publicaram sobre o mesmo assunto nas últimas
   JANELA_HORAS, com views/hora e o vocabulário de tags deles. É a única
   leitura do pipeline sobre a disputa FORA do canal, e alimenta título,
   descrição, tags e capa. Falha aqui só avisa (SEO_PANORAMA=0 desliga).
   A busca de NOTÍCIAS no Firecrawl que existia aqui foi REMOVIDA em
   2026-08-16: os fatos vêm só dos posts do X, e o pipeline não tem mais
   dependência nenhuma do Firecrawl.
5. GPT escreve o roteiro explicativo (análise/educacional) em tom adulto,
   citando as fontes (as contas do X que trouxeram o fato, e o veículo que elas
   citam), na estrutura PERGUNTA ESQUISITA -> CONTEXTUALIZAÇÃO ->
   DESENVOLVIMENTO -> CONSEQUÊNCIA -> CONCLUSÃO, com a conclusão respondendo a
   pergunta de um jeito que emenda de volta nela quando o Short reinicia
   (loop).
6. X API baixa um POOL de clipes de vídeo dos posts originais da trend (mais
   do que os 3 que entram na montagem, como folga para a auditoria), junto das
   fotos dos posts, que alimentam as cartelas. Imagem estática nunca ocupa a
   tela; trend sem post com vídeo nem chega aqui — a seleção já a descarta.
7. AUDITORIA do material visual: o GPT (visão) descreve e CLASSIFICA cada
   clipe, o veto duro derruba material de telejornal e imagem com selo de
   emissora, e uma nota de pertinência (1-5) derruba o clipe que não mostra o
   que a narração diz. No formato longo o telejornal não é vetado: entra
   MARCADO como representação visual (dessaturado + etiqueta na tela). O veto
   por TEXTO NA TELA entra aqui também: clipe tomado por texto — e, mais
   ainda, por texto PARADO — sai, a não ser que aquele texto seja o assunto
   que a narração descreve (o post citado, a tela do produto, o número
   falado); o clipe fica embaixo das legendas queimadas, e texto sobre texto
   não é lido por ninguém (VETO_TEXTO_DENSO=0 desliga). Roda antes do TTS para
   a reprovação não custar créditos.
   FALLBACK DE TEMA: ficar abaixo do piso de clipes aprovados (1 no curto,
   LONGO_MIN_CLIPES_APROVADOS no longo) — ou não conseguir baixar clipe
   nenhum — não aborta mais a execução: a candidata sai da disputa e os passos
   4 a 7 refazem com a próxima trend, até TENTATIVAS_TREND candidatas.
8. ElevenLabs narra o texto (TTS), o pipeline acelera a narração conforme o
   formato (o Short é acelerado, o longo roda em velocidade normal) e corta os
   silêncios; os timestamps do alinhamento acompanham as duas coisas.
9. A IA planeja os cortes: um "editor de cortes" casa cada clipe aprovado com
   o momento exato da narração (citações do texto -> timestamps do
   alinhamento).
10. Cartelas de imagem nos momentos-chave: foto do post da trend, auditada
    igual aos clipes, tomando a TELA INTEIRA quando a narração nomeia o que ela
    mostra.
11. Figuras geradas pelo gpt-image-2 (figuras.py): gráfico, tabela,
    infográfico, diagrama ou cartaz DESENHADO a partir dos números que a
    narração diz — ancorado na citação literal do trecho, e só com dado que a
    narração falou. São a ÚNICA fonte de "big number" na tela: os infográficos
    que o ffmpeg montava a partir de PNGs do Pillow foram removidos em
    2026-08-04. Cartelas e figuras entram e saem pelo CARROSSEL (item 12).
11b. MANCHETES (manchetes.py, só no formato longo, 2026-08-23): o índice
    "Ainda neste episódio" logo depois da pergunta de abertura (no máximo 10
    segundos, um tópico de cada vez) e uma manchete no canto inferior a cada
    troca de pauta, ancorada na citação do tópico. É a camada que divide um
    bloco corrido de 135 segundos em capítulos que o espectador percebe.
    Planejada ANTES das cartelas e das figuras, que desviam das janelas dela.
12. ffmpeg monta o vídeo em TELA CHEIA (2026-08-16, pedido do usuário): o
    conteúdo ocupa o QUADRO INTEIRO, com o preenchimento de fundo em desfoque
    do próprio clipe. Saíram os cenários que embrulhavam o vídeo — a moldura de
    celular sobre uma cama e, antes dela, a sala com TV —, e com eles o módulo
    cenario.py e a foto fundo-cama.png. Fundo = o próprio clipe borrado
    (cobertura total, sem instante vazio) + clipe nítido centrado + crossfade
    curto + legendas grandes (Archivo Black, altura levemente reduzida) +
    crédito de reprodução no canto superior direito ("Reprodução Imagem: X" +
    conta do post). As cartelas e as figuras entram por um CARROSSEL de duas
    posições: o conteúdo desliza para a esquerda e a imagem ocupa a tela; no
    fim da janela ela desliza de volta e o vídeo retorna. SEM música de fundo.
13. O resultado é salvo em output/ e registrado em videos.txt, e publicado no
    YouTube (o horário de publicação é o do cronjob que dispara a execução)
    com TAGS de busca (que iam vazias até 2026-08-07) e com a descrição
    montada em pipeline/seo.py: parágrafo do payload, par P:/R: (a parte de
    GEO — a frase autossuficiente que um buscador com IA consegue citar),
    capítulos no formato longo, fontes reais e as hashtags por último. O
    YouTube é o ÚNICO destino: a publicação secundária no TikTok (via Zernio)
    foi removida em 2026-08-16 a pedido do usuário — não reintroduzir sem
    pedido explícito.

Formatos (o mesmo fluxo acima, com parâmetros diferentes):
- padrão: Short vertical 1080x1920 de ~25s (era 60 até 2026-08-09), com
  legendas queimadas e narração ACELERADA (VIDEO_VELOCIDADE). PISO DURO de 21
  segundos: Short mais curto que isso não é publicado, a execução aborta. Os Shorts INTERCALAM temas — o
  macrotema do Short anterior sai da disputa da seleção.
- `--long-take`: vídeo de ANÁLISE em 16:9 (1920x1080), de 120 a 150 segundos
  (o piso de 120s é duro: abaixo dele a execução aborta), SEM legendas e em
  velocidade NORMAL, para os dois canais (combina com `-usa`). O roteiro
  explica um acontecimento contemporâneo cobrindo de 3 a 5 TÓPICOS — recortes
  diferentes do mesmo fato, tirados do próprio acontecimento (quem fez, quem
  paga, quem ganha, quem perde, o que vem depois). Usa até 8 clipes do X, até
  4 cartelas, até 4 figuras geradas, e a descrição sai com a lista de fontes
  reais.

Idioma: o canal decide, nunca o modelo. Canal brasileiro publica TUDO em
português (título, descrição, narração, capa); canal americano (`-usa`), TUDO
em inglês.
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
    CURTO_MIN_S,
    LONGO_MAX_S,
    LONGO_MIN_CLIPES_APROVADOS,
    LONGO_MIN_S,
    TENTATIVAS_TREND,
    ativar_formato_longo,
    carregar_config,
)
from pipeline.cortes import planejar_cortes
from pipeline.edicao import (
    RESPIRO_FINAL,
    duracao_audio,
    intervalos_imagens,
    marcar_memoria,
    montar_video,
)
from pipeline.escritor import (
    gerar_roteiro,
    selecionar_trend,
    selecionar_trends_longo,
)
from pipeline.figuras import gerar_figuras
from pipeline.legendas import gerar_legendas
from pipeline.manchetes import (
    gerar_manchetes,
    instantes_das_viradas,
    janelas as janelas_manchetes,
)
from pipeline.midia_x import baixar_midias_posts, descrever_midias
from pipeline.registro import registrar
from pipeline.seo import (
    capitulos,
    montar_descricao,
    panorama_do_dia,
    titulos_do_dia,
)
from pipeline.silencio import aparar_silencios, inserir_pausas
from pipeline.thumbnail import gerar_thumbnail
from pipeline.triagem import triar_material
from pipeline.x_client import (
    buscar_posts_com_video,
    coletar_trends,
    renovar_token_do_x,
)
from pipeline.youtube import autenticar as autenticar_youtube
from pipeline.youtube import publicar as publicar_youtube
from pipeline.referencia import montar_dossies
from pipeline.youtube import top_retencao, ultimos_publicados


def _slug(texto: str, limite: int = 40) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return texto[:limite].rstrip("-") or "video"


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
    parser.add_argument(
        "--renovar-x-token",
        action="store_true",
        help=(
            "NÃO gera vídeo: só renova o token do X e o distribui para os crons "
            "(cron dedicado; ver renovar_token_do_x em x_client.py)"
        ),
    )
    args = parser.parse_args()

    # Os modos que NÃO coletam pauta (renovar o token do X, autorizar o
    # YouTube) não precisam de X_LIST_ID — e o serviço do cron renovador não
    # tem essa env var. Exigir a lista deles derrubaria o cron que mantém o
    # token vivo para os outros quatro.
    coleta = not (args.renovar_x_token or args.auth_youtube or args.auth_youtube_usa)
    cfg = carregar_config(exige_lista=coleta)
    if args.auth_youtube or args.auth_youtube_usa:
        autenticar_youtube(cfg, usa=args.auth_youtube_usa)
        return
    # Modo RENOVADOR (2026-08-18, ideia do usuário). Sai antes de qualquer
    # leitura paga: este cron existe só para ser o ÚNICO que renova o token do
    # X, acabando com a corrida entre os quatro crons de vídeo.
    if args.renovar_x_token:
        raise SystemExit(0 if renovar_token_do_x(cfg) else 1)
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
    # Sem número aqui: no Short a lista não tem teto e o n_fallback nem chega a
    # ser usado (régua estrita, 2026-08-22); no longo o default dele resolve o
    # caminho de exceção.
    campeoes = top_retencao(cfg)
    # DOSSIÊ DOS CAMPEÕES (2026-08-22, pedido do usuário), só no Short e nos
    # dois canais: lê a legenda publicada e a capa de cada campeão, anexando
    # tudo à mesma lista que já segue para a seleção da trend e para o roteiro. Falha aberta — a régua numérica
    # sozinha é o comportamento que existia antes do dossiê, e ele não vale
    # derrubar uma execução.
    if cfg.formato == "curto" and campeoes:
        try:
            montar_dossies(cfg, campeoes)
        except Exception as erro:  # noqa: BLE001 — enriquecimento, não requisito
            print(
                f"[aviso] Dossiê dos campeões falhou ({erro}); a seleção segue "
                "só com as métricas."
            )

    trends = classificar_trends(cfg, coletar_trends(cfg))

    # TRIAGEM DO MATERIAL (2026-08-18, pedido do usuário): conferir o clipe
    # ANTES de escolher a pauta. O sinal que a seleção tinha era indireto —
    # quantos posts da candidata têm clipe —, e ele não diz nada sobre o que o
    # clipe MOSTRA; o resultado eram execuções inteiras gastas para descobrir
    # na auditoria que o único clipe era busto falante. Falha aqui não impede
    # nada: candidata sem veredito disputa como antes.
    try:
        triar_material(cfg, trends, cfg.output_dir / "_triagem")
    except SystemExit:
        raise
    except Exception as erro:
        print(f"[aviso] Triagem do material falhou ({erro}); seguindo sem ela.")

    # FALLBACK DE TEMA (2026-08-05): a trend é escolhida por um sinal INDIRETO
    # de material — quantos posts dela têm clipe nativo —, e esse sinal erra:
    # o clipe pode não baixar e a auditoria pode reprovar tudo. Quando isso
    # acontecia a execução morria com exit 1, tendo pago a coleta e a
    # classificação e com outras candidatas vivas na lista. Agora a candidata
    # que não rende material sai da disputa e a próxima é tentada, até
    # TENTATIVAS_TREND.
    #
    # O laço fecha ANTES do TTS de propósito: as falhas cobertas aqui são as de
    # material, e refazê-las custa notícias + roteiro + visão, nunca narração.
    # O piso de duração continua abortando seco lá embaixo — narração curta é
    # defeito do roteiro, e trocar de tema não conserta isso, só paga o
    # ElevenLabs de novo.
    tentadas: list[dict] = []
    for tentativa in range(1, TENTATIVAS_TREND + 1):
        # O LONGO cobre TRÊS acontecimentos (2026-08-18, pedido do usuário),
        # um por tópico: exigir 4 posts com clipe de um mesmo fato nunca
        # passava, e com três assuntos cada um só precisa do próprio clipe.
        selecao = (
            selecionar_trends_longo(
                cfg, trends, videos_recentes=recentes, campeoes=campeoes,
                excluir=tentadas,
            )
            if cfg.formato == "longo"
            else selecionar_trend(
                cfg, trends, videos_recentes=recentes, campeoes=campeoes,
                excluir=tentadas,
            )
        )
        # SEO/GEO: quem MAIS publicou sobre este assunto hoje. É a única leitura
        # do pipeline sobre o lado de fora do canal — os últimos publicados e os
        # campeões de retenção calibram o tom com o próprio público, mas não
        # dizem nada sobre a disputa da busca. Fica DENTRO do laço porque cada
        # tentativa é outra pauta, e a concorrência de uma não serve para a
        # outra. Falha aberta: sem panorama o roteiro sai como saía antes.
        panorama = panorama_do_dia(
            cfg, selecao.get("consulta_youtube") or selecao["trend"]
        )

        roteiro = gerar_roteiro(
            cfg, selecao, trends,
            videos_recentes=recentes, campeoes=campeoes, panorama=panorama,
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

        # O OBJETO da trend vem da própria seleção (selecionar_trend) — é o
        # mesmo que o roteiro usou, então os clipes baixados são sempre da
        # trend certa.
        trend_video = selecao["trend_obj"]

        # Busca ABERTA por clipes do assunto (só no formato longo, por
        # X_MAX_POSTS_BUSCA=0 no curto): as contas seguidas raramente têm vários
        # clipes do MESMO fato — só 5,6% dos posts delas trazem vídeo —, e é
        # disso que 90-120s de tela precisam. Fica fora do Short porque as
        # fontes não são curadas e o crédito leva a @ delas para a tela, 12
        # vezes por dia. Entra depois da seleção porque buscar para cada
        # candidata custaria uma consulta por candidata — em troca, a busca não
        # socorre uma candidata que já tenha sido barrada no portão da seleção.
        extras = buscar_posts_com_video(cfg, selecao.get("consulta_clipes", ""))
        if extras:
            urls = trend_video.get("posts") or []
            # `posts` vem com os posts de vídeo na frente (x_client), e o
            # lookup de mídias corta a lista no teto — então os achados entram
            # logo depois deles, antes dos posts só de texto, senão seriam
            # cortados fora.
            n_video = trend_video.get("posts_com_video") or 0
            novos = [u for u in extras if u not in urls]
            trend_video["posts"] = urls[:n_video] + novos + urls[n_video:]
            trend_video["posts_com_video"] = n_video + len(novos)

        clipes, fotos = baixar_midias_posts(
            cfg, trend_video.get("posts") or [], pasta
        )
        piso = LONGO_MIN_CLIPES_APROVADOS if cfg.formato == "longo" else 1
        if not clipes:
            recusa = (
                "nenhum clipe de vídeo baixou dos posts da trend (o formato é "
                "montado só com clipes do X, imagem estática é proibida)"
            )
        else:
            # AUDITORIA do material visual, antes do ElevenLabs: o GPT com
            # visão descreve e classifica cada clipe do pool, o veto duro
            # derruba material de telejornal/emissora e a nota de pertinência
            # derruba o clipe que não mostra o que a narração diz. Rodar aqui
            # (e não depois da narração, como a descrição das mídias rodava)
            # faz a reprovação custar zero crédito de TTS.
            laudos = descrever_midias(cfg, clipes)
            clipes = auditar_midias(
                cfg, roteiro["texto_video"], clipes, laudos,
                limite=cfg.max_clipes, rotulo="clipe", pasta=pasta,
            )
            recusa = ""
            if len(clipes) < piso:
                recusa = (
                    f"a auditoria aprovou {len(clipes)} clipe(s), abaixo do "
                    f"piso de {piso} do formato {cfg.formato} — o vídeo sairia "
                    "mostrando material de telejornal ou cena que não condiz "
                    f"com a narração (detalhe em "
                    f"{pasta / 'auditoria_clipe.json'})"
                )
        if not recusa:
            break

        # Descarta TODAS as escolhidas da rodada: no longo são três, e repetir
        # uma delas na tentativa seguinte gastaria material já reprovado.
        if selecao.get("selecoes"):
            tentadas.extend(s["trend_obj"] for s in selecao["selecoes"])
        else:
            tentadas.append(trend_video)
        print(
            f"[fallback] Tentativa {tentativa}/{TENTATIVAS_TREND} descartada — "
            f"'{selecao['trend']}': {recusa}."
        )
        if tentativa < TENTATIVAS_TREND:
            print("[fallback] Escolhendo outra trend com o material restante.")
    else:
        raise SystemExit(
            f"As {TENTATIVAS_TREND} candidatas tentadas hoje não renderam "
            "material aproveitável — nenhuma passou do piso de clipes "
            "auditados; abortando sem publicar. Se isso virar rotina, as "
            "alavancas são alargar JANELA_HORAS, subir X_MAX_POSTS ou revisar "
            "as contas acompanhadas."
        )

    marcar_memoria("antes da narração")
    narracao, alinhamento = gerar_narracao(
        cfg, roteiro["texto_video"], pasta / "narracao.mp3"
    )
    narracao, alinhamento, _ = aparar_silencios(narracao, alinhamento)

    largura, altura = cfg.video_largura, cfg.video_altura
    duracao = duracao_audio(narracao) + RESPIRO_FINAL

    # PISO DURO DE DURAÇÃO (2026-08-04, pedido do usuário): Short abaixo de
    # CURTO_MIN_S e vídeo longo abaixo de LONGO_MIN_S estão PROIBIDOS — não
    # saem, em vez de sair curtos como vinha acontecendo (o canal americano
    # publicou Shorts de 17 a 35 segundos com duração-alvo de 60).
    #
    # A conferência é aqui, e não só na faixa de palavras do roteiro, porque
    # palavra não é segundo: o ritmo real do TTS varia ~25% de narração para
    # narração, e só depois de narrar e cortar os silêncios se sabe a duração
    # de verdade. Custa a narração já paga — e é o preço certo, porque o
    # roteirista já teve TENTATIVAS_FAIXA_PALAVRAS chances de acertar o
    # tamanho, e o que sobra aqui é um vídeo que não deveria ir ao ar.
    #
    # O teto NÃO aborta: vídeo comprido demais é um defeito de retenção, não de
    # formato, e jogar fora uma execução inteira por 3 segundos de fala a mais
    # seria caro sem ninguém ganhar nada.
    piso_duracao = LONGO_MIN_S if cfg.formato == "longo" else CURTO_MIN_S
    if duracao < piso_duracao:
        raise SystemExit(
            f"Narração de {duracao:.1f}s abaixo do piso de {piso_duracao}s do "
            f"formato {cfg.formato} — vídeo mais curto que isso está proibido; "
            "abortando sem publicar. O roteiro saiu curto demais mesmo depois "
            "das tentativas de ajuste: as alavancas são subir "
            + (
                "LONG_DURACAO (alvo dentro da faixa) "
                if cfg.formato == "longo"
                else "VIDEO_DURACAO "
            )
            + "ou usar um TEXT_MODEL que respeite melhor o piso de palavras."
        )
    if cfg.formato == "longo" and duracao > LONGO_MAX_S:
        print(
            f"[aviso] Narração de {duracao:.1f}s acima do teto do formato "
            f"longo ({LONGO_MIN_S}-{LONGO_MAX_S}s); o vídeo segue, mas vale "
            "ajustar LONG_DURACAO se isso virar rotina."
        )

    # PAUSA NAS TROCAS DE PAUTA (2026-08-24, só no longo): abre um silêncio
    # logo ANTES da frase de virada de cada pauta — a "separação temporal" que
    # acompanha a visual. Fica DEPOIS da conferência de piso de propósito: o
    # piso mede FALA, e somar silêncio à duração deixaria um roteiro curto
    # demais passar por causa do respiro. E fica antes de tudo que ancora em
    # citação (cortes, cartelas, figuras, manchetes, capítulos), que passam a
    # ler o alinhamento já deslocado.
    if cfg.formato == "longo" and cfg.pausa_pauta_s > 0:
        narracao, alinhamento, _ = inserir_pausas(
            narracao,
            alinhamento,
            instantes_das_viradas(
                roteiro, roteiro["texto_video"], alinhamento, duracao
            ),
            cfg.pausa_pauta_s,
        )
        duracao = duracao_audio(narracao) + RESPIRO_FINAL

    # Posicionamento automático (reserva): clipes espalhados uniformemente,
    # com o primeiro abrindo o gancho.
    sobreposicoes = [
        {
            "caminho": m["caminho"],
            "inicio_frac": k / max(len(clipes), 1),
            "fim_frac": None,
            "conta": m.get("conta", ""),
            "representacao": bool(m.get("representacao")),
            "inicio_util_s": m.get("inicio_util_s"),
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
        util_por_caminho = {
            str(m["caminho"]): m.get("inicio_util_s") for m in clipes
        }
        for p in plano:
            p["conta"] = conta_por_caminho.get(str(p["caminho"]), "")
            p["representacao"] = repr_por_caminho.get(str(p["caminho"]), False)
            p["inicio_util_s"] = util_por_caminho.get(str(p["caminho"]))
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

    # Manchetes (só no longo): o índice "Ainda neste episódio" na abertura e o
    # painel que nomeia cada pauta quando ela vira. Vêm PRIMEIRO na fila das
    # sobreposições porque saem da estrutura do roteiro — as camadas que tomam
    # o quadro inteiro (cartela, figura) é que desviam delas, e não o
    # contrário: uma imagem em cima do painel taparia justamente a marca de
    # troca de pauta.
    manchetes = gerar_manchetes(
        cfg,
        roteiro,
        roteiro["texto_video"],
        alinhamento,
        duracao,
        pasta,
        tela=(largura, altura),
    )

    # Cartelas: a foto do post da trend toma a tela inteira pelo deslize, no
    # lugar do clipe. Renderizada no tamanho do QUADRO desde a volta da tela
    # cheia (2026-08-16) — antes era o tamanho da tela do celular desenhado.
    cartelas = gerar_cartelas(
        cfg,
        roteiro["texto_video"],
        fotos,
        alinhamento,
        duracao,
        pasta,
        tela=(largura, altura),
        ocupadas=janelas_manchetes(manchetes),
    )

    # Figuras geradas (gpt-image-2): gráfico, tabela, infográfico, diagrama ou
    # cartaz DESENHADO a partir dos números que a narração diz. São a ÚNICA
    # fonte de "big number" na tela desde 2026-08-04 — os infográficos que o
    # ffmpeg montava a partir de PNGs do Pillow (grafico.py) foram removidos a
    # pedido do usuário. Entra por último na fila de sobreposições porque é a
    # camada mais cara: o que já está marcado pelas cartelas é desviado aqui.
    ocupadas = janelas_manchetes(manchetes) + [
        (c["inicio_s"], c["inicio_s"] + c["dur_s"]) for c in cartelas
    ]
    marcar_memoria("antes das figuras")
    figuras = gerar_figuras(
        cfg,
        roteiro["texto_video"],
        trend_video,
        alinhamento,
        duracao,
        pasta,
        tela=(largura, altura),
        ocupadas=ocupadas,
    )

    marcar_memoria("antes da montagem")
    video_final = montar_video(
        narracao,
        sobreposicoes,
        pasta / "video_final.mp4",
        largura,
        altura,
        legendas=legendas,
        cartelas=cartelas,
        figuras=figuras,
        manchetes=manchetes,
        publico=cfg.publico,
        formato=cfg.formato,
    )

    # CAPÍTULOS (só no formato longo): cada tópico do roteiro trouxe uma citação
    # literal do ponto da narração em que ele começa, e o alinhamento converte
    # isso em carimbo de tempo. Publicados na descrição, viram os "momentos
    # principais" do YouTube — que rendem posição na busca e deixam o
    # espectador pular direto para o trecho que ele veio ver. Bloco inválido
    # (poucos capítulos, trechos colados) volta vazio e simplesmente não sai.
    marcos = []
    if cfg.formato == "longo":
        marcos = capitulos(
            roteiro, roteiro["texto_video"], alinhamento, duracao, cfg.publico
        )

    # A descrição publicada é montada aqui: o parágrafo do payload, o par P:/R:
    # (a parte de GEO — a frase que um buscador com IA consegue citar sem ter
    # assistido), os capítulos, as fontes reais do formato longo e, sempre por
    # último, as hashtags.
    descricao = montar_descricao(
        roteiro,
        cfg.publico,
        formato=cfg.formato,
        trend=trend_video,
        marcos=marcos,
    )

    registrar(cfg, video_final, roteiro["titulo"], descricao)

    # Capa customizada (só no longo, onde a thumbnail decide o clique — no
    # Short o feed mostra o vídeo rodando). Falha aqui não aborta: o YouTube
    # cai na capa automática e o vídeo vai ao ar do mesmo jeito.
    capa = None
    if cfg.formato == "longo":
        capa = gerar_thumbnail(
            cfg,
            video_final,
            roteiro["titulo"],
            roteiro["texto_video"],
            pasta,
            titulos_do_dia=titulos_do_dia(panorama),
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
    print(f"  Descrição:\n{descricao}")
    print(f"  YouTube: {url_youtube}")


if __name__ == "__main__":
    main()
