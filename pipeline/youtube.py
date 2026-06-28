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
from pathlib import Path

import requests

from .config import RAIZ, Config

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
    ]
)
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"
COMMENT_THREADS_URL = "https://www.googleapis.com/youtube/v3/commentThreads"
ENV_PATH = RAIZ / ".env"

# Comentário "fixado" postado automaticamente só no canal US. A YouTube Data API
# permite postar o comentário como dono do canal, mas NÃO expõe endpoint para
# fixá-lo — a fixação, se desejada, é manual no YouTube Studio. Os links ficam na
# bio do canal, então os textos não trazem URLs (comentário com link costuma ser
# segurado/filtrado pelo YouTube).
COMENTARIO_JOBS = (
    "Get paid to train AI working fully remote. Turing hires AI trainers "
    "(coding skills required) — make money from anywhere in the world. "
    "Apply now via the link in our bio!"
)
COMENTARIO_PADRAO = (
    "Power your AI agents with clean web data. Use Firecrawl. "
    "The complete toolkit to search, scrape, and interact with the web at scale. "
    "Try it out via the link in our bio!"
)


def _texto_comentario(titulo: str, descricao: str) -> str:
    """Escolhe o comentário pelo conteúdo: tema de 'job(s)' usa o da Turing.

    Procura a palavra 'job' ou 'jobs' (limites de palavra, sem diferenciar
    maiúsculas) no título e na descrição; havendo menção, devolve o convite da
    Turing, senão o texto padrão do Firecrawl.
    """
    texto = f"{titulo}\n{descricao}".lower()
    if re.search(r"\bjobs?\b", texto):
        return COMENTARIO_JOBS
    return COMENTARIO_PADRAO


def _postar_comentario(cfg: Config, token: str, video_id: str, titulo: str, descricao: str) -> None:
    """Posta o comentário do dono no vídeo (apenas canal US). Não fixa.

    Falhas são apenas avisadas: o vídeo já foi publicado e um comentário ausente
    não justifica derrubar o fluxo.
    """
    if cfg.publico != "usa":
        return

    texto = _texto_comentario(titulo, descricao)
    try:
        resp = requests.post(
            COMMENT_THREADS_URL,
            params={"part": "snippet"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            data=json.dumps(
                {
                    "snippet": {
                        "videoId": video_id,
                        "topLevelComment": {"snippet": {"textOriginal": texto}},
                    }
                }
            ).encode("utf-8"),
            timeout=60,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"{resp.status_code}: {resp.text[:300]}")
        print(f"[youtube] Comentário postado no vídeo {video_id} (fixe manualmente no Studio).")
    except Exception as erro:  # noqa: BLE001 — comentário opcional não derruba o fluxo
        print(f"[youtube] Falha ao postar o comentário (ignorada): {erro}")


def _atualizar_env(chave: str, valor: str) -> None:
    """Cria ou atualiza ``chave=valor`` no arquivo ``.env``."""
    linhas = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    nova = f"{chave}={valor}"
    for i, linha in enumerate(linhas):
        if linha.strip().startswith(f"{chave}="):
            linhas[i] = nova
            break
    else:
        if linhas and linhas[-1].strip():
            linhas.append("")
        linhas.append(nova)
    ENV_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")


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


def ultimos_publicados(cfg: Config, n: int = 9) -> list[dict]:
    """Últimos `n` vídeos publicados no canal selecionado (BR ou USA).

    Lê direto da YouTube Data API o canal correspondente ao refresh token de
    ``cfg.publico``, devolvendo os vídeos do mais recente para o mais antigo.
    Cada item traz ``titulo``, ``descricao`` e ``data`` (YYYY-MM-DD). Serve
    para o roteirista evitar repetir temas recém-publicados. Em qualquer falha
    (credenciais ausentes, API indisponível), devolve lista vazia sem derrubar
    o fluxo — o render não depende de nenhum estado local.
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        return []

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

        lista = requests.get(
            PLAYLIST_ITEMS_URL,
            params={"part": "snippet", "playlistId": uploads, "maxResults": n},
            headers=headers,
            timeout=60,
        )
        if lista.status_code != 200:
            raise RuntimeError(f"{lista.status_code}: {lista.text[:300]}")

        videos = []
        for item in lista.json().get("items", []):
            snippet = item.get("snippet", {})
            videos.append(
                {
                    "titulo": snippet.get("title", ""),
                    "descricao": snippet.get("description", ""),
                    "data": snippet.get("publishedAt", "")[:10],
                }
            )
        print(f"[youtube] {len(videos)} vídeos recentes do canal carregados.")
        return videos
    except Exception as erro:  # noqa: BLE001 — leitura opcional não derruba o fluxo
        print(f"[youtube] Não foi possível ler os últimos vídeos (ignorado): {erro}")
        return []


def publicar(
    cfg: Config,
    video: Path,
    titulo: str,
    descricao: str,
    tags: list[str] | None = None,
) -> str | None:
    """Publica o vídeo no YouTube e devolve a URL, ou ``None`` se pulou.

    Erros de upload são apenas avisados (não derrubam a execução): o vídeo
    já está salvo em ``output/`` e registrado em ``videos.txt``.
    """
    refresh = _refresh_token_do_publico(cfg)
    if not (cfg.youtube_client_id and cfg.youtube_client_secret and refresh):
        canal = "inglês (-usa)" if cfg.publico == "usa" else "português"
        flag = "--auth-youtube-usa" if cfg.publico == "usa" else "--auth-youtube"
        print(
            f"[youtube] Credenciais do canal {canal} ausentes; pulando publicação. "
            f"Rode 'python main.py {flag}' para autorizar."
        )
        return None

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
        _postar_comentario(cfg, token, video_id, titulo, descricao)
        return url
    except Exception as erro:  # noqa: BLE001 — falha de upload não derruba o fluxo
        print(f"[youtube] Falha na publicação (ignorada): {erro}")
        return None


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

    _atualizar_env(var_token, refresh)
    os.environ[var_token] = refresh
    print(
        f"[youtube] Refresh token de longa duração do canal {canal} salvo em "
        f"{var_token} no .env. Tudo pronto!"
    )
