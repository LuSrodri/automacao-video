"""Thumbnail do vídeo longo: um quadro real do vídeo + texto curto e assertivo.

A capa que o YouTube escolhe sozinho é um quadro qualquer — costuma cair num
frame borrado da transição ou no meio de um corte. Aqui a capa é montada de
propósito: um quadro do vídeo já pronto (portanto com a sala e a TV, coerente
com o que a pessoa vai ver), escurecido, com uma frase de 2 a 5 palavras em
Archivo Black ocupando a base.

O texto vem do GPT a partir do título e da narração, com uma regra dura: ele
tem que dizer o FATO, não provocar. "TRUMP PAUSA ATAQUES" chama mais atenção do
que "VOCÊ NÃO VAI ACREDITAR" e não queima a confiança de quem clica.

Falha aqui NÃO aborta: o vídeo já está montado e publicar sem capa customizada
é muito melhor do que não publicar.
"""

import json
import textwrap
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from .config import AVISO_DADOS_EXTERNOS, RAIZ, Config

FONTE = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"

# O YouTube aceita até 2 MB e recomenda 1280x720.
LARGURA, ALTURA = 1280, 720
MAX_BYTES = 2_000_000

MAX_PALAVRAS = 5
MAX_CARACTERES = 34  # acima disso a fonte encolhe demais para ler no celular

ESCURECER = 0.45  # brilho do quadro sob o texto (1.0 = original)
TEXTO_FRAC = 0.115  # altura da fonte como fração da altura da capa
MARGEM_FRAC = 0.055
ENTRELINHA = 1.12
TARJA_ALFA = 150  # tarja escura atrás do bloco de texto

ESQUEMA = {
    "name": "texto_da_thumbnail",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "texto": {
                "type": "string",
                "description": (
                    f"2 a {MAX_PALAVRAS} palavras, MAIÚSCULAS, dizendo o fato."
                ),
            }
        },
        "required": ["texto"],
    },
}

INSTRUCOES = f"""\
Você escreve o texto da CAPA (thumbnail) de um vídeo de notícias.

Devolva de 2 a {MAX_PALAVRAS} palavras, no máximo {MAX_CARACTERES} caracteres,
em MAIÚSCULAS, no MESMO IDIOMA do título que receber.

O texto tem que dizer O FATO, de forma que alguém que não conhece o assunto
entenda o que aconteceu só de bater o olho. Nome próprio conhecido ajuda, e
número concreto ajuda mais ainda.

NÃO use: pergunta, reticências, "veja", "urgente", "chocante", "você não vai
acreditar", nem qualquer promessa que a capa não cumpra. Curiosidade fabricada
traz clique e perde a audiência no primeiro segundo — o que retém é o fato.

Exemplos do que funciona: "TRUMP PAUSA ATAQUES AO IRÃ", "PETRÓLEO CAI 11%",
"APPLE PASSA A NVIDIA".
Exemplos do que NÃO funciona: "O QUE NINGUÉM TE CONTOU", "ISSO MUDA TUDO",
"ATENÇÃO: URGENTE".

Responda somente com o JSON pedido.\
"""


def _texto_da_capa(cfg: Config, titulo: str, narracao: str) -> str:
    """Frase curta para a capa; cai no título quando o GPT falha."""
    reserva = " ".join(titulo.split()[:MAX_PALAVRAS]).upper()
    try:
        cliente = OpenAI(api_key=cfg.openai_api_key)
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=[
                {"role": "system", "content": INSTRUCOES},
                {
                    "role": "user",
                    "content": (
                        f"{AVISO_DADOS_EXTERNOS}\n\nTÍTULO: {titulo}\n\n"
                        f"NARRAÇÃO:\n{narracao}"
                    ),
                },
            ],
            response_format={"type": "json_schema", "json_schema": ESQUEMA},
        )
        texto = json.loads(resposta.choices[0].message.content)["texto"]
    except Exception as erro:  # noqa: BLE001 — capa não vale abortar publicação
        print(f"[thumbnail] aviso: GPT falhou ({erro}); usando o título.")
        return reserva

    texto = " ".join((texto or "").split()).upper()
    if not texto:
        return reserva
    palavras = texto.split()
    if len(palavras) > MAX_PALAVRAS:
        texto = " ".join(palavras[:MAX_PALAVRAS])
    return texto


