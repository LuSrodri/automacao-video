"""Geração das legendas sincronizadas (formato ASS, queimadas pelo ffmpeg).

Quando nenhuma imagem está na tela, a legenda aparece centralizada no meio;
quando há imagem, ela desce para a parte inferior (a 20% de altura), liberando
o centro para a imagem. Tipografia Barlow, texto preto com borda branca.
"""

import re
from pathlib import Path

MAX_CHARS_LINHA = 18  # tamanho máximo de cada legenda exibida
MAX_PALAVRAS = 4
MIN_EXIBICAO = 0.35  # segundos

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
    """Agrupa palavras em legendas curtas (estilo vídeo vertical)."""
    grupos, atual = [], []
    for p in palavras:
        candidato = " ".join([*(x["texto"] for x in atual), p["texto"]])
        if atual and (len(candidato) > MAX_CHARS_LINHA or len(atual) >= MAX_PALAVRAS):
            grupos.append(atual)
            atual = []
        atual.append(p)
        # Fim de frase encerra a legenda, para não misturar frases
        if p["texto"].rstrip('"').rstrip("'").endswith((".", "!", "?", "…")):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)

    eventos = []
    for g in grupos:
        eventos.append(
            {
                "texto": " ".join(x["texto"] for x in g),
                "inicio": g[0]["inicio"],
                "fim": max(g[-1]["fim"], g[0]["inicio"] + MIN_EXIBICAO),
            }
        )
    # Evita sobreposição entre legendas consecutivas
    for k in range(len(eventos) - 1):
        eventos[k]["fim"] = min(eventos[k]["fim"], eventos[k + 1]["inicio"])
    return eventos


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

    tam_centro = max(48, round(largura * 0.125))
    tam_inferior = max(32, round(largura * 0.085))
    corpo = CABECALHO.format(
        largura=largura,
        altura=altura,
        tam_centro=tam_centro,
        tam_inferior=tam_inferior,
        margem_v=round(altura * 0.20),
    )

    linhas = []
    for ev in eventos:
        central = not _tem_imagem(ev["inicio"], ev["fim"], intervalos)
        estilo = "Centro" if central else "Inferior"
        texto_ev = ev["texto"].replace("{", "(").replace("}", ")")
        if central:
            texto_ev = texto_ev.upper()
        linhas.append(
            f"Dialogue: 0,{_ts(ev['inicio'])},{_ts(ev['fim'])},{estilo},,0,0,0,,{texto_ev}"
        )

    destino.write_text(corpo + "\n".join(linhas) + "\n", encoding="utf-8")
    print(f"[legendas] {len(eventos)} legendas geradas em {destino.name}")
    return destino
