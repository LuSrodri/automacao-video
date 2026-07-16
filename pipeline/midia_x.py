"""Download e descrição das mídias (fotos e vídeos) dos posts da trend.

Download via X API oficial v2 em modo pay-per-use (~US$ 0,005 por post/mídia
lida): um único GET /2/tweets com `expansions=attachments.media_keys` resolve
todos os posts da trend de uma vez. Fotos vêm por URL direta (pbs.twimg.com,
pedida em resolução original); vídeos vêm como variantes MP4, das quais
baixamos a de maior bitrate. Em qualquer falha da API, o pipeline segue só com
as imagens da busca web.

Descrição via GPT com visão sobre os arquivos baixados: fotos vão direto; de
vídeos o ffmpeg extrai alguns frames. As descrições orientam o planejador de
cortes (cortes.py) a casar cada mídia com o momento certo da narração.
"""

import base64
import re
import subprocess
import tempfile
from pathlib import Path

import requests
from openai import OpenAI

from .busca_imagens import _baixar as _baixar_imagem
from .config import Config
from .edicao import duracao_audio
from .x_client import obter_bearer

TWEETS_ENDPOINT = "https://api.x.com/2/tweets"

MAX_POSTS = 5  # posts consultados por vídeo (cada um custa ~US$ 0,005)
MAX_MIDIAS = 6  # mídias baixadas por vídeo (as primeiras encontradas)
MAX_VIDEO_BYTES = 60_000_000  # ~60 MB; vídeo maior que isso é descartado

PADRAO_ID_POST = re.compile(r"(?:x|twitter)\.com/[^/]+/status/(\d+)")


def _ids_dos_posts(urls: list[str]) -> list[str]:
    ids = [m.group(1) for u in urls if (m := PADRAO_ID_POST.search(u))]
    return list(dict.fromkeys(ids))[:MAX_POSTS]


def _url_foto_original(url: str) -> str:
    """Pede a foto na resolução original (name=orig) mantendo a query existente."""
    return f"{url}{'&' if '?' in url else '?'}name=orig"


def _melhor_variante(variantes: list[dict]) -> str | None:
    """URL do MP4 de maior bitrate (as demais variantes são HLS/baixa qualidade)."""
    mp4s = [
        v for v in variantes
        if v.get("content_type") == "video/mp4" and v.get("url")
    ]
    if not mp4s:
        return None
    return max(mp4s, key=lambda v: v.get("bit_rate") or 0)["url"]


def _baixar_foto(url: str, destino_sem_ext: Path) -> Path | None:
    # Reaproveita o fluxo de fotos da busca web (verificação de formato, piso
    # de tamanho e teto de resolução).
    return _baixar_imagem(_url_foto_original(url), destino_sem_ext)


def _baixar_video(url: str, destino: Path) -> Path | None:
    try:
        with requests.get(url, timeout=120, stream=True) as resp:
            resp.raise_for_status()
            tamanho = int(resp.headers.get("Content-Length") or 0)
            if tamanho > MAX_VIDEO_BYTES:
                print(f"[aviso] Vídeo de {url} grande demais ({tamanho} bytes), pulando")
                return None
            baixado = 0
            with destino.open("wb") as arquivo:
                for pedaco in resp.iter_content(chunk_size=1 << 16):
                    baixado += len(pedaco)
                    if baixado > MAX_VIDEO_BYTES:
                        print(f"[aviso] Vídeo de {url} passou do teto durante o download")
                        arquivo.close()
                        destino.unlink(missing_ok=True)
                        return None
                    arquivo.write(pedaco)
        return destino
    except requests.RequestException as erro:
        print(f"[aviso] Falha ao baixar vídeo {url}: {erro}")
        destino.unlink(missing_ok=True)
        return None


