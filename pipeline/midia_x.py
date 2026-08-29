"""Download e descrição das mídias dos posts da trend.

O CORPO do vídeo é montado somente com clipes de vídeo dos posts do X (imagem
estática nunca entra em tela cheia). Download via X API oficial v2 em modo
pay-per-use (~US$ 0,005 por post/mídia lida): um único GET /2/tweets com
`expansions=attachments.media_keys,author_id` resolve todos os posts da trend
de uma vez. Vídeos vêm como variantes MP4, das quais baixamos a de maior
bitrate QUE CABE em MAX_VIDEO_BYTES — as versões 4K do X passam de 2 GB, e
antes descartá-las descartava o clipe; a conta do autor (@usuario) segue junto
de cada mídia para o crédito de reprodução exibido na tela ("Reprodução
Imagem: X / Conta @...").

Baixamos um POOL maior que o necessário (`max_clipes + pool_extra_clipes`):
a auditoria (auditoria.py) reprova material de telejornal e clipe que não
condiz com a narração, e sem folga a reprovação só teria como resultado
abortar o vídeo.

As FOTOS dos posts também são baixadas (antes eram descartadas no filtro de
tipo): elas não entram em tela cheia — alimentam as cartelas sobrepostas nos
momentos-chave (cartelas.py).

Descrição via GPT com visão sobre os arquivos baixados (o ffmpeg extrai alguns
frames de cada clipe). A descrição vem em JSON estruturado: além do texto que
orienta o planejador de cortes (cortes.py), traz a CLASSIFICAÇÃO do material
(cena real, reportagem de TV, gravação de tela...) e se há selo de emissora na
imagem — os dois sinais em que a auditoria aplica veto duro.
"""

import base64
import json
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config
from .edicao import duracao_audio
from .x_client import obter_bearer

TWEETS_ENDPOINT = "https://api.x.com/2/tweets"

# Tetos do formato curto (Shorts). O formato longo (--long-take) sobe todos
# via Config (cfg.max_posts_midia / cfg.max_clipes / cfg.max_fotos): 2 minutos
# de tela pedem mais material, e cada post/mídia lida custa ~US$ 0,005.
MAX_POSTS = 12  # posts consultados por vídeo (cada um custa ~US$ 0,005)
MAX_CLIPES = 3  # clipes de vídeo USADOS na montagem (o pool baixado é maior)
POOL_EXTRA = 3  # clipes baixados além do necessário, como folga da auditoria
MAX_FOTOS = 4  # fotos baixadas para as cartelas sobrepostas
# Clipes que uma MESMA conta pode ocupar no pool antes de as vagas irem para
# outras (2026-08-17). 2 permite um veículo mostrar dois ângulos do fato sem
# tomar o pool inteiro; o que sobrar de vaga volta para quem foi adiado.
MAX_CLIPES_POR_CONTA = 2
MAX_VIDEO_BYTES = 60_000_000  # ~60 MB; vídeo maior que isso é descartado
MAX_FOTO_BYTES = 25_000_000  # ~25 MB; foto maior que isso é descartada

PADRAO_ID_POST = re.compile(r"(?:x|twitter)\.com/[^/]+/status/(\d+)")


def _ids_dos_posts(urls: list[str], max_posts: int = MAX_POSTS) -> list[str]:
    ids = [m.group(1) for u in urls if (m := PADRAO_ID_POST.search(u))]
    return list(dict.fromkeys(ids))[:max_posts]


def _variantes_mp4(variantes: list[dict]) -> list[str]:
    """URLs MP4 do mesmo clipe, da maior para a menor qualidade.

    Devolve a LISTA, e não só a melhor: o X serve o mesmo clipe em várias
    resoluções e a de cima às vezes é 4K. Em 2026-08-05 o único candidato de
    uma execução era um 3840x2160 de 2,9 GB — muito acima de MAX_VIDEO_BYTES —
    e descartá-lo derrubou o vídeo inteiro, com as versões menores do MESMO
    clipe disponíveis na mesma resposta. Quem baixa desce a lista até uma
    caber (`_baixar_melhor_variante`).
    """
    mp4s = [
        v for v in variantes
        if v.get("content_type") == "video/mp4" and v.get("url")
    ]
    mp4s.sort(key=lambda v: v.get("bit_rate") or 0, reverse=True)
    return [v["url"] for v in mp4s]


