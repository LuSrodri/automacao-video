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
    contas: list[str]
    text_model: str = "gpt-5.4-mini"
    search_model: str = "grok-4.3"
    image_model: str = "gpt-image-1.5"
    image_quality: str = "low"
    video_model: str = "grok-imagine-video-1.5-preview"
    video_duracao: int = 20
    video_resolucao: str = "480p"
    video_aspect_ratio: str = "9:16"
    janela_horas: int = 24
    clipe_path: Path = field(default_factory=lambda: RAIZ / "clipe.png")
    output_dir: Path = field(default_factory=lambda: RAIZ / "output")
    registro_path: Path = field(default_factory=lambda: RAIZ / "videos.txt")


def carregar_config() -> Config:
    load_dotenv(RAIZ / ".env")

    faltando = [
        nome
        for nome in ("OPENAI_API_KEY", "XAI_API_KEY")
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
        contas=contas,
        text_model=os.getenv("TEXT_MODEL", "gpt-5.4-mini"),
        search_model=os.getenv("SEARCH_MODEL", "grok-4.3"),
        image_model=os.getenv("IMAGE_MODEL", "gpt-image-1.5"),
        image_quality=os.getenv("IMAGE_QUALITY", "low"),
        video_model=os.getenv("VIDEO_MODEL", "grok-imagine-video-1.5-preview"),
        video_duracao=int(os.getenv("VIDEO_DURACAO", "20")),
        video_resolucao=os.getenv("VIDEO_RESOLUCAO", "480p"),
        video_aspect_ratio=os.getenv("VIDEO_ASPECT_RATIO", "9:16"),
        janela_horas=int(os.getenv("JANELA_HORAS", "24")),
    )

    # Durações acima de 10s são geradas em segmentos de até 10s, em paralelo,
    # e concatenadas com ffmpeg. O teto de 25s é só um limite de custo.
    if not 1 <= cfg.video_duracao <= 25:
        raise SystemExit("VIDEO_DURACAO deve estar entre 1 e 25 segundos.")
    if not cfg.clipe_path.exists():
        raise SystemExit(
            f"Imagem base não encontrada: {cfg.clipe_path}. "
            "Coloque o arquivo clipe.png na raiz do projeto."
        )

    cfg.output_dir.mkdir(exist_ok=True)
    return cfg
