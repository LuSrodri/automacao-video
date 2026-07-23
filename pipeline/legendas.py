"""Geração das legendas sincronizadas (formato ASS, queimadas pelo ffmpeg).

As legendas aparecem UMA PALAVRA POR VEZ, sempre em MAIÚSCULAS, com uma leve
animação de entrada (pop + fade). Quando nenhuma imagem está na tela, a palavra
fica centralizada no meio; quando há imagem, ela vai para a parte de baixo
(deixando o centro livre para a imagem). Tipografia Barlow, texto preto com
borda branca.
"""

import re
from pathlib import Path

MIN_EXIBICAO = 0.35  # segundos

# Animação de entrada (sutil): a palavra surge a 82% do tamanho e cresce até
# 100% em 140 ms, com um fade rápido. São tags de override do próprio ASS.
ANIM = r"{\fscx82\fscy82\t(0,140,\fscx100\fscy100)\fad(80,40)}"

CABECALHO = """\
[Script Info]
ScriptType: v4.00+
PlayResX: {largura}
PlayResY: {altura}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Centro,Barlow,{tam_centro},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,4,0,5,40,40,0,1
Style: Inferior,Barlow,{tam_inferior},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,1,4,0,2,40,40,{margem_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _palavras_com_tempos(texto: str, alinhamento: dict, dur_total: float) -> list[dict]:
    """Converte o alinhamento por caractere em palavras com início/fim."""
    chars = alinhamento.get("characters") or []
    inicios = alinhamento.get("character_start_times_seconds") or []
    fins = alinhamento.get("character_end_times_seconds") or []

    palavras: list[dict] = []
    if chars and len(chars) == len(inicios) == len(fins):
        atual, ini = "", None
        profundidade = 0  # dentro de [audio tags], que não são faladas
        for c, i, f in zip(chars, inicios, fins):
            if c == "[":
                profundidade += 1
            if profundidade:
                if c == "]":
                    profundidade = max(0, profundidade - 1)
                if atual:
                    palavras.append({"texto": atual, "inicio": ini, "fim": fim})
                    atual, ini = "", None
                continue
            if c.isspace():
                if atual:
                    palavras.append({"texto": atual, "inicio": ini, "fim": fim})
                    atual, ini = "", None
                continue
            if not atual:
                ini = i
            atual += c
            fim = f
        if atual:
            palavras.append({"texto": atual, "inicio": ini, "fim": fim})
        return palavras

    # Reserva: sem alinhamento, distribui as palavras uniformemente no áudio
    tokens = re.sub(r"\[[^\]]*\]", " ", texto).split()
    passo = dur_total / max(len(tokens), 1)
    return [
        {"texto": t, "inicio": k * passo, "fim": (k + 1) * passo}
        for k, t in enumerate(tokens)
    ]


def _agrupar(palavras: list[dict]) -> list[dict]:
    """Uma legenda por palavra (estilo karaokê de vídeo vertical)."""
    eventos = [
        {
            "texto": p["texto"],
            "inicio": p["inicio"],
            "fim": max(p["fim"], p["inicio"] + MIN_EXIBICAO),
        }
        for p in palavras
    ]
    # Evita sobreposição entre legendas consecutivas (sem deixar o fim recuar
    # para antes do início, o que geraria um evento de duração negativa).
    for k in range(len(eventos) - 1):
        eventos[k]["fim"] = max(
            eventos[k]["inicio"],
            min(eventos[k]["fim"], eventos[k + 1]["inicio"]),
        )
    return eventos


# Largura aproximada dos glifos maiúsculos da Barlow, em frações do tamanho da
# fonte. Serve só para estimar se a palavra cabe na tela; o que não estiver na
# tabela usa a média.
_LARGURA_GLIFO = {
    "I": 0.32, "J": 0.48, "L": 0.54, "F": 0.56, "T": 0.58, "E": 0.58,
    "B": 0.62, "P": 0.60, "R": 0.62, "S": 0.60, "Z": 0.58,
    "M": 0.92, "W": 0.98,
    "-": 0.40, "'": 0.25, ",": 0.28, ".": 0.28, "!": 0.32, "?": 0.55,
}
_LARGURA_PADRAO = 0.66


def _tamanho_que_cabe(palavra: str, tam_base: int, largura_util: float) -> int:
    """Reduz o tamanho da fonte quando a palavra não cabe na largura útil."""
    largura_est = sum(_LARGURA_GLIFO.get(c, _LARGURA_PADRAO) for c in palavra) * tam_base
    if largura_est <= largura_util:
        return tam_base
    return max(round(tam_base * largura_util / largura_est), 28)


def _tem_imagem(ini: float, fim: float, intervalos: list[tuple[float, float]]) -> bool:
    """Indica se alguma imagem está na tela durante a legenda (ini, fim)."""
    return any(ini < fi and fim > ii for ii, fi in intervalos)


def _ts(segundos: float) -> str:
    segundos = max(0.0, segundos)
    h = int(segundos // 3600)
    m = int(segundos % 3600 // 60)
    s = segundos % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def gerar_legendas(
    texto: str,
    alinhamento: dict,
    dur_total: float,
    largura: int,
    altura: int,
    destino: Path,
    intervalos_imagens: list[tuple[float, float]] | None = None,
) -> Path:
    """Gera o .ass das legendas sincronizadas e devolve seu caminho.

    `intervalos_imagens`: janelas (início, fim) em que há imagem na tela; nesses
    trechos a legenda vai para a parte inferior, nos demais fica centralizada.
    """
    intervalos = intervalos_imagens or []
    palavras = _palavras_com_tempos(texto, alinhamento, dur_total)
    eventos = _agrupar(palavras)

    tam_centro = max(56, round(largura * 0.150))
    tam_inferior = max(40, round(largura * 0.110))
    corpo = CABECALHO.format(
        largura=largura,
        altura=altura,
        tam_centro=tam_centro,
        tam_inferior=tam_inferior,
        margem_v=round(altura * 0.26),
    )

    # Largura disponível para o texto: tela menos as margens laterais (40+40)
    # e a borda, com uma folga de segurança para a estimativa de largura.
    largura_util = (largura - 80 - 8) * 0.95

    linhas = []
    for ev in eventos:
        central = not _tem_imagem(ev["inicio"], ev["fim"], intervalos)
        estilo = "Centro" if central else "Inferior"
        palavra = ev["texto"].replace("{", "(").replace("}", ")").upper()
        tam_base = tam_centro if central else tam_inferior
        tam = _tamanho_que_cabe(palavra, tam_base, largura_util)
        ajuste = f"{{\\fs{tam}}}" if tam != tam_base else ""
        linhas.append(
            f"Dialogue: 0,{_ts(ev['inicio'])},{_ts(ev['fim'])},{estilo},,0,0,0,,{ajuste}{ANIM}{palavra}"
        )

    destino.write_text(corpo + "\n".join(linhas) + "\n", encoding="utf-8")
    print(f"[legendas] {len(eventos)} legendas geradas em {destino.name}")
    return destino