def _baixar_arquivo(url: str, destino: Path, teto: int = MAX_VIDEO_BYTES) -> Path | None:
    """Baixa em streaming com teto de tamanho; None em qualquer falha."""
    try:
        with requests.get(url, timeout=120, stream=True) as resp:
            resp.raise_for_status()
            tamanho = int(resp.headers.get("Content-Length") or 0)
            if tamanho > teto:
                print(f"[aviso] Mídia de {url} grande demais ({tamanho} bytes), pulando")
                return None
            baixado = 0
            with destino.open("wb") as arquivo:
                for pedaco in resp.iter_content(chunk_size=1 << 16):
                    baixado += len(pedaco)
                    if baixado > teto:
                        print(f"[aviso] Mídia de {url} passou do teto durante o download")
                        arquivo.close()
                        destino.unlink(missing_ok=True)
                        return None
                    arquivo.write(pedaco)
        return destino
    except requests.RequestException as erro:
        print(f"[aviso] Falha ao baixar mídia {url}: {erro}")
        destino.unlink(missing_ok=True)
        return None


def _baixar_melhor_variante(urls: list[str], destino: Path) -> Path | None:
    """Baixa a melhor variante do clipe que couber no teto, descendo a lista.

    A variante de cima estourar MAX_VIDEO_BYTES não diz nada sobre o clipe —
    só sobre aquela resolução. Antes um 4K de 2,9 GB descartava o clipe
    inteiro; agora ele custa uma requisição perdida e o download segue na
    resolução de baixo.
    """
    for k, url in enumerate(urls, 1):
        caminho = _baixar_arquivo(url, destino)
        if caminho:
            if k > 1:
                print(
                    f"[midia-x] {destino.name}: baixado na variante {k} de "
                    f"{len(urls)} (as de cima não couberam no teto de "
                    f"{MAX_VIDEO_BYTES // 1_000_000} MB)"
                )
            return caminho
    return None


