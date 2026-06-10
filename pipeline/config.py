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
    videos_fundo: list[Path]
    text_model: str = "gpt-5.4-mini"
    search_model: str = "grok-4.3"
    voice_id: str = "czvzJwIVS2asEKnthV40"
    tts_model: str = "eleven_v3"
    video_duracao: int = 60
    janela_horas: int = 24
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

    fundo_glob = os.getenv("FUNDO_GLOB", "av paulista*.mp4")
    videos_fundo = sorted(RAIZ.glob(fundo_glob))
    if not videos_fundo:
        raise SystemExit(
            f"Nenhum vídeo de fundo encontrado com o padrão '{fundo_glob}' "
            "na raiz do projeto."
        )

    cfg = Config(
        openai_api_key=os.environ["OPENAI_API_KEY"],
        xai_api_key=os.environ["XAI_API_KEY"],
        elevenlabs_api_key=os.environ["ELEVENLABS_API_KEY"],
        contas=contas,
        videos_fundo=videos_fundo,
        text_model=os.getenv("TEXT_MODEL", "gpt-5.4-mini"),
        search_model=os.getenv("SEARCH_MODEL", "grok-4.3"),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "czvzJwIVS2asEKnthV40"),
        tts_model=os.getenv("ELEVENLABS_MODEL", "eleven_v3"),
        video_duracao=int(os.getenv("VIDEO_DURACAO", "60")),
        janela_horas=int(os.getenv("JANELA_HORAS", "24")),
    )

    # A duração final segue o áudio da narração; este valor orienta o
    # tamanho do roteiro gerado.
    if not 15 <= cfg.video_duracao <= 180:
        raise SystemExit("VIDEO_DURACAO deve estar entre 15 e 180 segundos.")

    cfg.output_dir.mkdir(exist_ok=True)
    return cfg
