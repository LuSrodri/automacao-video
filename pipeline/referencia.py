"""Dossiê dos vídeos campeões: o que eles DIZEM e o que a capa deles MOSTRA.

Até 2026-08-22 a régua de audiência era só numérica. O modelo recebia título,
views e retenção dos campeões e a instrução de imitar o ASSUNTO deles — e era
só isso que ele tinha: uma lista de títulos. Tudo que fez aqueles vídeos
segurarem quem abriu (o que a capa promete, que palavras a narração usa, como
o vídeo começa a falar) ficava fora do prompt, porque nunca tinha sido lido.

Este módulo lê. Para cada campeão da lista (ver ``_lista_estrita`` em
youtube.py) ele pega a LEGENDA publicada e a CAPA do vídeo, e devolve isso
anexado ao próprio campeão. Quem consome é o prompt de SELEÇÃO da trend e o
prompt do ROTEIRO (escritor.py), os dois lados do Short.

SEM BAIXAR O VÍDEO (decisão do usuário em 2026-08-22, depois da medição). O
desenho anterior baixava o mp4 com o yt-dlp para tirar 20 frames e transcrever
o áudio, e ele tinha dois problemas medidos: o YouTube respondeu "Sign in to
confirm you're not a bot" já num IP residencial (no IP de datacenter do Render
seria pior, e dos sete player clients só o `android` escapou), e 20 imagens por
campeão vezes 50 campeões vezes 12 execuções por dia era, de longe, a etapa
mais cara do pipeline. Legenda e capa vêm da Data API com o token que o
pipeline já tem, em duas requisições baratas, e trazem o essencial: o que foi
DITO e o que foi PROMETIDO na imagem. O que se perde é a leitura do miolo
visual do vídeo.

SÓ NO FORMATO CURTO, nos dois canais (pedido do usuário). O formato longo
segue com a régua numérica de antes — o molde dele não são os Shorts.

NADA É PERSISTIDO (decisão do usuário em 2026-08-22): os vídeos do canal e as
métricas mudam a cada execução do cron, então o dossiê é montado do zero,
usado, e some junto com o diretório temporário.

FALHA ABERTA, vídeo a vídeo. Legenda que não existe, capa que não baixa, visão
que erra — cada um desses encolhe UM dossiê e deixa os outros passarem; o
campeão sem dossiê continua na lista com título, views e engajamento, que é
exatamente o que ele tinha antes deste módulo existir. O que não pode
acontecer é a leitura de referência derrubar uma execução inteira: ela é
enriquecimento, não pré-requisito.
"""

import json
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, Config
from .midia_x import _data_uri, _reduzir
from .youtube import (
    CAPTIONS_URL,
    _refresh_token_do_publico,
    _renovar_access_token,
)

# Quantos dossiês montar em paralelo. Cada um é rede quase o tempo todo (duas
# requisições à Data API e uma chamada de visão), então a concorrência paga.
DOSSIES_PARALELOS = int(os.getenv("DOSSIES_PARALELOS", "8") or 8)

# Teto de campeões que ganham dossiê. A lista já vem cortada em
# LIMITE_REFERENCIA (50); este teto é só do enriquecimento, para o caso de
# querer barateá-lo sem mexer no tamanho da lista que vai ao prompt. 0 desliga.
# Os escolhidos são os primeiros, e a lista já vem do melhor para o pior.
DOSSIE_MAX_VIDEOS = int(os.getenv("DOSSIE_MAX_VIDEOS", "0") or 0)

ESQUEMA_VISUAL = {
    "name": "leitura_da_capa",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cena": {
                "type": "string",
                "description": (
                    "O que a imagem mostra: pessoa, objeto, lugar, gráfico. "
                    "Uma frase, concreta."
                ),
            },
            "texto": {
                "type": "string",
                "description": (
                    "O texto escrito na capa, transcrito. String vazia quando "
                    "não há texto nenhum."
                ),
            },
            "composicao": {
                "type": "string",
                "description": (
                    "Como a capa está montada: close de rosto, montagem de "
                    "duas imagens, print de tela, número gigante, seta."
                ),
            },
        },
        "required": ["cena", "texto", "composicao"],
    },
}