def baixar_midias_posts(
    cfg: Config, urls_posts: list[str], pasta: Path
) -> tuple[list[dict], list[dict]]:
    """Baixa as mídias dos posts da trend; devolve (clipes, fotos).

    Cada item é {"caminho": Path, "tipo": str, "conta": "@usuario", ...}. Os
    CLIPES (vídeo e GIF animado, que sai como .mp4) montam o corpo do vídeo e
    vêm com folga — `max_clipes + pool_extra_clipes` — porque a auditoria
    reprova parte deles. As FOTOS não entram em tela cheia: alimentam as
    cartelas sobrepostas dos momentos-chave (cartelas.py).

    Falhas de credencial/API ABORTAM a execução: a trend é escolhida
    justamente por ter clipes nos posts, e pular a etapa entregaria um vídeo
    sem material nenhum.
    """
    max_posts = getattr(cfg, "max_posts_midia", MAX_POSTS) or MAX_POSTS
    max_clipes = getattr(cfg, "max_clipes", MAX_CLIPES) or MAX_CLIPES
    pool = max_clipes + (getattr(cfg, "pool_extra_clipes", POOL_EXTRA) or 0)
    max_fotos = getattr(cfg, "max_fotos", MAX_FOTOS) or 0
    ids = _ids_dos_posts(urls_posts, max_posts)
    if not ids:
        return [], []

    if not (cfg.x_consumer_key and cfg.x_consumer_secret):
        raise SystemExit(
            "X_CONSUMER_KEY/X_CONSUMER_SECRET ausentes — sem eles não dá para "
            "baixar os clipes dos posts da trend; abortando."
        )
    token = obter_bearer(cfg)
    if token is None:
        raise SystemExit(
            "X API sem token — sem ele não dá para baixar os clipes dos posts "
            "da trend; abortando. Confira as credenciais no .env."
        )

    print(f"[midia-x] Consultando {len(ids)} posts da trend na X API...")
    try:
        resp = requests.get(
            TWEETS_ENDPOINT,
            params={
                "ids": ",".join(ids),
                "tweet.fields": "text",
                "expansions": "attachments.media_keys,author_id",
                "user.fields": "username",
                "media.fields": (
                    "media_key,type,url,variants,preview_image_url,width,"
                    "height,duration_ms"
                ),
            },
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
        dados = resp.json()
    except (requests.RequestException, ValueError) as erro:
        raise SystemExit(
            f"X API: lookup dos posts da trend falhou — o vídeo sairia sem o "
            f"material que motivou a escolha da trend; abortando: {erro}"
        ) from erro

    includes = dados.get("includes") or {}
    midias = includes.get("media") or []
    if not midias:
        print("[midia-x] Nenhuma mídia anexada nos posts consultados")
        return [], []

    # De qual post veio cada mídia, o texto do post (contexto para a
    # descrição) e a conta do autor (crédito de reprodução na tela).
    usuarios = {u.get("id"): u.get("username", "") for u in includes.get("users") or []}
    dono_da_midia: dict[str, str] = {}
    texto_do_post: dict[str, str] = {}
    conta_do_post: dict[str, str] = {}
    for post in dados.get("data") or []:
        post_id = post.get("id", "")
        texto_do_post[post_id] = post.get("text", "")
        usuario = usuarios.get(post.get("author_id"), "")
        conta_do_post[post_id] = f"@{usuario}" if usuario else ""
        for chave in (post.get("attachments") or {}).get("media_keys") or []:
            dono_da_midia.setdefault(chave, post_id)

    def _comum(m: dict, caminho: Path) -> dict:
        post_id = dono_da_midia.get(m.get("media_key", ""), "")
        return {
            "caminho": caminho,
            "trecho": "",
            "tipo": m.get("type"),
            "post_id": post_id,
            "conta": conta_do_post.get(post_id, ""),
            "texto_post": texto_do_post.get(post_id, ""),
        }

    brutos = [m for m in midias if m.get("type") in ("video", "animated_gif")]
    # TETO DE DURAÇÃO DO CLIPE NO SHORT (2026-08-28, pedido do usuário: "só
    # escolha vídeos que tenham até 30 segundos no máximo"). A coleta já
    # descartou o POST cujo menor clipe passa do teto (x_client), mas um post
    # aprovado pode trazer os dois — o corte de 20s e a íntegra de 6 minutos —,
    # e é aqui que a íntegra fica de fora. Ganho duplo: ela não ocupa vaga no
    # pool e não gasta banda, porque o corte acontece ANTES do download.
    #
    # O formato longo não tem teto: lá o clipe ocupa uma parte inteira do vídeo
    # e a montagem continua repetindo em loop, então clipe comprido é ganho.
    if cfg.formato == "curto":
        teto_ms = float(cfg.curto_max_dur_clipe_s) * 1000.0
        cabem = [
            m for m in brutos
            # Duração desconhecida (o X não a informa para GIF animado) não
            # veta: sem medida não há teto a aplicar, e vetar por falta de dado
            # jogaria fora material bom.
            if not isinstance(m.get("duration_ms"), (int, float))
            or float(m["duration_ms"]) <= teto_ms
        ]
        if len(cabem) < len(brutos):
            print(
                f"[midia-x] {len(brutos) - len(cabem)} clipe(s) acima do teto "
                f"de {cfg.curto_max_dur_clipe_s}s do Short fora do pool "
                f"(o Short não repete clipe, então só entra o que cabe inteiro)"
            )
        brutos = cabem
    if not brutos:
        print("[midia-x] Nenhum clipe de vídeo anexado nos posts consultados")

    clipes: list[dict] = []
    por_conta: dict[str, int] = {}
    baixados = 0

    def _conta_da(m: dict) -> str:
        return conta_do_post.get(dono_da_midia.get(m.get("media_key", ""), ""), "")

    def _para_o_pool(m: dict) -> None:
        nonlocal baixados
        urls_mp4 = _variantes_mp4(m.get("variants") or [])
        if not urls_mp4:
            return
        baixados += 1
        caminho = _baixar_melhor_variante(
            urls_mp4, pasta / f"clipe_x_{baixados}.mp4"
        )
        if not caminho:
            return
        conta = _conta_da(m)
        por_conta[conta] = por_conta.get(conta, 0) + 1
        try:
            dur_s = duracao_audio(caminho)  # ffprobe format=duration
        except (subprocess.CalledProcessError, ValueError, OSError):
            dur_s = None
        item = _comum(m, caminho) | {"dur_s": dur_s}
        clipes.append(item)
        print(
            f"[midia-x] {caminho.name} ({m.get('type')}, "
            f"{item['conta'] or 'conta desconhecida'})"
        )

    # TETO POR CONTA (2026-08-17): sem ele o pool virava a produção de uma conta
    # só. Medido em 17/08: de 8 clipes coletados, 4 eram do @business e 2 do
    # @HeyGen (anúncio de produto) — um pool que não representa a timeline e
    # concentra o risco de a auditoria reprovar tudo de uma vez, porque material
    # do mesmo veículo tem sempre o mesmo formato. Conta desconhecida não entra
    # na conta do teto: sem saber de quem é, não há concentração a evitar.
    adiados: list[dict] = []
    for m in brutos:
        if len(clipes) >= pool:
            break
        conta = _conta_da(m)
        if conta and por_conta.get(conta, 0) >= MAX_CLIPES_POR_CONTA:
            adiados.append(m)
            continue
        _para_o_pool(m)

    # As vagas que sobrarem voltam para quem o teto adiou: diversidade é
    # preferência, não sacrifício de material — pool menor é o que trava o
    # vídeo no piso da auditoria.
    for m in adiados:
        if len(clipes) >= pool:
            break
        _para_o_pool(m)
    if adiados and len(por_conta) > 1:
        print(
            f"[midia-x] Pool de {len(por_conta)} conta(s) distinta(s) "
            f"(teto de {MAX_CLIPES_POR_CONTA} por conta)"
        )

    # Fotos: nunca entram em tela cheia (o formato proíbe), só nas cartelas.
    fotos: list[dict] = []
    for k, m in enumerate(
        [m for m in midias if m.get("type") == "photo"][:max_fotos], 1
    ):
        url_foto = (m.get("url") or "").strip()
        if not url_foto:
            continue
        sufixo = Path(url_foto.split("?")[0]).suffix.lower() or ".jpg"
        if sufixo not in (".jpg", ".jpeg", ".png", ".webp"):
            sufixo = ".jpg"
        caminho = _baixar_arquivo(
            url_foto, pasta / f"foto_x_{k}{sufixo}", MAX_FOTO_BYTES
        )
        if not caminho:
            continue
        item = _comum(m, caminho) | {"dur_s": None, "origem": "x"}
        fotos.append(item)
        print(f"[midia-x] {caminho.name} (foto, {item['conta'] or '?'})")

    if not clipes:
        print("[midia-x] Nenhum clipe dos posts pôde ser baixado")
    else:
        print(
            f"[midia-x] Pool de {len(clipes)} clipe(s) para {max_clipes} "
            f"vaga(s) na montagem e {len(fotos)} foto(s) para as cartelas"
        )
    return clipes, fotos


# ---- Descrição das mídias baixadas (GPT com visão) ----

LADO_VISAO = 768  # px; lado máximo das imagens enviadas ao GPT (custo de visão)
# Frames por vídeo (2026-08-17). Eram 3, em 10%, 50% e 85% da duração — e a
# medição contra 8 clipes reais mostrou que essa amostragem DECIDIA POR SORTEIO:
# clipes com 5 de 8 frames de busto falante passavam e clipes com 3 de 8 eram
# vetados. A causa é onde os pontos caem: 10% e 85% de um vídeo de veículo são
# abertura e encerramento, justo onde o apresentador aparece, e o miolo (a cena
# que serve) entrava com um voto só. Um dos três ainda podia cair num flash de
# transição, como caiu num clipe da Bloomberg. Agora são 8 frames no CENTRO de
# fatias iguais: nenhum encosta nas pontas e o corpo do vídeo é que decide.
FRAMES_VIDEO = 8

# Classificação do material, base do veto duro da auditoria. O enum é fechado
# de propósito: a reclamação do canal é sobre um padrão recorrente (material de
# telejornal), e regra de código não oscila como julgamento de LLM.
TIPOS_MATERIAL = [
    "cena_real",  # o fato: pessoas, lugares, equipamentos, produto em uso
    "reportagem_tv",  # matéria de telejornal: âncora, repórter, tarja, VT
    "estudio_ou_podcast",  # entrevista/podcast/palestra (não é emissora)
    # As duas casas abaixo são O VETO desde 2026-08-29, quando `imagem_filmada`
    # saiu: elas cobrem exatamente as quatro coisas que o usuário mandou seguir
    # barrando (slide, apresentação, screenshot, gravação de tela) e nada além
    # disso. Animação, render, vídeo de IA, gameplay e filmagem dentro de
    # moldura NÃO entram aqui — vão para 'cena_real' ou 'outro' e passam.
    "gravacao_de_tela",  # captura de tela ou screenshot: app, site, terminal, planilha, gráfico
    "cartela_ou_manchete",  # slide, apresentação, cartela de texto, print de manchete
    "logo_ou_marca",  # só logotipo/vinheta
    "outro",
]

# Quanto da tela é texto escrito (2026-08-07). Nasce de um pedido direto: clipe
# de fundo cheio de texto — e principalmente texto PARADO — não pode entrar. O
# vídeo já tem legendas grandes queimadas e cartelas por cima; um
# clipe que também é texto vira uma tela onde nada se lê, e texto parado num
# fundo em movimento é a versão pior disso, porque fica lá os segundos todos.
# A escala é ordenada e a auditoria compara por posição (ver auditoria.py).
DENSIDADES_TEXTO = ["nenhum", "pouco", "moderado", "muito"]

# MOVIMENTO E TALKING HEAD (2026-08-09). Nasce do mesmo tipo de pedido que o
# veto de texto: clipe PARADO (o mesmo quadro do começo ao fim, foto com áudio,
# tela congelada) e clipe de PESSOA FALANDO PARA A CÂMERA não podem entrar. Os
# dois falham pelo mesmo motivo — o vídeo é montado sobre movimento, e um
# quadro que não muda ou um busto que só mexe a boca não mostram o fato, só
# ocupam a tela enquanto a narração o conta. A visão mede as duas coisas aqui;
# quem veta é a auditoria (auditoria.py).

# LIVE FOOTAGE: O CAMPO `imagem_filmada` FOI REMOVIDO em 2026-08-29 (pedido do
# usuário: "remova completamente o veto de live footage; só mantenha o veto a
# slides, apresentações, screenshots e gravações de tela"). Ele existiu entre
# 25 e 29/08 e exigia que uma CÂMERA tivesse filmado o clipe no mundo físico,
# o que barrava junto animação, motion graphics, render 3D, vídeo gerado por
# IA, gameplay e MOLDURA (filmagem dentro de mockup de celular ou de template)
# — tudo isso volta a ser material legítimo.
#
# O que o usuário quis manter cabe inteiro em `tipo_material`, e é por isso que
# o campo pôde sair em vez de encolher: 'gravacao_de_tela' cobre captura de
# tela e screenshot, 'cartela_ou_manchete' cobre slide, apresentação e print de
# manchete. Os dois estão em TIPOS_VETADOS_CLIPE (auditoria.py), e as
# descrições do enum e do prompt foram apertadas na mesma data justamente
# porque agora ELAS são o veto — antes um slide classificado como 'outro'
# ainda morria no `imagem_filmada`, e hoje passaria.

ESQUEMA_DESCRICAO = {
    "name": "descricao_de_midia",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "descricao": {
                "type": "string",
                "description": (
                    "2 a 4 frases OBJETIVAS: o que aparece (pessoas, produtos, "
                    "telas, lugares), o que acontece e qualquer texto legível. "
                    "Vai orientar um editor que NÃO viu a mídia: seja concreto "
                    "e sem opinião."
                ),
            },
            "tipo_material": {
                "type": "string",
                "enum": TIPOS_MATERIAL,
                "description": (
                    "Que TIPO de material é. 'reportagem_tv' sempre que houver "
                    "âncora/repórter em enquadramento de telejornal, tarja de "
                    "legenda inferior de emissora ou estrutura de VT "
                    "jornalístico. "
                    "'gravacao_de_tela' para captura de tela ou SCREENSHOT de "
                    "qualquer interface: app, site, navegador, terminal, chat, "
                    "planilha, gráfico de mercado, demo de software. "
                    "'cartela_ou_manchete' para SLIDE, APRESENTAÇÃO, cartela "
                    "de texto ou print de manchete — o quadro é um texto "
                    "escrito ou um bloco de tópicos, animado ou parado. "
                    "Animação, desenho, motion graphics SEM texto, render 3D, "
                    "vídeo gerado por IA, gameplay e filmagem posta dentro de "
                    "moldura ou mockup NÃO são nenhum dos dois: classifique "
                    "pelo que a cena mostra ('cena_real' ou 'outro')."
                ),
            },
            "selo_de_emissora": {
                "type": "boolean",
                "description": (
                    "true se aparece na imagem logotipo, selo de canto, tarja "
                    "ou marca d'água de EMISSORA DE TV ou VEÍCULO DE IMPRENSA "
                    "(CNN, Globo, BBC, Reuters, Fox...). Logotipo de empresa de "
                    "tecnologia ou de governo NÃO conta."
                ),
            },
            "marca_visivel": {
                "type": "string",
                "description": (
                    "Nome da marca/emissora cujo selo aparece; string vazia se "
                    "nenhuma."
                ),
            },
            "texto_na_tela": {
                "type": "string",
                "description": (
                    "Texto legível na imagem, transcrito; vazio se não houver."
                ),
            },
            "densidade_texto": {
                "type": "string",
                "enum": DENSIDADES_TEXTO,
                "description": (
                    "QUANTO da tela é ocupado por texto escrito, somando "
                    "legendas queimadas, tarjas, títulos, slides e prints. "
                    "'nenhum' = não há texto; 'pouco' = uma marca d'água, um "
                    "placar ou uma linha discreta; 'moderado' = uma faixa de "
                    "texto que puxa o olho, tipo legenda grande ou manchete no "
                    "rodapé; 'muito' = o texto É o conteúdo do quadro (slide, "
                    "cartaz, print de post, parede de tuíte, thumbnail com "
                    "frase gigante). Julgue pela ÁREA ocupada, não pela "
                    "importância do que está escrito."
                ),
            },
            "texto_estatico": {
                "type": "boolean",
                "description": (
                    "true se o MESMO texto fica parado na tela nos frames "
                    "recebidos, sem mudar nem sair (cartaz, slide, print, "
                    "quadro congelado). false quando não há texto, quando ele "
                    "muda de um frame para o outro (legenda acompanhando a "
                    "fala, rolagem, digitação) ou quando aparece só de "
                    "passagem. Numa imagem estática (um frame só), responda "
                    "true sempre que houver texto ocupando a tela."
                ),
            },
            "cena_estatica": {
                "type": "boolean",
                "description": (
                    "true se os frames recebidos são praticamente o MESMO "
                    "quadro: câmera parada e nada de relevante se movendo "
                    "(foto parada com áudio, slide, quadro congelado, cartaz "
                    "filmado, tela sem atividade). false quando a cena muda de "
                    "um frame para o outro — pessoas ou objetos se deslocando, "
                    "câmera em movimento, corte para outro plano, interface "
                    "sendo operada. Numa imagem estática (um frame só), "
                    "responda true."
                ),
            },
            "pessoa_falando": {
                "type": "boolean",
                "description": (
                    "true se o quadro é DOMINADO por uma ou mais pessoas "
                    "falando para a câmera ou entre si, e é isso que o clipe "
                    "mostra: entrevista, depoimento, podcast, palestra, "
                    "coletiva, âncora, selfie-vídeo, reação gravada. false "
                    "quando ninguém fala, quando a fala é só narração em off "
                    "sobre imagens do fato, ou quando as pessoas aparecem "
                    "AGINDO (operando, andando, apresentando algo que se vê na "
                    "tela) em vez de só falando."
                ),
            },
            "legendas_queimadas": {
                "type": "boolean",
                "description": (
                    "true SOMENTE se o clipe traz LEGENDA/SUBTÍTULO QUEIMADO "
                    "— a TRANSCRIÇÃO DA FALA aparecendo na imagem, palavra por "
                    "palavra ou linha por linha, acompanhando quem fala e "
                    "MUDANDO de um frame para o outro. Inclui legenda de "
                    "acessibilidade, legenda de recorte de podcast e legenda "
                    "estilo karaokê. "
                    "NÃO É LEGENDA, e nesses casos responda false: MARCA "
                    "D'ÁGUA de qualquer tipo (logo de emissora, de veículo, de "
                    "app ou de autor, no canto ou no meio da tela), tarja e "
                    "manchete de telejornal, placar, relógio, rótulo de lugar "
                    "ou de pessoa, crédito, hashtag, texto de interface e "
                    "qualquer título PARADO. O teste é um só: aquilo transcreve "
                    "o que alguém está dizendo? Se não transcreve fala, não é "
                    "legenda — e marca d'água é material PERMITIDO no canal."
                ),
            },
            "frames_busto_falante": {
                "type": "array",
                "items": {"type": "boolean"},
                "description": (
                    "UM ITEM POR FRAME RECEBIDO, na mesma ordem: true se AQUELE "
                    "frame é dominado por pessoa(s) falando para a câmera ou "
                    "entre si (entrevista, âncora, coletiva, depoimento, "
                    "estúdio); false se ele mostra cena, ação, lugar, objeto, "
                    "gráfico ou tela. Julgue cada frame POR SI, sem uniformizar "
                    "o clipe: um vídeo que abre com o apresentador e mostra a "
                    "cena no meio tem itens diferentes. Numa imagem estática, "
                    "devolva um único item."
                ),
            },
        },
        "required": [
            "descricao",
            "tipo_material",
            "selo_de_emissora",
            "marca_visivel",
            "texto_na_tela",
            "densidade_texto",
            "texto_estatico",
            "cena_estatica",
            "pessoa_falando",
            "legendas_queimadas",
            "frames_busto_falante",
        ],
    },
}

