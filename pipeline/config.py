"""Carrega a configuração do projeto a partir do arquivo .env."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    openai_api_key: str
    xai_api_key: str
    elevenlabs_api_key: str
    contas: list[str]
    video_largura: int = 1080
    video_altura: int = 1920
    text_model: str = "gpt-5.4-mini"
    search_model: str = "grok-4.3"
    voice_id: str = "czvzJwIVS2asEKnthV40"
    voice_id_usa: str = "POPWFdpTM8Mn2ZQEagyQ"
    tts_model: str = "eleven_v3"
    video_duracao: int = 60
    janela_horas: int = 24
    publico: str = "brasil"  # "brasil" ou "usa" (flag -usa no main.py)
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_refresh_token_usa: str = ""
    youtube_privacy: str = "public"  # public | unlisted | private
    youtube_category_id: str = "28"  # 28 = Science & Technology
    output_dir: Path = field(default_factory=lambda: RAIZ / "output")
    registro_path: Path = field(default_factory=lambda: RAIZ / "videos.txt")


def carregar_config() -> Config:
    load_dotenv(RAIZ / ".env")

    faltando = [
        nome
        for nome in ("OPENAI_API_KEY", "XAI_API_KEY", "ELEVENLABS_API_KEY")
        if not os.getenv(nome)
    ]
    if faltando:
        raise SystemExit(
            f"Variáveis ausentes no .env: {', '.join(faltando)}. "
            "Copie o .env.example para .env e preencha as chaves."
        )

    # X_ACCOUNTS é opcional: vazio = busca aberta pelas threads de tech/AI
    # mais discutidas do dia; preenchido = restringe às contas listadas.
    contas = [
        c.strip().lstrip("@")
        for c in os.getenv("X_ACCOUNTS", "").split(",")
        if c.strip()
    ]
    if len(contas) > 20:
        raise SystemExit("X_ACCOUNTS aceita no máximo 20 contas (limite da X Search).")

    cfg = Config(
        openai_api_key=os.environ["OPENAI_API_KEY"],
        xai_api_key=os.environ["XAI_API_KEY"],
        elevenlabs_api_key=os.environ["ELEVENLABS_API_KEY"],
        contas=contas,
        video_largura=int(os.getenv("VIDEO_LARGURA", "1080")),
        video_altura=int(os.getenv("VIDEO_ALTURA", "1920")),
        text_model=os.getenv("TEXT_MODEL", "gpt-5.4-mini"),
        search_model=os.getenv("SEARCH_MODEL", "grok-4.3"),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "czvzJwIVS2asEKnthV40"),
        voice_id_usa=os.getenv("ELEVENLABS_VOICE_ID_USA", "POPWFdpTM8Mn2ZQEagyQ"),
        tts_model=os.getenv("ELEVENLABS_MODEL", "eleven_v3"),
        video_duracao=int(os.getenv("VIDEO_DURACAO", "60")),
        janela_horas=int(os.getenv("JANELA_HORAS", "24")),
        youtube_client_id=os.getenv("YOUTUBE_CLIENT_ID", ""),
        youtube_client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        youtube_refresh_token=os.getenv("YOUTUBE_REFRESH_TOKEN", ""),
        youtube_refresh_token_usa=os.getenv("YOUTUBE_REFRESH_TOKEN_USA", ""),
        youtube_privacy=os.getenv("YOUTUBE_PRIVACY", "public"),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "28"),
    )

    # A duração final segue o áudio da narração; este valor orienta o
    # tamanho do roteiro gerado.
    if not 15 <= cfg.video_duracao <= 180:
        raise SystemExit("VIDEO_DURACAO deve estar entre 15 e 180 segundos.")

    cfg.output_dir.mkdir(exist_ok=True)
    return cfg