PROMPT_VISUAL = """\
Esta é a CAPA (thumbnail) de um vídeo CURTO que já foi publicado e que segurou
bem a audiência: quem abriu continuou assistindo em vez de deslizar para o
próximo.

Descreva o que se vê, de forma concreta e factual, para que a capa de outro
vídeo possa ser montada no mesmo padrão. Não julgue qualidade, não elogie e
não tente explicar POR QUE o vídeo funcionou — diga apenas o que está na
imagem, e transcreva exatamente o texto escrito nela.

Responda somente com o JSON pedido.\
"""


def _limpar_legenda(bruto: str) -> str:
    """Texto corrido a partir de uma legenda SRT/VTT.

    Fora numeração de cue, marcas de tempo, tags de posicionamento e as linhas
    repetidas que o ASR do YouTube produz ao rolar a legenda na tela — sem essa
    deduplicação a transcrição sai com cada frase escrita duas ou três vezes, e
    o prompt passa a mostrar um vídeo que fala repetido.
    """
    linhas = []
    for linha in (bruto or "").splitlines():
        limpa = re.sub(r"<[^>]+>", "", linha).strip()
        if (
            not limpa
            or limpa.isdigit()
            or "-->" in limpa
            or limpa.upper().startswith(("WEBVTT", "KIND:", "LANGUAGE:"))
        ):
            continue
        if not linhas or linhas[-1] != limpa:
            linhas.append(limpa)
    return " ".join(linhas).strip()