PROMPT_DESCRICAO = """\
Você analisa uma mídia que pode entrar num vídeo jornalístico. Descreva o que
ela mostra e CLASSIFIQUE o material segundo o esquema pedido.

A classificação decide se a mídia pode ser usada, então seja literal: se o que
está na tela é uma matéria de telejornal (âncora ou repórter em enquadramento
de TV, tarja inferior de emissora, estrutura de VT), o tipo é "reportagem_tv" —
mesmo que a cena mostrada dentro da matéria seja interessante.

O TEXTO NA TELA também decide o uso, então meça-o com cuidado e sem
generosidade: "densidade_texto" é a ÁREA do quadro tomada por letras (não a
importância do que dizem), e "texto_estatico" é se o mesmo texto fica PARADO
nos frames que você recebeu. Print de post, slide, cartaz e quadro com frase
gigante são "muito" e estáticos; legenda que acompanha a fala muda de frame
para frame e não é estática.

O MOVIMENTO decide o uso do mesmo jeito. "cena_estatica" é se os frames são o
mesmo quadro: compare-os de verdade, e responda true quando o que muda entre
eles é irrelevante (um relógio, uma legenda) e o QUADRO é o mesmo.
"pessoa_falando" é se o clipe é alguém falando para a câmera ou entre si —
entrevista, podcast, coletiva, depoimento, âncora — e não uma cena em que
pessoas AGEM. Em "cena_estatica", na dúvida responda true: material parado é o
que este canal não usa.

"tipo_material" carrega o único veto de material que sobrou, então as duas
casas que vetam precisam ser literais. "gravacao_de_tela" é captura de tela ou
SCREENSHOT de qualquer interface — app, site, navegador, terminal, chat,
planilha, gráfico de mercado, demo de software — por mais que o assunto seja
exatamente o da notícia. "cartela_ou_manchete" é SLIDE, APRESENTAÇÃO, cartela
de texto ou print de manchete: o quadro é um texto escrito ou um bloco de
tópicos, animado ou parado. Se o clipe é uma dessas quatro coisas em qualquer
trecho relevante, é esse o tipo, mesmo que haja movimento.

O que NÃO é nenhum dos dois: animação, desenho, motion graphics sem texto,
render 3D, vídeo gerado por IA, gameplay e filmagem posta dentro de moldura,
mockup de celular ou template. Nada disso é vetado — classifique pelo que a
cena mostra ("cena_real" quando é o fato, "outro" quando não dá para dizer).

"legendas_queimadas" é só sobre TRANSCRIÇÃO DE FALA na imagem: a faixa que
acompanha o que a pessoa está dizendo e muda a cada frame. MARCA D'ÁGUA NÃO É
LEGENDA — logo de emissora, de veículo, de app ou de autor, no canto ou no meio
da tela, é material permitido e responde false. O mesmo vale para tarja,
manchete, placar, relógio, rótulo e título parado: nada disso transcreve fala.

"frames_busto_falante" é a MEDIDA que decide, e ela é POR FRAME: um item para
cada frame recebido, na ordem, julgando cada um por si. Não uniformize o clipe
— vídeo de veículo costuma abrir e fechar com o apresentador e mostrar a cena no
meio, e é essa diferença entre os frames que interessa aqui.

Responda somente com o JSON pedido.\
"""


