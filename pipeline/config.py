"""Carrega a configuração do projeto a partir do arquivo .env."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent

# Contas fixas do X que alimentam a coleta (geopolítica, inteligência, IA e
# tech). X_ACCOUNTS no .env, quando preenchido, substitui esta lista.
CONTAS_PADRAO = [
    "elonmusk", "CNNBrasil", "brasilparalelo", "exercitooficial", "SpaceX",
    "revistaoeste", "EmbaixadaEUA", "OpenAI", "sama", "huggingface",
    "StanfordAILab", "OpenAIDevs", "DarioAmodei", "AnthropicAI", "rakyll",
    "GoogleAI", "gdb", "hardmaru", "WhiteHouse", "SamPancher", "business",
    "Osint613", "Kalshi", "dfolloni", "bcherny", "trq212", "addyosmani",
    "claudeai", "noahzweben", "ClaudeDevs", "googlegemma", "arena",
    "cursor_ai", "satyanadella", "_cyberhusky", "lucasjvds", "unusual_whales",
    "WatcherGuru", "kimmonismus", "sentdefender", "Faytuks", "demishassabis",
    "alexandr_wang", "mustafasuleyman", "SecRubio", "intheworldofai",
    "chetaslua", "Sam_Acqua", "BancoCentralBR", "FBI",
]


@dataclass
class Config:
    openai_api_key: str
    elevenlabs_api_key: str
    firecrawl_api_key: str
    contas: list[str]
    x_consumer_key: str  # X API oficial: coleta dos posts + mídias
    x_consumer_secret: str
    x_max_posts: int = 60  # teto de posts lidos por execução (leitura é paga)
    video_largura: int = 1080
    video_altura: int = 1920
    text_model: str = "gpt-5.6-luna"
    voice_id: str = "czvzJwIVS2asEKnthV40"
    voice_id_usa: str = "POPWFdpTM8Mn2ZQEagyQ"
    tts_model: str = "eleven_v3"
    video_duracao: int = 35
    janela_horas: int = 24
    num_trends: int = 10  # quantas trends do X coletar para escolher a do vídeo
    num_noticias: int = 6  # quantas notícias buscar (Firecrawl news) p/ enriquecer
    publico: str = "brasil"  # "brasil" ou "usa" (flag -usa no main.py)
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    youtube_refresh_token_usa: str = ""
    youtube_handle: str = ""  # @usuário exibido no topo do vídeo (público br)
    youtube_handle_usa: str = ""  # @usuário do canal inglês (-usa)
    youtube_privacy: str = "public"  # public | unlisted | private
    youtube_category_id: str = "28"  # 28 = Science & Technology
    output_dir: Path = field(default_factory=lambda: RAIZ / "output")
    registro_path: Path = field(default_factory=lambda: RAIZ / "videos.txt")

    @property
    def handle_do_publico(self) -> str:
        """@usuário do canal certo (inglês quando publico == 'usa'), normalizado.

        Devolve string vazia quando não configurado; nesse caso o vídeo é
        montado sem o nome de usuário sob o logo.
        """
        bruto = (self.youtube_handle_usa if self.publico == "usa"
                 else self.youtube_handle).strip()
        if not bruto:
            return ""
        return bruto if bruto.startswith("@") else f"@{bruto}"


def carregar_config() -> Config:
    load_dotenv(RAIZ / ".env")

    faltando = [
        nome
        for nome in (
            "OPENAI_API_KEY",
            "ELEVENLABS_API_KEY",
            "FIRECRAWL_API_KEY",
            "X_CONSUMER_KEY",
            "X_CONSUMER_SECRET",
        )
        if not os.getenv(nome)
    ]
    if faltando:
        raise SystemExit(
            f"Variáveis ausentes no .env: {', '.join(faltando)}. "
            "Copie o .env.example para .env e preencha as chaves."
        )

    # X_ACCOUNTS é opcional: vazio = usa a lista fixa CONTAS_PADRAO;
    # preenchido = usa somente as contas listadas no .env.
    contas = [
        c.strip().lstrip("@")
        for c in os.getenv("X_ACCOUNTS", "").split(",")
        if c.strip()
    ] or list(CONTAS_PADRAO)

    cfg = Config(
        openai_api_key=os.environ["OPENAI_API_KEY"],
        elevenlabs_api_key=os.environ["ELEVENLABS_API_KEY"],
        firecrawl_api_key=os.environ["FIRECRAWL_API_KEY"],
        contas=contas,
        x_consumer_key=os.environ["X_CONSUMER_KEY"],
        x_consumer_secret=os.environ["X_CONSUMER_SECRET"],
        x_max_posts=int(os.getenv("X_MAX_POSTS", "60")),
        video_largura=int(os.getenv("VIDEO_LARGURA", "1080")),
        video_altura=int(os.getenv("VIDEO_ALTURA", "1920")),
        text_model=os.getenv("TEXT_MODEL", "gpt-5.6-luna"),
        voice_id=os.getenv("ELEVENLABS_VOICE_ID", "czvzJwIVS2asEKnthV40"),
        voice_id_usa=os.getenv("ELEVENLABS_VOICE_ID_USA", "POPWFdpTM8Mn2ZQEagyQ"),
        tts_model=os.getenv("ELEVENLABS_MODEL", "eleven_v3"),
        video_duracao=int(os.getenv("VIDEO_DURACAO", "35")),
        janela_horas=int(os.getenv("JANELA_HORAS", "24")),
        num_trends=int(os.getenv("NUM_TRENDS", "10")),
        num_noticias=int(os.getenv("NUM_NOTICIAS", "6")),
        youtube_client_id=os.getenv("YOUTUBE_CLIENT_ID", ""),
        youtube_client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", ""),
        youtube_refresh_token=os.getenv("YOUTUBE_REFRESH_TOKEN", ""),
        youtube_refresh_token_usa=os.getenv("YOUTUBE_REFRESH_TOKEN_USA", ""),
        youtube_handle=os.getenv("YOUTUBE_HANDLE", ""),
        youtube_handle_usa=os.getenv("YOUTUBE_HANDLE_USA", ""),
        youtube_privacy=os.getenv("YOUTUBE_PRIVACY", "public"),
        youtube_category_id=os.getenv("YOUTUBE_CATEGORY_ID", "28"),
    )

    # A duração final segue o áudio da narração; este valor orienta o
    # tamanho do roteiro gerado.
    if not 15 <= cfg.video_duracao <= 180:
        raise SystemExit("VIDEO_DURACAO deve estar entre 15 e 180 segundos.")

    cfg.output_dir.mkdir(exist_ok=True)
    return cfg
