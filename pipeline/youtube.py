"""Publicação automática no YouTube via YouTube Data API v3.

Usa apenas ``requests`` (sem o SDK do Google), no mesmo estilo dos demais
módulos do pipeline. O fluxo é:

1. Uma única vez, ``autenticar()`` roda o consentimento OAuth no navegador e
   guarda um *refresh token* de longa duração no ``.env`` (rode
   ``python main.py --auth-youtube``).
2. A cada execução, ``publicar()`` troca esse refresh token por um access
   token de curta duração e envia o vídeo num upload resumível.

A publicação roda sempre, independente da flag ``-usa``.
"""

import http.server
import json
import os
import re
import secrets
import threading
import urllib.parse
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .config import (
    CURVAS_PARALELAS,
    ENGAJAMENTO_MINIMO,
    DIAS_REFERENCIA,
    LIMITE_REFERENCIA,
    PASSO_FALLBACK_VIEWS,
    RETENCAO_MINIMA,
    VIEWS_MINIMO_ABSOLUTO,
    VIEWS_MINIMO_REFERENCIA,
    Config,
    atualizar_env,
)

# Todos os escopos da YouTube Data API v3, conforme a lista oficial da Google
# (https://developers.google.com/identity/protocols/oauth2/scopes#youtube).
# Assim o mesmo refresh token serve para publicar, ler e gerenciar o canal,
# sem reautenticar a cada feature nova.
#
# NÃO incluímos "youtubepartner-channel-audit": a Google exige que o token com
# esse escopo seja revogado logo após a auditoria com o parceiro, o que é
# incompatível com um refresh token de longa duração. Adicione manualmente só
# se for fazer uma auditoria pontual.
ESCOPO = " ".join(
    [
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/youtube.force-ssl",
        "https://www.googleapis.com/auth/youtube.channel-memberships.creator",
        "https://www.googleapis.com/auth/youtubepartner",
        # Analytics (métricas de retenção). Tokens antigos não têm este escopo:
        # reautorize com --auth-youtube / --auth-youtube-usa para ativar.
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
# Busca pública (seo.py): o que MAIS GENTE publicou sobre o assunto hoje. Não
# gasta da cota de 10.000 unidades/dia — cai no balde separado de "Search
# Queries", de 100 buscas/dia.
SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
# Legendas dos vídeos do PRÓPRIO canal (referencia.py): `captions.download` é
# liberado para o dono do vídeo, inclusive na faixa gerada pelo ASR. É o
# caminho reserva da transcrição quando o download do vídeo é barrado.
CAPTIONS_URL = "https://www.googleapis.com/youtube/v3/captions"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"

# Piso de views para o ranking de retenção: vídeo com pouquíssimas views tem
# retenção estatisticamente sem valor (3 amigos assistindo até o fim = 100%).
# Vale só para o formato LONGO desde 2026-08-22: no Short quem faz esse papel é
# VIEWS_MINIMO_ABSOLUTO, o ponto onde o afrouxamento gradual de views para.
VIEWS_MINIMO_RETENCAO = 50



# Segundo em que o "continuou vs deslizou fora" é medido na curva de retenção.
#
# CALIBRADO, não chutado (2026-08-17): com 6 vídeos cujo "Continuaram
# assistindo" real foi lido no Studio, o ponto de leitura foi varrido de 1s a 8s
# procurando o que melhor reproduz aquele número. Erro médio absoluto:
#
#     1s: 23,7 pts    4s:  6,6 pts    6,0s: 3,32 pts  (viés -0,4)
#     2s: 13,8 pts    5s:  3,3 pts    6,5s: 3,31 pts  (viés -1,6)
#     3s:  9,0 pts                    8,0s: 4,7 pts
#
# 6s ganha por causa do VIÉS: 6,5s empata no erro absoluto mas puxa a leitura
# 1,6 ponto para baixo sistematicamente, enquanto 6s fica praticamente centrado.
# Com 3s (a primeira tentativa) a medida lia ~8 pontos ALTO, o que tornava o
# piso de 70% bem mais permissivo que os 70% do Studio; aos 6s o número é
# comparável de verdade.
#
# Os 3,3 pontos que sobram são irredutíveis por este caminho: por vídeo o desvio
# vai de -5 a +3, então a fórmula exata do Studio difere da nossa em algo que a
# curva não revela. A janela (vida toda vs 28 dias) NÃO importa — testada, muda
# o erro na terceira casa.
SEGUNDO_DO_GANCHO = 6


def _gancho_pela_curva(
    vid: str, duracao_s: int, headers: dict, fim: str
) -> tuple[str, float | None]:
    """Fração da audiência inicial que ainda está lá aos SEGUNDO_DO_GANCHO.

    Esta é a única forma de chegar ao "continuaram assistindo": a Analytics API
    não expõe esse número como métrica (ver ENGAJAMENTO_MINIMO em config.py),
    mas expõe a CURVA, e a queda dela nos primeiros segundos é a mesma coisa.

    Custa uma chamada por vídeo, então o chamador roda isto por ÚLTIMO, sobre
    quem já passou pelos filtros baratos. Devolve None quando a curva não vem —
    vídeo novo demais, sem dados, ou erro de rede. No formato LONGO o None não
    reprova (medir errado é pior do que não medir); na régua estrita do Short
    reprova, porque lá o critério é "engajamento acima de X" e quem não foi
    medido não o satisfaz. Ver ``_lista_estrita``.
    """
    try:
        resp = requests.get(
            ANALYTICS_URL,
            params={
                "ids": "channel==MINE",
                "startDate": "2005-01-01",
                "endDate": fim,
                "dimensions": "elapsedVideoTimeRatio",
                "metrics": "audienceWatchRatio",
                "filters": f"video=={vid}",
            },
            headers=headers,
            timeout=45,
        )
        if resp.status_code != 200:
            return vid, None
        linhas = resp.json().get("rows") or []
        if not linhas:
            return vid, None
        curva = {float(x[0]): float(x[1]) for x in linhas}
        ts = sorted(curva)
        inicio = curva[ts[0]]
        if not inicio:
            return vid, None
        # A curva é indexada por FRAÇÃO do vídeo, então o segundo alvo depende
        # da duração. Sem duração conhecida, 20s é a mediana dos Shorts daqui.
        alvo = SEGUNDO_DO_GANCHO / (duracao_s or 20)
        return vid, curva[min(ts, key=lambda t: abs(t - alvo))] / inicio * 100
    except Exception:  # noqa: BLE001 — sem a curva o vídeo segue sem nota
        return vid, None


def _refresh_token_do_publico(cfg: Config) -> str:
    """Refresh token do canal certo: inglês quando publico == 'usa'."""
    if cfg.publico == "usa":
        return cfg.youtube_refresh_token_usa
    return cfg.youtube_refresh_token


def _renovar_access_token(cfg: Config, refresh_token: str | None = None) -> str:
    """Troca o refresh token por um access token de curta duração."""
    refresh_token = refresh_token or _refresh_token_do_publico(cfg)
    resp = requests.post(
        TOKEN_URL,
        data={
            "client_id": cfg.youtube_client_id,
            "client_secret": cfg.youtube_client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Falha ao renovar o token do YouTube ({resp.status_code}): "
            f"{resp.text[:300]}"
        )
    return resp.json()["access_token"]


def _duracao_iso(texto: str) -> int:
    """Segundos de uma duração ISO 8601 da Data API ('PT1M42S'); 0 se ilegível."""
    m = re.fullmatch(
        r"P(?:(\d+)D)?T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", (texto or "").strip()
    )
    if not m:
        return 0
    dias, horas, minutos, segundos = (int(g or 0) for g in m.groups())
    return ((dias * 24 + horas) * 60 + minutos) * 60 + segundos


def _data_de_corte() -> str:
    """Data ISO a partir da qual um vídeo entra na régua (hoje - DIAS_REFERENCIA).

    Uma função só, usada pelos DOIS caminhos que leem o catálogo — os últimos
    publicados e os campeões de retenção —, para as duas réguas nunca olharem
    janelas diferentes.
    """
    return (
        datetime.now(timezone.utc) - timedelta(days=DIAS_REFERENCIA)
    ).strftime("%Y-%m-%d")


def ultimos_publicados(cfg: Config, n: int = 100) -> list[dict]:
    """Últimos `n` vídeos publicados no canal selecionado (BR ou USA).

    Lê direto da YouTube Data API o canal correspondente ao refresh token de
    ``cfg.publico``, devolvendo os vídeos do mais recente para o mais antigo
    (a playlist e a busca de estatísticas são paginadas em blocos de 50, o
    teto por chamada da API). Cada item traz ``titulo``, ``descricao``,
    ``data`` (YYYY-MM-DDTHH:MM, UTC — a hora alimenta a verificação de vídeo
    repetido: com 3-4 execuções/dia, saber que o último vídeo saiu há poucas
    horas é o que importa), ``views``, ``likes`` e ``duracao_s`` (segundos —
    separa os Shorts dos vídeos do formato longo) — as contagens vêm da Data
    API (tempo real) e não da Analytics (que atrasa 2-3 dias e zeraria os
    vídeos mais novos, justamente os mais informativos). A lista é a régua da
    seleção guiada pela audiência — e a data de cada vídeo é o que permite
    normalizar as views pela idade (views/h) no prompt de seleção, o sinal que
    mostra um ciclo de notícia esfriando. Então
    qualquer falha (credenciais ausentes, API indisponível) ABORTA a
    execução: melhor falhar cedo e alto do que escolher pauta às cegas.
    Canal novo sem uploads devolve lista vazia (não é erro).
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        canal = "inglês (-usa)" if cfg.publico == "usa" else "português"
        flag = "--auth-youtube-usa" if cfg.publico == "usa" else "--auth-youtube"
        raise SystemExit(
            f"Credenciais do YouTube do canal {canal} ausentes — sem elas não "
            "dá para ler os últimos publicados, e a seleção guiada pela "
            f"audiência depende disso. Configure o .env e rode 'python main.py {flag}'."
        )

    try:
        token = _renovar_access_token(cfg, refresh)
        headers = {"Authorization": f"Bearer {token}"}

        canal = requests.get(
            CHANNELS_URL,
            params={"part": "contentDetails", "mine": "true"},
            headers=headers,
            timeout=60,
        )
        if canal.status_code != 200:
            raise RuntimeError(f"{canal.status_code}: {canal.text[:300]}")
        itens = canal.json().get("items", [])
        if not itens:
            return []
        uploads = itens[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # A playlist de uploads vem do mais novo para o mais antigo, então
        # sair da janela é sinal de PARAR: tudo daqui para trás é mais velho
        # ainda. Isso corta páginas de playlistItems e lotes de videos.list que
        # antes eram lidos só para serem descartados adiante.
        corte = _data_de_corte()
        itens_lista: list[dict] = []
        pagina = None
        fora_da_janela = False
        while len(itens_lista) < n and not fora_da_janela:
            params = {
                "part": "snippet,contentDetails",
                "playlistId": uploads,
                "maxResults": min(n - len(itens_lista), 50),
            }
            if pagina:
                params["pageToken"] = pagina
            lista = requests.get(
                PLAYLIST_ITEMS_URL, params=params, headers=headers, timeout=60
            )
            if lista.status_code != 200:
                raise RuntimeError(f"{lista.status_code}: {lista.text[:300]}")
            corpo = lista.json()
            for item in corpo.get("items", []):
                if (item.get("snippet", {}).get("publishedAt", "") or "")[:10] < corte:
                    fora_da_janela = True
                    break
                itens_lista.append(item)
            pagina = corpo.get("nextPageToken")
            if not pagina:
                break

        todos_ids = [
            i.get("contentDetails", {}).get("videoId", "") for i in itens_lista
        ]
        estatisticas: dict[str, dict] = {}
        for inicio in range(0, len(todos_ids), 50):
            lote = ",".join(filter(None, todos_ids[inicio:inicio + 50]))
            if not lote:
                continue
            detalhes = requests.get(
                VIDEOS_URL,
                # contentDetails vem junto (mesma chamada) pela DURAÇÃO: é ela
                # que separa os Shorts dos vídeos longos na hora de aplicar as
                # regras duras do formato longo em escritor.py.
                params={"part": "statistics,contentDetails", "id": lote},
                headers=headers,
                timeout=60,
            )
            if detalhes.status_code != 200:
                raise RuntimeError(
                    f"{detalhes.status_code}: {detalhes.text[:300]}"
                )
            estatisticas.update(
                {
                    item["id"]: {
                        **item.get("statistics", {}),
                        "duracao_s": _duracao_iso(
                            item.get("contentDetails", {}).get("duration", "")
                        ),
                    }
                    for item in detalhes.json().get("items", [])
                }
            )

        videos = []
        for item in itens_lista:
            snippet = item.get("snippet", {})
            st = estatisticas.get(
                item.get("contentDetails", {}).get("videoId", ""), {}
            )
            videos.append(
                {
                    "titulo": snippet.get("title", ""),
                    "descricao": snippet.get("description", ""),
                    "data": snippet.get("publishedAt", "")[:16],
                    "views": int(st.get("viewCount") or 0),
                    "likes": int(st.get("likeCount") or 0),
                    "duracao_s": st.get("duracao_s") or 0,
                }
            )
        print(
            f"[youtube] {len(videos)} vídeos do canal carregados "
            f"(publicados desde {corte}, janela de {DIAS_REFERENCIA} dias)."
        )
        return videos
    except Exception as erro:  # noqa: BLE001 — sem os recentes a seleção é cega
        raise SystemExit(
            "Falha ao ler os últimos vídeos publicados do canal — eles são a "
            f"régua da seleção guiada pela audiência; abortando: {erro}"
        ) from erro


def _melhor_thumbnail(thumbnails: dict) -> str:
    """URL da maior capa disponível; "" quando o vídeo não traz nenhuma.

    A ordem é a da própria Data API, do maior para o menor. `maxres` não existe
    para todo vídeo (é gerada só acima de certa resolução de upload), e por isso
    a escolha é por tentativa e não por chave fixa.
    """
    for nome in ("maxres", "standard", "high", "medium", "default"):
        url = (thumbnails.get(nome) or {}).get("url")
        if url:
            return url
    return ""


def _lista_estrita(
    linhas: list[dict],
    medir_ganchos: Callable[[list[str]], None],
    ganchos: dict[str, float | None],
) -> list[dict]:
    """Os melhores vídeos do canal por ENGAJAMENTO, para servir de molde ao Short.

    Régua pedida pelo usuário em 2026-08-22, válida só no formato curto e nos
    dois canais: engajamento acima de ``ENGAJAMENTO_MINIMO`` e views acima do
    piso, ao mesmo tempo, com teto de ``LIMITE_REFERENCIA``.

    A RETENÇÃO NÃO ENTRA. Ela era o critério principal até este dia, e saiu
    depois de o usuário conferir os números no Studio e concluir que ela é
    irrelevante para este canal. Sobrou a métrica que descreve a decisão do
    espectador no instante que decide o Short: continuar assistindo ou deslizar
    fora. ``RETENCAO_MINIMA`` continua existindo — o formato LONGO ainda a usa.

    O ÚNICO afrouxamento é o de VIEWS, de ``PASSO_FALLBACK_VIEWS`` em
    ``PASSO_FALLBACK_VIEWS``, até a lista sair do vazio ou o piso chegar em
    ``VIEWS_MINIMO_ABSOLUTO``. O engajamento nunca cede: views é só a base
    estatística por trás do percentual — base menor ainda mede alguma coisa —,
    enquanto o engajamento é o critério, e critério que cede não é critério.

    ORDEM DOS FILTROS, e não é detalhe de estilo: as views saem do relatório em
    lote que já está na mão, e só quem passa nelas custa a chamada da curva de
    retenção (uma por vídeo). Filtrar na ordem inversa mediria o catálogo
    inteiro para descartar quase tudo depois.

    Vídeo SEM curva (``None``) fica de fora: o critério é "engajamento acima de
    X", e quem não foi medido não o satisfaz. Difere do formato longo, onde a
    ausência de medida perdoa — lá a régua prioriza, aqui ela veta. A contagem
    dos não medidos vai para o log, senão o corte fica inauditável.

    A ordem de saída é a do próprio engajamento, do maior para o menor, e o
    teto corta pelos piores. Não há mais o produto `gancho × profundidade` que
    ordenava a lista: com a retenção fora da régua, o que sobrou dele era só o
    gancho.

    Lista vazia no fim não é erro: é o canal não ter nenhum vídeo que sirva de
    molde, e a seleção segue sem a seção (ver ``_resumo_campeoes``).
    """
    piso = VIEWS_MINIMO_REFERENCIA
    while piso >= VIEWS_MINIMO_ABSOLUTO:
        base = [r for r in linhas if float(r.get("views") or 0) >= piso]
        if base:
            medir_ganchos([str(r.get("video", "")) for r in base])
            aprovados = [
                r
                for r in base
                if (ganchos.get(str(r.get("video"))) or 0) > ENGAJAMENTO_MINIMO
            ]
            if aprovados:
                if piso < VIEWS_MINIMO_REFERENCIA:
                    print(
                        f"[youtube] piso de views cedeu de "
                        f"{VIEWS_MINIMO_REFERENCIA} para {piso} até a lista "
                        "sair do vazio (o engajamento não cedeu)."
                    )
                sem_curva = sum(
                    1 for r in base if ganchos.get(str(r.get("video"))) is None
                )
                if sem_curva:
                    print(
                        f"[youtube] {sem_curva} vídeo(s) fora por não ter curva "
                        "de retenção (sem medida não há como afirmar o "
                        "engajamento)."
                    )
                aprovados.sort(
                    key=lambda r: ganchos.get(str(r.get("video"))) or 0,
                    reverse=True,
                )
                print(
                    f"[youtube] régua do Short: {len(aprovados)} de "
                    f"{len(base)} vídeo(s) com {piso}+ views passaram de "
                    f"{ENGAJAMENTO_MINIMO}% de engajamento"
                    + (
                        f"; ficam os {LIMITE_REFERENCIA} melhores."
                        if len(aprovados) > LIMITE_REFERENCIA
                        else "."
                    )
                )
                return aprovados[:LIMITE_REFERENCIA]
            print(
                f"[youtube] piso de {piso} views: {len(base)} vídeo(s), nenhum "
                f"acima de {ENGAJAMENTO_MINIMO}% de engajamento; afrouxando o "
                "piso."
            )
        piso -= PASSO_FALLBACK_VIEWS

    print(
        "[youtube] aviso: nenhum vídeo do canal passou nos dois critérios "
        f"(engajamento > {ENGAJAMENTO_MINIMO}%, views >= "
        f"{VIEWS_MINIMO_ABSOLUTO}); a seleção segue SEM molde."
    )
    return []


def top_retencao(cfg: Config, n_fallback: int = 6) -> list[dict]:
    """Vídeos do canal que servem de MOLDE, por RETENÇÃO, de todos os tempos.

    A métrica que manda é a RETENÇÃO — ``averageViewPercentage``, a mesma que o
    Studio mostra com esse nome. Até 2026-08-17 o piso era aplicado sobre o
    GANCHO (``engagedViews/views``), e a medição contra a API real mostrou que
    isso invertia o critério: no BR o único vídeo acima de 70% de gancho tinha
    183 views, e no US nenhum vídeo do catálogo jamais passou de 66,7% — os
    hits de 20k+ views ficavam todos DE FORA do molde. Ver ``RETENCAO_MINIMA``
    em config.py para os números completos. O gancho continua sendo lido e
    exibido, como desempate e como informação no prompt.

    DUAS RÉGUAS, escolhidas pelo formato (2026-08-22):

    - SHORT (``cfg.formato == "curto"``, os dois canais): régua ESTRITA, em
      ``_lista_estrita`` — retenção, engajamento e views simultâneos, sem teto
      de quantidade, e o único fallback é afrouxar as views de 100 em 100.
      Lista vazia é resposta legítima: melhor sem molde do que com molde ruim.
    - LONGO: o comportamento anterior, intacto — piso de views, teto de
      ``LIMITE_REFERENCIA``, engajamento como filtro que CEDE quando
      esvazia a lista, e ``n_fallback`` limitando o caminho de exceção (canal
      sem ninguém acima do piso cai para os melhores disponíveis, marcados como
      contraexemplo no prompt).

    Cada campeão volta com ``video_id``, ``titulo``, ``descricao`` e
    ``duracao_s`` além das métricas: é o que ``referencia.py`` usa para montar
    o dossiê do Short (frames + transcrição).

    Requer o escopo ``yt-analytics.readonly`` no refresh token; tokens antigos
    precisam de reautorização (``--auth-youtube``/``--auth-youtube-usa``).
    Qualquer falha ABORTA a execução (fail-fast): os campeões guiam a seleção
    da trend, e rodar sem eles degrada o vídeo silenciosamente. Canal novo sem
    métricas devolve lista vazia (não é erro).
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        canal = "inglês (-usa)" if cfg.publico == "usa" else "português"
        flag = "--auth-youtube-usa" if cfg.publico == "usa" else "--auth-youtube"
        raise SystemExit(
            f"Credenciais do YouTube do canal {canal} ausentes — sem elas não "
            "dá para ler a régua de engajamento que guia a seleção. "
            f"Configure o .env e rode 'python main.py {flag}'."
        )

    try:
        token = _renovar_access_token(cfg, refresh)
        headers = {"Authorization": f"Bearer {token}"}

        corte = _data_de_corte()
        params = {
            "ids": "channel==MINE",
            # A janela da Analytics acompanha a dos campeões: medir "desde
            # sempre" traria vídeos de ciclos de notícia mortos para o molde.
            "startDate": corte,
            "endDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "dimensions": "video",
            "metrics": "views,engagedViews,averageViewPercentage",
            "sort": "-views",
            "maxResults": 200,
        }
        resp = requests.get(ANALYTICS_URL, params=params, headers=headers, timeout=60)
        if resp.status_code == 400:
            # engagedViews pode não estar disponível; refaz só com as clássicas
            params["metrics"] = "views,averageViewPercentage"
            resp = requests.get(
                ANALYTICS_URL, params=params, headers=headers, timeout=60
            )
        if resp.status_code == 403:
            if "has not been used in project" in resp.text or "disabled" in resp.text:
                raise SystemExit(
                    "A YouTube Analytics API está desligada no projeto do "
                    "Google Cloud das credenciais — sem ela não há campeões de "
                    "retenção para guiar a seleção. Ative em "
                    "https://console.developers.google.com/apis/api/"
                    "youtubeanalytics.googleapis.com/overview e rode de novo."
                )
            raise SystemExit(
                "Sem permissão para a YouTube Analytics (o refresh token não "
                "tem o escopo yt-analytics.readonly) — sem ela não há campeões "
                "de retenção para guiar a seleção. Reautorize com "
                "'python main.py --auth-youtube' (e --auth-youtube-usa)."
            )
        if resp.status_code != 200:
            raise RuntimeError(f"{resp.status_code}: {resp.text[:300]}")

        corpo = resp.json()
        colunas = [c.get("name") for c in corpo.get("columnHeaders", [])]
        linhas = [dict(zip(colunas, valores)) for valores in corpo.get("rows") or []]
        if not linhas:
            return []

        def profundidade(r: dict) -> float:
            """% do vídeo que quem ficou assistiu."""
            return float(r.get("averageViewPercentage") or 0)

        def engajamento(r: dict) -> float | None:
            """% de quem abriu e FICOU, contra quem deslizou fora (desempate).

            Sem ``engagedViews`` na conta devolve None: o número não existe, e
            fingir que existe (caindo para a profundidade, como antes) mistura
            duas métricas debaixo do mesmo rótulo no prompt.
            """
            views = float(r.get("views") or 0)
            if views and "engagedViews" in r:
                return float(r.get("engagedViews") or 0) / views * 100
            return None

        def pontuacao(r: dict) -> float:
            """Gancho × profundidade — a ordenação que funcionava até 08-16.

            Ordena a lista; QUEM ENTRA nela é decidido pelos pisos. Sem
            ``engagedViews`` o fator vira 1.0 e a ordem passa a ser só a
            profundidade, que é o comportamento antigo.
            """
            g = engajamento(r)
            return (1.0 if g is None else g / 100) * (profundidade(r) / 100)

        # Título, DESCRIÇÃO e duração, em lote de 50 (o teto de `videos.list`).
        # A duração é necessária ANTES da curva de retenção, que é indexada por
        # fração do vídeo e não por segundo; título e descrição alimentam o
        # dossiê do Short (referencia.py). Preenchido sob demanda e
        # reaproveitado a cada afrouxamento do piso de views.
        detalhes: dict[str, dict] = {}

        def carregar_detalhes(ids: list[str]) -> None:
            faltando = [i for i in dict.fromkeys(ids) if i and i not in detalhes]
            for i in range(0, len(faltando), 50):
                resposta = requests.get(
                    VIDEOS_URL,
                    params={
                        "part": "snippet,contentDetails",
                        "id": ",".join(faltando[i : i + 50]),
                    },
                    headers=headers,
                    timeout=60,
                )
                if resposta.status_code != 200:
                    continue
                for item in resposta.json().get("items", []):
                    snippet = item.get("snippet", {})
                    detalhes[item["id"]] = {
                        "titulo": snippet.get("title", ""),
                        "descricao": snippet.get("description", ""),
                        "publicado_em": (snippet.get("publishedAt", "") or "")[:10],
                        "duracao_s": _duracao_iso(
                            item.get("contentDetails", {}).get("duration", "")
                        ),
                        "thumbnail": _melhor_thumbnail(
                            snippet.get("thumbnails", {})
                        ),
                    }

        # JANELA DOS CAMPEÕES (2026-08-24): a `startDate` da Analytics limita
        # o PERÍODO MEDIDO, não a idade do vídeo — um vídeo de um ano que ainda
        # recebe views apareceria nas linhas. O corte por DATA DE PUBLICAÇÃO é
        # este, e ele precisa dos detalhes, que custam 1 unidade por lote de 50.
        ids_medidos = [str(r.get("video", "")) for r in linhas]
        carregar_detalhes(ids_medidos)
        na_janela = [
            r
            for r in linhas
            if detalhes.get(str(r.get("video", {})), {}).get("publicado_em", "")
            >= corte
        ]
        if na_janela:
            if len(na_janela) < len(linhas):
                print(
                    f"[youtube] {len(linhas) - len(na_janela)} vídeo(s) fora da "
                    f"janela de {DIAS_REFERENCIA} dias (publicados antes de "
                    f"{corte}); ficam {len(na_janela)} na régua."
                )
            linhas = na_janela
        else:
            # Canal sem nada publicado na janela: melhor a régua antiga do que
            # régua nenhuma — sem campeões a seleção fica cega.
            print(
                f"[youtube] aviso: nenhum vídeo publicado nos últimos "
                f"{DIAS_REFERENCIA} dias entrou na medição; a régua usa o "
                "catálogo inteiro desta vez."
            )

        # ENGAJAMENTO pela curva de retenção — uma chamada por vídeo, em
        # paralelo (elas só esperam rede). Medido sob demanda e memorizado:
        # quando o piso de views cede, só os vídeos NOVOS da faixa custam
        # chamada; os já medidos são reaproveitados.
        ganchos: dict[str, float | None] = {}

        def medir_ganchos(ids: list[str]) -> None:
            faltando = [i for i in dict.fromkeys(ids) if i and i not in ganchos]
            if not faltando:
                return
            carregar_detalhes(faltando)
            with ThreadPoolExecutor(max_workers=CURVAS_PARALELAS) as executor:
                ganchos.update(
                    executor.map(
                        lambda v: _gancho_pela_curva(
                            v,
                            detalhes.get(v, {}).get("duracao_s", 0),
                            headers,
                            params["endDate"],
                        ),
                        faltando,
                    )
                )

        if getattr(cfg, "formato", "curto") == "curto":
            # Já sai ordenada por engajamento e cortada em LIMITE_REFERENCIA.
            top = _lista_estrita(linhas, medir_ganchos, ganchos)
            if not top:
                return []
        else:
            candidatos = [
                r
                for r in linhas
                if float(r.get("views") or 0) >= VIEWS_MINIMO_RETENCAO
            ] or linhas  # canal novo: sem vídeos acima do piso, usa o que houver
            ordenados = sorted(candidatos, key=pontuacao, reverse=True)
            acima = [
                r
                for r in ordenados
                if profundidade(r) > RETENCAO_MINIMA
                and float(r.get("views") or 0) >= VIEWS_MINIMO_REFERENCIA
            ][:LIMITE_REFERENCIA]
            if not acima:
                print(
                    f"[youtube] aviso: nenhum vídeo do canal com "
                    f"{VIEWS_MINIMO_REFERENCIA}+ views passou de "
                    f"{RETENCAO_MINIMA}% de retenção; a régua cai para os "
                    "melhores disponíveis (a seleção marca cada um abaixo do "
                    "piso, e o modelo sabe que são contraexemplo)."
                )
            top = acima or ordenados[:n_fallback]
            medir_ganchos([str(r.get("video", "")) for r in top])
            # Reprova só quem foi MEDIDO e ficou abaixo: sem curva (None) o
            # vídeo segue, porque a ausência de medição não é sinal de nada. Se
            # o piso esvaziar a lista, ele cede — a régua prioriza, não veta.
            com_gancho = [
                r
                for r in top
                if (ganchos.get(str(r.get("video"))) or ENGAJAMENTO_MINIMO + 1)
                > ENGAJAMENTO_MINIMO
            ]
            if com_gancho and len(com_gancho) < len(top):
                print(
                    f"[youtube] {len(top) - len(com_gancho)} vídeo(s) fora por "
                    f"engajamento abaixo de {ENGAJAMENTO_MINIMO}% aos "
                    f"{SEGUNDO_DO_GANCHO}s."
                )
                top = com_gancho
            elif not com_gancho:
                print(
                    f"[youtube] aviso: nenhum vídeo passou do piso de "
                    f"{ENGAJAMENTO_MINIMO}% de engajamento; o piso cede para "
                    "não deixar a seleção sem molde."
                )

        carregar_detalhes([str(r.get("video", "")) for r in top])
        campeoes = []
        for r in top:
            vid = str(r.get("video", ""))
            info = detalhes.get(vid, {})
            views = float(r.get("views") or 0)
            g = ganchos.get(vid)
            campeoes.append(
                {
                    # O id fica na lista: é por ele que referencia.py baixa o
                    # vídeo publicado para tirar frames e transcrever.
                    "video_id": vid,
                    "titulo": info.get("titulo") or vid,
                    "descricao": info.get("descricao", ""),
                    "duracao_s": info.get("duracao_s", 0),
                    # A capa é a única imagem do dossiê desde 2026-08-22, quando
                    # o download do vídeo saiu (ver referencia.py).
                    "thumbnail": info.get("thumbnail", ""),
                    "views": int(views),
                    # O rótulo de ALTA RETENÇÃO no prompt sai deste número
                    # (escritor._resumo_campeoes), então ele é o MESMO que o
                    # filtro usou.
                    "retencao_media": round(profundidade(r)),
                    "retencao_gancho": round(g) if g is not None else None,
                }
            )
        acima_do_piso = sum(
            1 for c in campeoes if c["retencao_media"] > RETENCAO_MINIMA
        )
        print(
            f"[youtube] {len(campeoes)} vídeos de referência carregados "
            f"({acima_do_piso} acima de {RETENCAO_MINIMA}% de retenção)."
        )
        # Os títulos entram no log: era impossível auditar a régua sabendo só a
        # contagem — a investigação de 2026-08-17 só achou o vídeo de 183 views
        # consultando a API por fora.
        for c in campeoes[:10]:
            gancho = (
                f"{c['retencao_gancho']}%"
                if c["retencao_gancho"] is not None
                else "?"
            )
            print(
                f"[youtube]   {c['views']:>7} views | retenção "
                f"{c['retencao_media']}% | engajamento {gancho} | "
                f"{c['titulo'][:60]}"
            )
        if len(campeoes) > 10:
            print(f"[youtube]   (+{len(campeoes) - 10} outros na lista)")
        return campeoes
    except Exception as erro:  # noqa: BLE001 — sem os campeões a seleção degrada
        raise SystemExit(
            "Falha ao ler a régua de engajamento do canal — ela guia a "
            f"seleção da trend; abortando: {erro}"
        ) from erro


def _enviar_thumbnail(token: str, video_id: str, thumbnail: Path) -> None:
    """Sobe a capa customizada. Falha aqui não derruba nada (só avisa).

    Precisa do canal verificado: sem verificação o YouTube devolve 403 e o
    vídeo fica com a capa automática — o aviso diz o que fazer.
    """
    try:
        resposta = requests.post(
            "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
            params={"videoId": video_id},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "image/jpeg",
            },
            data=thumbnail.read_bytes(),
            timeout=120,
        )
        if resposta.status_code in (200, 201):
            print("[youtube] Capa customizada aplicada.")
        elif resposta.status_code == 403:
            print(
                "[aviso] YouTube recusou a capa (403): o canal precisa estar "
                "VERIFICADO para aceitar thumbnail customizada. O vídeo está "
                "no ar com a capa automática."
            )
        else:
            print(
                f"[aviso] Capa não aplicada ({resposta.status_code}): "
                f"{resposta.text[:200]}. O vídeo está no ar."
            )
    except requests.RequestException as erro:
        print(f"[aviso] Capa não aplicada ({erro}). O vídeo está no ar.")


def publicar(
    cfg: Config,
    video: Path,
    titulo: str,
    descricao: str,
    tags: list[str] | None = None,
    thumbnail: Path | None = None,
) -> str:
    """Publica o vídeo no YouTube e devolve a URL.

    Qualquer falha ABORTA a execução com erro: terminar com sucesso sem
    publicar é a pior falha silenciosa possível (todo o custo gasto, nada no
    ar). O vídeo já está salvo em ``output/`` e registrado em ``videos.txt``,
    então dá para subir manualmente enquanto se investiga.
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        canal = "inglês (-usa)" if cfg.publico == "usa" else "português"
        flag = "--auth-youtube-usa" if cfg.publico == "usa" else "--auth-youtube"
        raise SystemExit(
            f"Credenciais do YouTube do canal {canal} ausentes — impossível "
            f"publicar. Rode 'python main.py {flag}' para autorizar. O vídeo "
            f"está salvo em {video}."
        )

    try:
        token = _renovar_access_token(cfg, refresh)

        tamanho = video.stat().st_size
        metadados = {
            "snippet": {
                "title": titulo[:100],
                "description": descricao[:5000],
                "tags": tags or [],
                "categoryId": cfg.youtube_category_id,
            },
            "status": {
                "privacyStatus": cfg.youtube_privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        print(f"[youtube] Publicando '{titulo}' ({cfg.youtube_privacy})...")
        inicio = requests.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Type": "video/*",
                "X-Upload-Content-Length": str(tamanho),
            },
            data=json.dumps(metadados).encode("utf-8"),
            timeout=60,
        )
        if inicio.status_code != 200:
            raise RuntimeError(
                f"YouTube recusou o início do upload ({inicio.status_code}): "
                f"{inicio.text[:300]}"
            )
        url_upload = inicio.headers["Location"]

        with open(video, "rb") as arq:
            envio = requests.put(
                url_upload,
                headers={
                    "Content-Type": "video/*",
                    "Content-Length": str(tamanho),
                },
                data=arq,
                timeout=600,
            )
        if envio.status_code not in (200, 201):
            raise RuntimeError(
                f"Falha no envio do vídeo ({envio.status_code}): {envio.text[:300]}"
            )

        video_id = envio.json()["id"]
        url = f"https://youtu.be/{video_id}"
        print(f"[youtube] Publicado: {url}")

        # Capa customizada, DEPOIS do upload e fora do try principal de
        # publicação: o vídeo já está no ar, e falhar aqui só custaria a capa
        # automática do YouTube — não vale derrubar uma execução inteira.
        if thumbnail is not None and thumbnail.is_file():
            _enviar_thumbnail(token, video_id, thumbnail)
        return url
    except Exception as erro:  # noqa: BLE001 — sucesso sem publicar é falha oculta
        raise SystemExit(
            f"Falha na publicação no YouTube: {erro}. O vídeo está salvo em "
            f"{video} — dá para subir manualmente enquanto investiga."
        ) from erro


def autenticar(cfg: Config, usa: bool = False) -> None:
    """Fluxo OAuth (uma vez): abre o navegador e salva o refresh token no .env.

    ``usa=True`` autoriza o canal em inglês e grava em
    ``YOUTUBE_REFRESH_TOKEN_USA``; caso contrário, o canal em português em
    ``YOUTUBE_REFRESH_TOKEN``. Escolha o canal certo na tela do Google.
    """
    if not (cfg.youtube_client_id and cfg.youtube_client_secret):
        raise SystemExit(
            "Defina YOUTUBE_CLIENT_ID e YOUTUBE_CLIENT_SECRET no .env antes de autenticar."
        )

    var_token = "YOUTUBE_REFRESH_TOKEN_USA" if usa else "YOUTUBE_REFRESH_TOKEN"
    canal = "inglês (-usa)" if usa else "português"
    print(f"[youtube] Autorizando o canal {canal}. Escolha-o na tela do Google.")

    codigo: dict[str, str] = {}
    estado = secrets.token_urlsafe(16)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            codigo["code"] = params.get("code", [""])[0]
            codigo["state"] = params.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                "<h2>Autorizacao concluida.</h2>"
                "<p>Pode fechar esta aba e voltar ao terminal.</p>".encode("utf-8")
            )

        def log_message(self, *_args) -> None:  # silencia o log do servidor
            pass

    servidor = http.server.HTTPServer(("localhost", 0), Handler)
    porta = servidor.server_address[1]
    redirect_uri = f"http://localhost:{porta}"

    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": cfg.youtube_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": ESCOPO,
            "access_type": "offline",
            "prompt": "consent",
            "state": estado,
        }
    )

    print("[youtube] Abrindo o navegador para autorização...")
    print(f"  Se não abrir, acesse manualmente:\n  {url}\n")
    threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    servidor.handle_request()  # aguarda o redirect com o código
    servidor.server_close()

    if codigo.get("state") != estado or not codigo.get("code"):
        raise SystemExit("Autorização inválida (state divergente ou código ausente).")

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": codigo["code"],
            "client_id": cfg.youtube_client_id,
            "client_secret": cfg.youtube_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise SystemExit(f"Falha ao obter o token ({resp.status_code}): {resp.text[:300]}")

    refresh = resp.json().get("refresh_token")
    if not refresh:
        raise SystemExit(
            "O Google não retornou refresh_token. Remova o acesso anterior em "
            "https://myaccount.google.com/permissions e tente de novo."
        )

    atualizar_env(var_token, refresh)
    os.environ[var_token] = refresh
    print(
        f"[youtube] Refresh token de longa duração do canal {canal} salvo em "
        f"{var_token} no .env. Tudo pronto!"
    )