def _reduzir(origem: Path, destino: Path, ss: float | None = None) -> Path | None:
    """JPEG reduzido para a visão; com `ss`, extrai o frame do vídeo nesse ponto."""
    comando = ["ffmpeg", "-y", "-loglevel", "error"]
    if ss is not None:
        comando += ["-ss", f"{ss:.2f}"]
    comando += [
        "-i", str(origem),
        "-frames:v", "1",
        "-vf", f"scale='min({LADO_VISAO},iw)':-2",
        str(destino),
    ]
    try:
        subprocess.run(comando, check=True, capture_output=True)
        return destino if destino.exists() else None
    except (subprocess.CalledProcessError, OSError):
        return None


def _data_uri(caminho: Path) -> str:
    dados = base64.b64encode(caminho.read_bytes()).decode()
    return f"data:image/jpeg;base64,{dados}"


def _fatias(dur: float, n: int = FRAMES_VIDEO) -> list[tuple[float, float, float]]:
    """(início, fim, meio) de `n` fatias iguais do vídeo.

    O frame sai do MEIO de cada fatia, nunca das pontas do vídeo: é o que impede
    a abertura e o encerramento — onde mora o apresentador — de valerem por um
    quarto da amostra, como valiam com os pontos fixos de 10% e 85%.
    """
    return [(dur * i / n, dur * (i + 1) / n, dur * (i + 0.5) / n) for i in range(n)]


