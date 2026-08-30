"""SEO e GEO: o que já disputa o assunto HOJE, e como o vídeo se apresenta.

Duas coisas moram aqui:

1. PANORAMA DO DIA (`panorama_do_dia`) — os vídeos que o YouTube já publicou
   sobre o mesmo assunto nas últimas horas, lidos da YouTube Data API
   (search.list + videos.list). Até 2026-08-07 o pipeline escolhia título,
   descrição e capa olhando SÓ para dentro do canal (os últimos publicados e os
   campeões de retenção). Isso calibra o TOM, mas não diz nada sobre a disputa
   real: quem mais cobriu o fato hoje, com que palavras, e o que está subindo
   rápido. O panorama traz esse lado de fora — títulos reais, views por hora e,
   principalmente, o VOCABULÁRIO DE TAGS que os vídeos daquele assunto estão
   usando naquele dia, que é a matéria-prima que faltava para as tags do canal
   (que, aliás, iam VAZIAS no upload: `roteiro.get("tags")` nunca existiu no
   esquema do roteiro, então todo vídeo subia sem tag nenhuma).

   CUSTO: uma chamada de search.list por execução. Ela não consome a cota
   normal de 10.000 unidades/dia — cai no balde separado de "Search Queries",
   com teto de 100 buscas/dia, então uma por execução é folgado. O
   videos.list que completa os dados custa 1 unidade.

   FALHA ABERTA, ao contrário de `ultimos_publicados`/`top_retencao`: aqueles
   são a RÉGUA da seleção (sem eles a pauta é escolhida às cegas, e por isso
   abortam). O panorama é contexto de redação — perdê-lo devolve exatamente o
   comportamento de antes de 2026-08-07, que já publicava vídeo. Derrubar uma
   execução paga por causa disso seria trocar um vídeo por nenhum vídeo.

2. MONTAGEM DA DESCRIÇÃO PUBLICADA (`montar_descricao`) — o texto que sobe
   para o YouTube não é mais só o parágrafo do roteirista. Ele passa a ser:

       parágrafo do payload (o resumo do fato, com a fonte)
       P: a pergunta de abertura / R: a resposta fechada, com número e fonte
       Capítulos (só no formato longo, quando dá para casar os tópicos)
       Fontes (só no formato longo)
       hashtags

   O bloco P/R é a parte de GEO (Generative Engine Optimization): motor de
   resposta generativo cita trecho AUTOSSUFICIENTE — uma frase que já traz a
   entidade, o número, a data e de quem veio. O parágrafo do roteirista é
   escrito para gente e costuma depender do vídeo ("isso significa que...");
   a resposta curta é escrita para ser extraída sozinha. As hashtags vão para
   o FIM em código, porque o modelo as escreve grudadas no fim do parágrafo e
   elas empurrariam o resto para longe dos primeiros caracteres, que são os
   que aparecem na busca.

O idioma dos rótulos ("P:"/"Q:", "Fontes:"/"Sources:") é regra de CANAL, como
todo o resto do pipeline: `cfg.publico` decide, nunca o modelo.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

import requests

from .config import Config
from .cortes import _tempo_do_char, localizar_citacao
from .youtube import (
    SEARCH_URL,
    VIDEOS_URL,
    _duracao_iso,
    _refresh_token_do_publico,
    _renovar_access_token,
)

# Região e idioma de relevância da busca, por canal. Sem isso a busca do canal
# brasileiro devolveria os vídeos americanos do mesmo assunto — que são a
# concorrência de outro canal, não a dele.
REGIAO_DO_CANAL = {"brasil": ("BR", "pt"), "usa": ("US", "en")}

# Teto de vídeos do dia lidos por execução (search.list aceita até 50).
MAX_VIDEOS_PADRAO = 20
# Tags mais frequentes levadas ao prompt. Acima disso o bloco vira ruído e o
# modelo começa a colar termo de outro assunto.
MAX_TAGS_VOCABULARIO = 24
# Teto de caracteres somados das tags de um vídeo no YouTube.
MAX_CARACTERES_TAGS = 480
MAX_TAGS = 15
MAX_CARACTERES_TAG = 40

# Posts do X listados como fontes na descrição publicada. Não é só crédito: é o
# REGISTRO do que a pauta consumiu, relido em toda execução para tirar da
# disputa a curtida que já virou vídeo (`x_client.posts_ja_usados`). O teto
# existe para a descrição não estourar os 5.000 caracteres do YouTube — a
# truncagem cortaria pelo fim, e o fim é justamente este bloco.
MAX_FONTES = 30
# Páginas da APURAÇÃO creditadas na descrição (apuracao.py, 2026-08-30). Teto
# próprio e curto: elas são crédito de leitura, não registro — nenhuma
# mecânica do pipeline as relê, e cada uma empurra o bloco de posts (esse sim
# relido) para mais perto do corte de 5.000 caracteres.
MAX_FONTES_APURACAO = 8
# Teto de caracteres da descrição no YouTube (`youtube.publicar` corta aqui).
MAX_DESCRICAO = 5000

# Capítulos (formato longo): o YouTube só ativa "momentos principais" quando o
# primeiro carimbo é 0:00, existem pelo menos 3 e cada trecho dura no mínimo
# 10 segundos. Abaixo disso o bloco não vira capítulo — vira lixo na descrição.
MIN_CAPITULOS = 3
MIN_SEGUNDOS_CAPITULO = 10.0

ROTULOS = {
    "brasil": {
        "pergunta": "P:",
        "resposta": "R:",
        "capitulos": "Capítulos:",
        "fontes": "Fontes:",
        "abertura": "Início",
    },
    "usa": {
        "pergunta": "Q:",
        "resposta": "A:",
        "capitulos": "Chapters:",
        "fontes": "Sources:",
        "abertura": "Intro",
    },
}


def _rotulos(publico: str) -> dict:
    return ROTULOS.get(publico, ROTULOS["brasil"])


# ---- Panorama do dia --------------------------------------------------------


def _buscar_ids(
    cfg: Config, headers: dict, consulta: str, desde: datetime, maximo: int
) -> list[str]:
    """IDs dos vídeos publicados desde `desde` que respondem pela consulta."""
    regiao, idioma = REGIAO_DO_CANAL.get(cfg.publico, REGIAO_DO_CANAL["brasil"])
    resp = requests.get(
        SEARCH_URL,
        params={
            "part": "id",
            "q": consulta,
            "type": "video",
            # viewCount dentro de uma janela de horas = o que ESTOUROU hoje,
            # que é o sinal útil. Por relevância viria a mesma lista de sempre,
            # dominada por vídeo antigo e consolidado.
            "order": "viewCount",
            "publishedAfter": desde.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "maxResults": min(max(maximo, 1), 50),
            "regionCode": regiao,
            "relevanceLanguage": idioma,
        },
        headers=headers,
        timeout=60,
    )
    if resp.status_code == 403 and "quota" in resp.text.lower():
        raise RuntimeError(
            "cota de buscas da YouTube Data API esgotada (o balde de Search "
            "Queries é de 100 buscas/dia, separado das 10.000 unidades)"
        )
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:300]}")
    return [
        item["id"]["videoId"]
        for item in resp.json().get("items", [])
        if (item.get("id") or {}).get("videoId")
    ]


def _detalhar(headers: dict, ids: list[str]) -> list[dict]:
    """Título, canal, tags, views e duração de cada vídeo achado (1 unidade)."""
    resp = requests.get(
        VIDEOS_URL,
        params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids)},
        headers=headers,
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code}: {resp.text[:300]}")

    agora = datetime.now(timezone.utc)
    videos = []
    for item in resp.json().get("items", []):
        snippet = item.get("snippet", {})
        try:
            publicado = datetime.fromisoformat(
                (snippet.get("publishedAt") or "").replace("Z", "+00:00")
            )
            horas = max((agora - publicado).total_seconds() / 3600, 0.5)
        except ValueError:
            horas = None
        views = int(item.get("statistics", {}).get("viewCount") or 0)
        videos.append(
            {
                "titulo": snippet.get("title", ""),
                "canal": snippet.get("channelTitle", ""),
                "tags": [t for t in (snippet.get("tags") or []) if t.strip()],
                "views": views,
                "horas": horas,
                "views_h": (views / horas) if horas else None,
                "duracao_s": _duracao_iso(
                    item.get("contentDetails", {}).get("duration", "")
                ),
            }
        )
    return videos


def panorama_do_dia(cfg: Config, consulta: str) -> dict | None:
    """Vídeos publicados na janela do dia sobre o assunto; None se não deu.

    `consulta` é a consulta de busca no idioma do canal que a seleção da trend
    devolve (`consulta_youtube`). A janela é a mesma da coleta do X
    (``cfg.janela_horas``): o vídeo do canal disputa com quem publicou sobre o
    mesmo fato desde que ele apareceu, não com o acervo do assunto.

    Falha aberta em TUDO (credencial ausente, cota, API fora, consulta vazia):
    devolve None com um aviso no log e o pipeline segue escrevendo como
    escrevia antes. Ver a docstring do módulo para o porquê.
    """
    if not getattr(cfg, "seo_panorama", True):
        print("[seo] Panorama do dia desligado (SEO_PANORAMA=0).")
        return None
    consulta = (consulta or "").strip()
    if not consulta:
        print("[seo] Sem consulta de busca; panorama do dia pulado.")
        return None

    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        print(
            "[seo] Credenciais do YouTube ausentes; panorama do dia pulado "
            "(título, descrição e capa seguem só com a régua interna do canal)."
        )
        return None

    janela = getattr(cfg, "janela_horas", 24) or 24
    maximo = getattr(cfg, "seo_max_videos", MAX_VIDEOS_PADRAO) or MAX_VIDEOS_PADRAO
    desde = datetime.now(timezone.utc) - timedelta(hours=janela)
    try:
        headers = {"Authorization": f"Bearer {_renovar_access_token(cfg, refresh)}"}
        print(
            f"[seo] Buscando vídeos das últimas {janela}h sobre "
            f"\"{consulta}\"..."
        )
        ids = _buscar_ids(cfg, headers, consulta, desde, maximo)
        if not ids:
            print(
                "[seo] Nenhum vídeo publicado na janela para essa consulta — "
                "o assunto está livre no YouTube (ou a consulta ficou estreita "
                "demais)."
            )
            return None
        videos = _detalhar(headers, ids)
    except Exception as erro:  # noqa: BLE001 — falha aberta, ver docstring
        print(
            f"[seo] aviso: panorama do dia falhou ({erro}); o vídeo segue com "
            "título, descrição e capa calibrados só pelo histórico do canal."
        )
        return None

    videos.sort(key=lambda v: (v["views_h"] is None, -(v["views_h"] or 0)))

    contagem: Counter[str] = Counter()
    for v in videos:
        # Um vídeo só não pode empilhar o mesmo termo: as tags já vêm únicas
        # por vídeo, mas variações de caixa contariam duas vezes no total.
        for tag in {t.strip().lower() for t in v["tags"]}:
            if 2 <= len(tag) <= MAX_CARACTERES_TAG:
                contagem[tag] += 1

    panorama = {
        "consulta": consulta,
        "janela_horas": janela,
        "videos": videos,
        "tags_frequentes": contagem.most_common(MAX_TAGS_VOCABULARIO),
    }
    print(
        f"[seo] {len(videos)} vídeo(s) do dia sobre o assunto; "
        f"{len(contagem)} termo(s) distintos nas tags deles."
    )
    lider = videos[0]
    if lider.get("views_h"):
        print(
            f"[seo] O que mais sobe: \"{lider['titulo']}\" "
            f"({lider['canal']}, {lider['views_h']:.0f} views/h)"
        )
    return panorama


def resumo_para_prompt(panorama: dict | None, maximo: int = 10) -> str:
    """Bloco do panorama para o prompt do roteirista (vazio se não há dados)."""
    if not panorama or not panorama.get("videos"):
        return ""
    linhas = [
        "\n\nCONCORRÊNCIA DE HOJE NO YOUTUBE — vídeos que JÁ ESTÃO NO AR sobre "
        f"este mesmo assunto, publicados nas últimas {panorama['janela_horas']}h "
        f"(busca real na YouTube Data API por \"{panorama['consulta']}\", "
        "ordenados pelo ritmo de views por hora). É contra estes títulos que o "
        "nosso vai aparecer lado a lado na busca e no 'a seguir':"
    ]
    for v in panorama["videos"][:maximo]:
        idade = f"há {v['horas']:.0f}h" if v.get("horas") else "idade ?"
        ritmo = f", {v['views_h']:.0f} views/h" if v.get("views_h") else ""
        linhas.append(
            f"- ({idade}) {v['titulo']} — {v['canal']}, "
            f"{v['views']} views{ritmo}"
        )
    if panorama.get("tags_frequentes"):
        vocabulario = ", ".join(
            f"{tag} ({n})" for tag, n in panorama["tags_frequentes"]
        )
        linhas.append(
            "\nVOCABULÁRIO DE TAGS desses vídeos, com quantos deles usam cada "
            "termo — é assim que o público e o algoritmo estão NOMEANDO este "
            f"assunto hoje:\n{vocabulario}"
        )
    return "\n".join(linhas)


def titulos_do_dia(panorama: dict | None, maximo: int = 8) -> list[str]:
    """Só os títulos concorrentes (usado pela capa, que não precisa do resto)."""
    if not panorama:
        return []
    return [v["titulo"] for v in panorama.get("videos", [])[:maximo] if v["titulo"]]


# ---- Tags do vídeo ----------------------------------------------------------


def limpar_tags(tags: list[str] | None) -> list[str]:
    """Sanea as tags devolvidas pelo modelo para o formato que a API aceita.

    Regra de comportamento nunca fica só no prompt (mesma lição da auditoria
    pró-leigo e do idioma da capa): aqui o que importa é o limite real da API —
    o YouTube recusa o upload inteiro quando a soma das tags passa de 500
    caracteres, e uma tag perdida derrubaria a publicação de um vídeo já pago.
    Também tira o '#' (tag não é hashtag) e remove repetição por caixa.
    """
    limpas: list[str] = []
    vistas: set[str] = set()
    total = 0
    for bruta in tags or []:
        tag = " ".join(str(bruta).replace("#", " ").split()).strip(" ,;")
        if not tag or len(tag) > MAX_CARACTERES_TAG:
            continue
        chave = tag.lower()
        if chave in vistas:
            continue
        # A API conta os caracteres somados; aspas em tag com espaço contam
        # dobrado no cálculo do YouTube, então a folga de MAX_CARACTERES_TAGS
        # para os 500 reais é de propósito.
        if total + len(tag) > MAX_CARACTERES_TAGS or len(limpas) >= MAX_TAGS:
            break
        vistas.add(chave)
        limpas.append(tag)
        total += len(tag)
    return limpas


# ---- Descrição publicada ----------------------------------------------------


def _separar_hashtags(descricao: str) -> tuple[str, str]:
    """(parágrafo, hashtags) — as hashtags do fim saem para serem recolocadas.

    O esquema do roteiro pede as hashtags grudadas no fim da descrição. Elas
    precisam ficar por último no texto publicado, depois do P/R e dos
    capítulos, senão empurram o conteúdo para fora dos primeiros caracteres —
    que são os que o YouTube mostra na busca e os que um motor de resposta lê
    primeiro.
    """
    palavras = descricao.split()
    corte = len(palavras)
    while corte > 0 and palavras[corte - 1].startswith("#"):
        corte -= 1
    if corte == len(palavras):
        return descricao.strip(), ""
    return " ".join(palavras[:corte]).strip(), " ".join(palavras[corte:]).strip()


def _mm_ss(segundos: float) -> str:
    total = int(segundos)
    if total >= 3600:
        return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


def capitulos(
    roteiro: dict, texto_video: str, alinhamento: dict, duracao: float, publico: str
) -> list[tuple[float, str]]:
    """Capítulos do vídeo longo, ancorados na narração; vazio se não fecham.

    Cada tópico do roteiro traz uma CITAÇÃO literal do trecho da narração em
    que ele começa (mesmo mecanismo das cartelas): a citação é
    procurada no texto e o alinhamento do ElevenLabs devolve o instante exato.
    Capítulo com carimbo chutado seria pior que capítulo nenhum — ele promete
    ao espectador um ponto do vídeo que não existe.

    Devolve [] quando não dá para montar um bloco VÁLIDO (menos de
    MIN_CAPITULOS, trechos colados demais ou citação que não bate): o YouTube
    ignora um bloco inválido e o que sobra é ruído na descrição.
    """
    topicos = roteiro.get("topicos") or []
    if len(topicos) + 1 < MIN_CAPITULOS:
        return []

    # Mesma busca da montagem (cortes.localizar_citacao): tolera audio tag no
    # meio da frase e espaço colapsado. Antes era um `find` cru no texto, e o
    # capítulo sumia quando o modelo copiava a fala por cima de um "[pausa]".
    marcos: list[tuple[float, str]] = []
    cursor = 0
    for t in topicos:
        citacao = (t.get("citacao") or "").strip()
        titulo = " ".join((t.get("titulo") or "").split())
        if not citacao or not titulo:
            continue
        pos = localizar_citacao(texto_video, citacao, cursor)
        if pos is None:
            print(f"[seo] Capítulo sem âncora na narração, descartado: {titulo}")
            continue
        cursor = pos + 1
        marcos.append(
            (_tempo_do_char(alinhamento, texto_video, pos, duracao), titulo)
        )

    marcos.sort(key=lambda m: m[0])
    # O capítulo 0:00 é a PAUTA FALADA — os primeiros ~6 segundos em que a
    # narração diz o que o vídeo vai tratar. Até 2026-08-24 ele levava a
    # "pergunta esquisita" de abertura, que deixou de ser falada: manter a
    # pergunta ali prometeria ao espectador um trecho que não existe mais.
    abertura = _rotulos(publico)["abertura"]
    lista: list[tuple[float, str]] = [(0.0, abertura)]
    for inicio, titulo in marcos:
        if inicio - lista[-1][0] < MIN_SEGUNDOS_CAPITULO:
            continue  # trecho curto demais: o YouTube rejeitaria o bloco todo
        if duracao - inicio < MIN_SEGUNDOS_CAPITULO:
            continue  # capítulo colado no fim do vídeo
        lista.append((inicio, titulo))

    if len(lista) < MIN_CAPITULOS:
        print(
            f"[seo] Só {len(lista)} capítulo(s) válido(s) (o YouTube exige "
            f"{MIN_CAPITULOS}); a descrição sai sem o bloco."
        )
        return []
    return lista


def montar_descricao(
    roteiro: dict,
    publico: str,
    formato: str = "curto",
    trend: dict | None = None,
    marcos: list[tuple[float, str]] | None = None,
    fontes_apuracao: list[str] | None = None,
) -> str:
    """Monta a descrição publicada a partir das peças do roteiro.

    Ordem, e o motivo de cada uma:
    1. o parágrafo do payload — os primeiros ~150 caracteres são o que aparece
       na busca do YouTube;
    2. o par P/R — a parte de GEO: uma pergunta e uma resposta autossuficiente,
       com número e fonte, no formato que motor de resposta generativo extrai;
    3. os capítulos (formato longo, quando fecham) — viram "momentos
       principais" e dão ao YouTube um índice do que o vídeo cobre;
    4. as fontes reais — os posts do X de onde a pauta e os clipes saíram e,
       depois deles, as páginas que a apuração leu (`fontes_apuracao`);
    5. as hashtags, sempre por último.

    O BLOCO DE FONTES SAI NOS DOIS FORMATOS desde 2026-08-30. Ele era só do
    longo, e era isso que quebrava o desenho das curtidas ("esgotar os vídeos
    curtidos pela descrição dos nossos vídeos"): sem o link do post na
    descrição do Short, nada marcava a curtida como GASTA, e ela voltava à
    disputa em toda execução — foi assim que o laser de matar mosquito saiu
    duas vezes no canal BR. A descrição publicada é a ÚNICA memória durável do
    pipeline (o disco do Render é efêmero e `videos.txt` morre com o
    contêiner), então é ela que carrega o registro. Quem lê estes links de
    volta é `x_client.posts_ja_usados`.
    """
    rotulos = _rotulos(publico)
    paragrafo, hashtags = _separar_hashtags(roteiro.get("descricao") or "")
    blocos = [paragrafo] if paragrafo else []

    pergunta = " ".join((roteiro.get("pergunta") or "").split())
    resposta = " ".join((roteiro.get("resposta_curta") or "").split())
    if pergunta and resposta:
        if not pergunta.endswith("?"):
            pergunta += "?"
        blocos.append(
            f"{rotulos['pergunta']} {pergunta}\n{rotulos['resposta']} {resposta}"
        )

    if marcos:
        linhas = [f"{_mm_ss(t)} {titulo}" for t, titulo in marcos]
        blocos.append(rotulos["capitulos"] + "\n" + "\n".join(linhas))

    # NOS DOIS FORMATOS (2026-08-30) — ver o cabeçalho da função. O teto subiu
    # de 10 para MAX_FONTES porque cada URL que fica de fora é um post curtido
    # que NÃO conta como gasto: a lista precisa cobrir os posts da pauta
    # inteira, não uma amostra dela.
    urls = list(
        dict.fromkeys(u for u in ((trend or {}).get("posts") or []) if u)
    )[:MAX_FONTES]
    # AS PÁGINAS DA APURAÇÃO ENTRAM DEPOIS DOS POSTS (2026-08-30), e a ordem é
    # a coisa importante aqui. Duas razões, as duas mecânicas:
    #
    # 1. O bloco é lido de volta por `x_client.posts_ja_usados`, que é o
    #    registro de qual curtida já virou vídeo. Ele casa um padrão de
    #    x.com/.../status/<id>, então link de veículo passa batido e não
    #    contamina a memória — mas só porque ele fica FORA do padrão, nunca
    #    porque alguém o filtrou.
    # 2. Quando a descrição estoura os 5.000 caracteres, o laço logo abaixo
    #    corta URLs PELO FIM. Com a apuração no fim, quem cede primeiro é o
    #    crédito de leitura; o registro dos posts, que é o que impede a mesma
    #    pauta de sair duas vezes, é o último a sair.
    urls += [
        u for u in dict.fromkeys(fontes_apuracao or []) if u and u not in urls
    ][:MAX_FONTES_APURACAO]
    indice_fontes = -1
    if urls:
        indice_fontes = len(blocos)
        blocos.append(
            rotulos["fontes"] + "\n" + "\n".join(f"- {u}" for u in urls)
        )

    if hashtags:
        blocos.append(hashtags)
    descricao = "\n\n".join(blocos)
    # O YouTube corta a descrição em 5.000 caracteres (`youtube.publicar`), e o
    # corte é PELO FIM — onde moram as fontes. Perder um link ali não é perder
    # crédito, é perder o registro que impede o post de virar vídeo de novo,
    # então quando o texto passa do teto quem cede são as URLs (as últimas
    # primeiro), e não o bloco inteiro.
    while len(descricao) > MAX_DESCRICAO and urls:
        urls.pop()
        if urls:
            blocos[indice_fontes] = (
                rotulos["fontes"] + "\n" + "\n".join(f"- {u}" for u in urls)
            )
        else:
            del blocos[indice_fontes]  # rótulo sozinho seria ruído
        descricao = "\n\n".join(blocos)
    return descricao