def baixar_midias_posts(cfg: Config, urls_posts: list[str], pasta: Path) -> list[dict]:
    """Baixa as mídias dos posts; devolve [{"caminho": Path, "trecho": ""}, ...].

    Compatível com o formato de `buscar_imagens` — o `main.py` mescla as duas
    listas. Vídeos saem como .mp4 e a montagem (edicao.py) os detecta pela
    extensão.

    Falhas de credencial/API ABORTAM a execução: a trend costuma ser escolhida
    justamente por ter vídeo/foto nos posts, e pular a etapa entregaria um
    vídeo sem o material que motivou a escolha. Posts sem mídia anexada não
    são erro — aí a lista sai vazia e o vídeo usa só as imagens da web.
    """
    ids = _ids_dos_posts(urls_posts)
    if not ids:
        return []

    if not (cfg.x_consumer_key and cfg.x_consumer_secret):
        raise SystemExit(
            "X_CONSUMER_KEY/X_CONSUMER_SECRET ausentes — sem eles não dá para "
            "baixar as mídias dos posts da trend; abortando."
        )
    token = obter_bearer(cfg)
    if token is None:
        raise SystemExit(
            "X API sem token — sem ele não dá para baixar as mídias dos posts "
            "da trend; abortando. Confira as credenciais no .env."
        )

    print(f"[midia-x] Consultando {len(ids)} posts da trend na X API...")
    try:
        resp = requests.get(
            TWEETS_ENDPOINT,
            params={
                "ids": ",".join(ids),
                "tweet.fields": "text",
                "expansions": "attachments.media_keys",
                "media.fields": (
                    "media_key,type,url,variants,preview_image_url,width,height"
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

    midias = (dados.get("includes") or {}).get("media") or []
    if not midias:
        print("[midia-x] Nenhuma mídia anexada nos posts consultados")
        return []

    # De qual post veio cada mídia e o texto do post (contexto para a descrição)
    dono_da_midia: dict[str, str] = {}
    texto_do_post: dict[str, str] = {}
    for post in dados.get("data") or []:
        texto_do_post[post.get("id", "")] = post.get("text", "")
        for chave in (post.get("attachments") or {}).get("media_keys") or []:
            dono_da_midia.setdefault(chave, post.get("id", ""))

    baixadas: list[dict] = []
    for k, m in enumerate(midias[:MAX_MIDIAS], 1):
        tipo = m.get("type")
        caminho = None
        if tipo == "photo" and m.get("url"):
            caminho = _baixar_foto(m["url"], pasta / f"midia_x_{k}")
        elif tipo in ("video", "animated_gif"):
            url_mp4 = _melhor_variante(m.get("variants") or [])
            if url_mp4:
                caminho = _baixar_video(url_mp4, pasta / f"midia_x_{k}.mp4")
        if caminho:
            dur_s = None
            if caminho.suffix == ".mp4":
                try:
                    dur_s = duracao_audio(caminho)  # ffprobe format=duration
                except (subprocess.CalledProcessError, ValueError, OSError):
                    dur_s = None
            post_id = dono_da_midia.get(m.get("media_key", ""), "")
            baixadas.append(
                {
                    "caminho": caminho,
                    "trecho": "",
                    "tipo": tipo,
                    "post_id": post_id,
                    "texto_post": texto_do_post.get(post_id, ""),
                    "dur_s": dur_s,
                }
            )
            print(f"[midia-x] {caminho.name} ({tipo})")

    if not baixadas:
        print("[midia-x] Nenhuma mídia dos posts pôde ser baixada")
    return baixadas


# ---- Descrição das mídias baixadas (GPT com visão) ----

LADO_VISAO = 768  # px; lado máximo das imagens enviadas ao GPT (custo de visão)
FRAMES_VIDEO = 3  # frames extraídos por vídeo (início, meio e fim)

PROMPT_DESCRICAO = """\
Descreva a mídia em 2 a 4 frases OBJETIVAS: o que aparece (pessoas, produtos,
telas, lugares), o que acontece e qualquer texto legível na imagem. A descrição
vai orientar um editor de vídeo que NÃO viu a mídia — seja concreto, sem
opinião, e responda somente com a descrição.\
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


def _imagens_da_midia(m: dict, pasta_tmp: Path) -> list[Path]:
    """Fotos viram um JPEG reduzido; vídeos, FRAMES_VIDEO frames espaçados."""
    caminho: Path = m["caminho"]
    if caminho.suffix != ".mp4":
        jpeg = _reduzir(caminho, pasta_tmp / f"{caminho.stem}.jpg")
        return [jpeg] if jpeg else []
    dur = m.get("dur_s") or 0
    pontos = (
        [dur * f for f in (0.1, 0.5, 0.85)][:FRAMES_VIDEO] if dur else [0.0, 1.0, 2.0]
    )
    frames = []
    for i, ponto in enumerate(pontos):
        frame = _reduzir(caminho, pasta_tmp / f"{caminho.stem}_f{i}.jpg", ss=ponto)
        if frame:
            frames.append(frame)
    return frames


def descrever_midias(cfg: Config, midias: list[dict]) -> dict[str, str]:
    """Descreve cada mídia baixada com o GPT (visão); {str(caminho): descrição}.

    Etapa opcional: qualquer falha só pula a mídia, nunca derruba o pipeline.
    """
    if not midias:
        return {}
    cliente = OpenAI(api_key=cfg.openai_api_key)
    print(f"[midia-x] Descrevendo {len(midias)} mídias com o GPT (visão)...")

    descricoes: dict[str, str] = {}
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
            conteudo = [{"type": "text", "text": PROMPT_DESCRICAO + contexto}] + [
                {"type": "image_url", "image_url": {"url": _data_uri(img)}}
                for img in imagens
            ]
            try:
                resposta = cliente.chat.completions.create(
                    model=cfg.text_model,
                    messages=[{"role": "user", "content": conteudo}],
                )
                descricao = (resposta.choices[0].message.content or "").strip()
            except Exception as erro:
                print(f"[aviso] Descrição de {m['caminho'].name} falhou: {erro}")
                continue
            if descricao:
                descricoes[str(m["caminho"])] = descricao

    print(f"[midia-x] {len(descricoes)} mídias descritas")
    return descricoes