def _imagens_da_midia(m: dict, pasta_tmp: Path) -> list[Path]:
    """Fotos viram um JPEG reduzido; vídeos, FRAMES_VIDEO frames espaçados."""
    caminho: Path = m["caminho"]
    if caminho.suffix != ".mp4":
        jpeg = _reduzir(caminho, pasta_tmp / f"{caminho.stem}.jpg")
        return [jpeg] if jpeg else []
    dur = m.get("dur_s") or 0
    pontos = (
        [meio for _, _, meio in _fatias(dur)]
        if dur
        else [float(i) for i in range(FRAMES_VIDEO)]
    )
    frames = []
    for i, ponto in enumerate(pontos):
        frame = _reduzir(caminho, pasta_tmp / f"{caminho.stem}_f{i}.jpg", ss=ponto)
        if frame:
            frames.append(frame)
    return frames


def _medir_frames(laudo: dict, n_frames: int, dur: float) -> None:
    """Anota no laudo a FRAÇÃO de busto falante e o melhor trecho do clipe.

    Escreve três campos:

    - ``fracao_falando``: quantos dos frames medidos são busto falante. É o que
      a auditoria passa a usar no lugar do booleano do clipe inteiro — um clipe
      que abre e fecha com o apresentador mas mostra a cena no miolo deixa de
      ser reprovado por causa das pontas.
    - ``inicio_util_s`` e ``dur_util_s``: a maior sequência CONTÍGUA de frames
      sem busto falante, convertida de volta para tempo. É o pedaço que a
      montagem deve pôr no ar; sem isso o clipe entra sempre do segundo zero,
      que num vídeo de veículo é justamente a abertura com o âncora.

    Laudo sem o array (modelo antigo, chamada malsucedida) fica sem os campos, e
    quem lê cai no comportamento anterior: a ausência da medida não é veredito.
    """
    marcas = laudo.get("frames_busto_falante")
    if not isinstance(marcas, list) or not marcas:
        return
    marcas = [bool(x) for x in marcas[:n_frames]]
    laudo["fracao_falando"] = sum(marcas) / len(marcas)
    if not dur:
        return

    # O trecho vai de CENTRO a CENTRO de fatia, não de borda a borda: o que foi
    # medido é o frame do meio, e a borda ainda pertence ao que veio antes. Com
    # as bordas, o clipe do FBI começaria em 14,1s e entraria no ar mostrando o
    # porta-voz — verificado extraindo o frame do vídeo montado.
    melhor_ini = melhor_fim = corrente_ini = None
    fatias = _fatias(dur, len(marcas))
    for i, falando in enumerate(marcas):
        if falando:
            corrente_ini = None
            continue
        if corrente_ini is None:
            corrente_ini = i
        ini, fim = fatias[corrente_ini][2], fatias[i][2]
        if melhor_ini is None or fim - ini > melhor_fim - melhor_ini:
            melhor_ini, melhor_fim = ini, fim
    if melhor_ini is not None:
        laudo["inicio_util_s"] = round(melhor_ini, 2)
        # Um bloco de uma fatia só tem centro único: a folga é meia fatia, o
        # quanto se pode afirmar a partir de um frame.
        laudo["dur_util_s"] = round(
            max(melhor_fim - melhor_ini, dur / len(marcas) / 2), 2
        )