def _quadro_do_video(video: Path, destino: Path, instante: float) -> Path | None:
    """Extrai um quadro do vídeo já montado."""
    import subprocess

    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{instante:.2f}",
             "-i", str(video), "-vframes", "1",
             "-vf", f"scale={LARGURA}:{ALTURA}:force_original_aspect_ratio=increase,"
                    f"crop={LARGURA}:{ALTURA}",
             str(destino)],
            check=True, capture_output=True,
        )
        return destino if destino.is_file() else None
    except (subprocess.CalledProcessError, OSError) as erro:
        print(f"[thumbnail] aviso: não deu para extrair o quadro ({erro}).")
        return None


def _quebrar(texto: str, fonte: ImageFont.FreeTypeFont, largura_max: int) -> list[str]:
    """Quebra o texto em linhas que cabem na largura, sem cortar palavra."""
    for por_linha in range(len(texto), 0, -1):
        linhas = textwrap.wrap(texto, width=por_linha)
        if all(fonte.getbbox(l)[2] <= largura_max for l in linhas):
            return linhas
    return [texto]


def gerar_thumbnail(
    cfg: Config,
    video: Path,
    titulo: str,
    narracao: str,
    pasta: Path,
    instante: float = 2.0,
) -> Path | None:
    """Monta a capa e devolve o caminho; None se não foi possível.

    `instante` é onde o quadro é colhido — 2s evita o crossfade de abertura e
    já mostra o primeiro clipe (o mais bem avaliado pela auditoria) na tela.
    """
    if not FONTE.is_file():
        print(f"[thumbnail] aviso: fonte ausente ({FONTE}); sem capa.")
        return None

    quadro = _quadro_do_video(video, pasta / "thumb_quadro.png", instante)
    if quadro is None:
        return None

    texto = _texto_da_capa(cfg, titulo, narracao)
    print(f"[thumbnail] Texto da capa: {texto}")

    img = Image.open(quadro).convert("RGB")
    img = ImageEnhance.Brightness(img).enhance(ESCURECER)

    tamanho = round(ALTURA * TEXTO_FRAC)
    margem = round(LARGURA * MARGEM_FRAC)
    fonte = ImageFont.truetype(str(FONTE), tamanho)
    linhas = _quebrar(texto, fonte, LARGURA - 2 * margem)
    # Texto longo demais em duas linhas ainda estoura: encolhe até caber.
    while len(linhas) > 2 and tamanho > 24:
        tamanho = round(tamanho * 0.9)
        fonte = ImageFont.truetype(str(FONTE), tamanho)
        linhas = _quebrar(texto, fonte, LARGURA - 2 * margem)

    altura_linha = round(tamanho * ENTRELINHA)
    bloco = altura_linha * len(linhas)
    topo = ALTURA - margem - bloco

    # Tarja escura sob o bloco, para o texto ler sobre qualquer quadro. A faixa
    # vai do topo do bloco (com uma folga) até a base da capa.
    banda_topo = max(0, topo - margem // 2)
    banda = img.crop((0, banda_topo, LARGURA, ALTURA)).convert("RGBA")
    tarja = Image.new("RGBA", banda.size, (0, 0, 0, TARJA_ALFA))
    img.paste(Image.alpha_composite(banda, tarja).convert("RGB"), (0, banda_topo))

    desenho = ImageDraw.Draw(img)
    for i, linha in enumerate(linhas):
        y = topo + i * altura_linha
        # Contorno preto: garante leitura mesmo sobre um trecho claro do quadro.
        desenho.text(
            (margem, y), linha, font=fonte, fill=(255, 255, 255),
            stroke_width=max(2, tamanho // 14), stroke_fill=(0, 0, 0),
        )

    destino = pasta / "thumbnail.jpg"
    qualidade = 92
    img.save(destino, "JPEG", quality=qualidade)
    while destino.stat().st_size > MAX_BYTES and qualidade > 40:
        qualidade -= 10
        img.save(destino, "JPEG", quality=qualidade)
    print(f"[thumbnail] Capa salva em {destino} ({destino.stat().st_size} bytes)")
    return destino