def _legendas_da_api(video_id: str, token: str) -> str:
    """Narração do vídeo pela legenda publicada. "" quando não dá.

    O canal é nosso, o token já tem o escopo `youtube.force-ssl`, e
    `captions.download` é liberado para o dono do vídeo inclusive na faixa
    gerada automaticamente (ASR). É por isso que este caminho substituiu o
    download + STT: mesma informação, duas requisições, sem checagem de bot.

    Prefere a legenda humana à do ASR quando as duas existem: a nossa é a
    transcrição exata do roteiro que foi narrado.
    """
    try:
        lista = requests.get(
            CAPTIONS_URL,
            params={"part": "snippet", "videoId": video_id},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if lista.status_code != 200:
            return ""
        faixas = lista.json().get("items", [])
        if not faixas:
            return ""
        faixas.sort(
            key=lambda f: f.get("snippet", {}).get("trackKind", "") == "ASR"
        )
        conteudo = requests.get(
            f"{CAPTIONS_URL}/{faixas[0]['id']}",
            params={"tfmt": "srt"},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        if conteudo.status_code != 200:
            return ""
        return _limpar_legenda(conteudo.text)
    except Exception as erro:  # noqa: BLE001 — ver docstring do módulo
        print(f"[referencia] legendas de {video_id} falharam: {erro}")
        return ""


def _baixar_capa(url: str, destino: Path) -> Path | None:
    """Baixa a capa e a reduz para o tamanho que a visão usa. None quando não dá.

    A capa vem do i.ytimg.com, que é servidor de imagem estática e não passa
    pela checagem de bot do player — foi justamente ela que derrubou o download
    do vídeo. A redução reaproveita `_reduzir` de midia_x, o mesmo caminho de
    ffmpeg que o resto do pipeline usa para preparar imagem para o GPT.
    """
    if not url:
        return None
    try:
        resposta = requests.get(url, timeout=30)
        if resposta.status_code != 200 or not resposta.content:
            return None
        bruta = destino.with_name(destino.stem + "_bruta.jpg")
        bruta.write_bytes(resposta.content)
    except Exception as erro:  # noqa: BLE001 — ver docstring do módulo
        print(f"[referencia] capa não baixou: {erro}")
        return None
    reduzida = _reduzir(bruta, destino)
    bruta.unlink(missing_ok=True)
    return reduzida


def _ler_capa(cliente: OpenAI, cfg: Config, imagem: Path) -> dict:
    """Laudo da capa. {} quando não dá."""
    conteudo = [
        {"type": "text", "text": AVISO_DADOS_EXTERNOS},
        {"type": "text", "text": PROMPT_VISUAL},
        {"type": "image_url", "image_url": {"url": _data_uri(imagem)}},
    ]
    try:
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[{"role": "user", "content": conteudo}],
            response_format={"type": "json_schema", "json_schema": ESQUEMA_VISUAL},
        )
        return json.loads(resposta.choices[0].message.content)
    except Exception as erro:  # noqa: BLE001 — ver docstring do módulo
        print(f"[referencia] leitura da capa falhou: {erro}")
        return {}


def _dossie_de(cfg: Config, campeao: dict, raiz: Path, token: str) -> None:
    """Anexa legenda e leitura da capa a UM campeão, no lugar."""
    video_id = campeao.get("video_id") or ""
    if not video_id:
        return
    pasta = raiz / video_id
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        if token:
            campeao["transcricao"] = _legendas_da_api(video_id, token)
        capa = _baixar_capa(
            campeao.get("thumbnail", ""), pasta / f"{video_id}.jpg"
        )
        if capa:
            campeao["visual"] = _ler_capa(
                OpenAI(api_key=cfg.openai_api_key), cfg, capa
            )
        palavras = len((campeao.get("transcricao") or "").split())
        print(
            f"[referencia] {video_id}: {palavras} palavras de legenda, capa "
            f"{'lida' if campeao.get('visual') else 'ausente'} — "
            f"{campeao.get('titulo', '')[:50]}"
        )
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def montar_dossies(cfg: Config, campeoes: list[dict]) -> list[dict]:
    """Enriquece os campeões com legenda e leitura da capa, NO LUGAR.

    Devolve a mesma lista recebida (mutada), para quem preferir encadear. Cada
    campeão enriquecido ganha ``transcricao`` e ``visual``; quem falhou fica sem
    esses campos e o prompt simplesmente não os mostra (ver
    ``_resumo_campeoes`` em escritor.py).

    Chamada só no formato curto — quem decide isso é ``main.py``, que é onde o
    formato já está resolvido.
    """
    if not campeoes:
        return campeoes
    alvos = campeoes[:DOSSIE_MAX_VIDEOS] if DOSSIE_MAX_VIDEOS > 0 else campeoes
    print(
        f"[referencia] Montando dossiê de {len(alvos)} campeão(ões): legenda "
        "publicada e capa de cada um."
    )
    # Um access token para todos: é ele que autoriza `captions.download`. Sem
    # token o dossiê fica só com a capa, que não exige autenticação.
    token = ""
    try:
        refresh = _refresh_token_do_publico(cfg)
        if refresh:
            token = _renovar_access_token(cfg, refresh)
    except Exception as erro:  # noqa: BLE001 — enriquecimento, não requisito
        print(f"[referencia] sem token para as legendas ({erro}).")

    with tempfile.TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        with ThreadPoolExecutor(max_workers=DOSSIES_PARALELOS) as executor:
            list(executor.map(lambda c: _dossie_de(cfg, c, raiz, token), alvos))

    com_texto = sum(1 for c in alvos if (c.get("transcricao") or "").strip())
    com_capa = sum(1 for c in alvos if c.get("visual"))
    print(
        f"[referencia] dossiê pronto: {com_texto} com legenda e {com_capa} com "
        f"leitura de capa, de {len(alvos)}."
    )
    if not com_texto and alvos:
        print(
            "[referencia] aviso: nenhuma legenda voltou. Se isso se repetir, "
            "confira o escopo youtube.force-ssl do refresh token — a seleção "
            "segue com título, métricas e capa."
        )
    return campeoes