def descrever_midias(cfg: Config, midias: list[dict]) -> dict[str, dict]:
    """Descreve e classifica cada mídia baixada com o GPT (visão).

    Devolve {str(caminho): {"descricao", "tipo_material", "selo_de_emissora",
    "marca_visivel", "texto_na_tela"}}. Mídia que falhar fica FORA do
    dicionário — e a auditoria reprova quem não tem laudo, porque usar material
    não verificado é exatamente o que esta camada existe para evitar.
    """
    if not midias:
        return {}
    cliente = OpenAI(api_key=cfg.openai_api_key)
    print(f"[midia-x] Descrevendo {len(midias)} mídias com o GPT (visão)...")

    descricoes: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        pasta_tmp = Path(tmp)
        for m in midias:
            imagens = _imagens_da_midia(m, pasta_tmp)
            if not imagens:
                continue
            contexto = ""
            if m["caminho"].suffix == ".mp4":
                contexto += (
                    f"\nAs imagens são {len(imagens)} frames, em ordem, de um "
                    f"vídeo de {m.get('dur_s') or '?'} segundos — descreva a "
                    "ação do começo ao fim."
                )
            if m.get("texto_post"):
                contexto += f"\nTexto do post de origem: \"{m['texto_post']}\""
            conteudo = [
                {"type": "text", "text": AVISO_DADOS_EXTERNOS},
                {"type": "text", "text": PROMPT_DESCRICAO + contexto},
            ] + [
                {"type": "image_url", "image_url": {"url": _data_uri(img)}}
                for img in imagens
            ]
            try:
                resposta = cliente.chat.completions.create(
                    model=cfg.text_model,
                    messages=[{"role": "user", "content": conteudo}],
                    response_format={
                        "type": "json_schema", "json_schema": ESQUEMA_DESCRICAO
                    },
                )
                laudo = json.loads(resposta.choices[0].message.content)
            except Exception as erro:
                print(f"[aviso] Descrição de {m['caminho'].name} falhou: {erro}")
                continue
            if (laudo.get("descricao") or "").strip():
                _medir_frames(laudo, len(imagens), m.get("dur_s") or 0)
                descricoes[str(m["caminho"])] = laudo
                marca = (
                    f" [selo: {laudo.get('marca_visivel') or 'emissora'}]"
                    if laudo.get("selo_de_emissora")
                    else ""
                )
                densidade = laudo.get("densidade_texto") or "?"
                texto = (
                    ""
                    if densidade in ("nenhum", "?")
                    else (
                        f" [texto: {densidade}"
                        + (", parado" if laudo.get("texto_estatico") else "")
                        + "]"
                    )
                )
                movimento = " [cena parada]" if laudo.get("cena_estatica") else ""
                if laudo.get("legendas_queimadas"):
                    movimento += " [legendado]"
                marcas = laudo.get("frames_busto_falante") or []
                if marcas:
                    # A fração vai para o log porque é ela que veta agora: sem o
                    # número na tela a decisão volta a ser inauditável, que foi
                    # como o booleano de 3 frames passou meses errando calado.
                    movimento += (
                        f" [falando em {sum(bool(x) for x in marcas)}/{len(marcas)}"
                        " frames]"
                    )
                    if laudo.get("dur_util_s"):
                        movimento += (
                            f" [trecho útil {laudo['inicio_util_s']:.0f}s"
                            f"+{laudo['dur_util_s']:.0f}s]"
                        )
                elif laudo.get("pessoa_falando"):
                    movimento += " [pessoa falando]"
                print(
                    f"[midia-x] {m['caminho'].name}: "
                    f"{laudo.get('tipo_material', '?')}{marca}{texto}{movimento}"
                )

    print(f"[midia-x] {len(descricoes)} mídias descritas")
    return descricoes
