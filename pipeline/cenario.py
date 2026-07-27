"""Cenário de sala de estar com uma TV, para o formato longo.

O clipe deixa de ocupar a tela inteira e passa a aparecer DENTRO da TV de uma
sala — identidade visual do formato longo (o Short segue em tela cheia). O
cenário é desenhado com Pillow, como os infográficos: nada de asset externo,
nenhuma licença de imagem para administrar, e a paleta acompanha o vídeo.

A saída é um PNG RGBA em que TUDO é opaco menos o retângulo da tela, que fica
transparente. A montagem põe o clipe atrás e este PNG por cima: o clipe só
aparece pelo buraco, e a moldura da TV cobre as bordas dele sem precisar de
máscara no ffmpeg.

`gerar_cenario_tv` devolve (caminho do PNG, retângulo da tela em px).
"""

from pathlib import Path

from PIL import Image, ImageDraw

# Paleta escura e dessaturada: a sala é moldura, não é o assunto — quem tem que
# puxar o olho é o clipe dentro da TV.
PAREDE_TOPO = (28, 30, 36)
PAREDE_BASE = (18, 19, 24)
PISO = (13, 14, 18)
MOVEL = (38, 33, 30)
MOVEL_TAMPO = (52, 45, 40)
BEZEL = (10, 10, 12)
BEZEL_BORDA = (58, 60, 68)
DETALHE = (44, 48, 58)

# A tela ocupa esta fração da largura do vídeo. Subir aproxima o clipe do
# tamanho que ele tinha em tela cheia (e some com a sala); descer dá mais sala
# e menos clipe. 0.76 deixa o clipe grande e ainda lê como "TV numa sala".
TELA_FRAC_LARGURA = 0.76
TELA_TOPO_FRAC = 0.085  # distância do topo do vídeo até o topo da tela
MOLDURA_FRAC = 0.011  # espessura da moldura da TV, fração da largura


def _gradiente_vertical(img: Image.Image, y0: int, y1: int, cor0, cor1) -> None:
    """Preenche a faixa [y0, y1) com um gradiente vertical de cor0 a cor1."""
    desenho = ImageDraw.Draw(img)
    altura = max(y1 - y0, 1)
    for i in range(altura):
        t = i / altura
        cor = tuple(round(a + (b - a) * t) for a, b in zip(cor0, cor1))
        desenho.line([(0, y0 + i), (img.width, y0 + i)], fill=(*cor, 255))


def gerar_cenario_tv(
    largura: int, altura: int, destino: Path
) -> tuple[Path, tuple[int, int, int, int]]:
    """Renderiza a sala e devolve (PNG, (x, y, largura, altura) da tela).

    O retângulo da tela é 16:9 e fica com o buraco transparente. Quem monta
    escala o clipe para esse retângulo e sobrepõe este PNG por cima.
    """
    tela_l = round(largura * TELA_FRAC_LARGURA)
    tela_a = round(tela_l * 9 / 16)
    tela_x = (largura - tela_l) // 2
    tela_y = round(altura * TELA_TOPO_FRAC)
    moldura = max(4, round(largura * MOLDURA_FRAC))

    img = Image.new("RGBA", (largura, altura), (0, 0, 0, 255))
    desenho = ImageDraw.Draw(img)

    # Parede com gradiente, e o piso ocupando a faixa de baixo.
    linha_piso = tela_y + tela_a + round(altura * 0.075)
    _gradiente_vertical(img, 0, linha_piso, PAREDE_TOPO, PAREDE_BASE)
    desenho.rectangle([0, linha_piso, largura, altura], fill=(*PISO, 255))

    # Móvel sob a TV: um bloco largo e baixo, com tampo mais claro.
    movel_l = round(tela_l * 1.02)
    movel_x = (largura - movel_l) // 2
    movel_topo = linha_piso - round(altura * 0.02)
    desenho.rectangle(
        [movel_x, movel_topo, movel_x + movel_l, altura], fill=(*MOVEL, 255)
    )
    desenho.rectangle(
        [movel_x, movel_topo, movel_x + movel_l, movel_topo + max(3, moldura // 2)],
        fill=(*MOVEL_TAMPO, 255),
    )
    # Puxadores: dois riscos discretos, só para o móvel não ser um retângulo.
    puxador_y = movel_topo + round((altura - movel_topo) * 0.42)
    for frac in (0.3, 0.7):
        cx = movel_x + round(movel_l * frac)
        desenho.line(
            [(cx - round(largura * 0.03), puxador_y),
             (cx + round(largura * 0.03), puxador_y)],
            fill=(*MOVEL_TAMPO, 255), width=max(2, moldura // 3),
        )

    # Pé central da TV, ligando a moldura ao móvel.
    pe_l = round(tela_l * 0.10)
    desenho.rectangle(
        [(largura - pe_l) // 2, tela_y + tela_a,
         (largura + pe_l) // 2, movel_topo],
        fill=(*BEZEL, 255),
    )

    # Moldura da TV: bloco escuro com um fio de luz na borda externa.
    desenho.rectangle(
        [tela_x - moldura, tela_y - moldura,
         tela_x + tela_l + moldura, tela_y + tela_a + moldura],
        fill=(*BEZEL, 255), outline=(*BEZEL_BORDA, 255), width=max(1, moldura // 4),
    )

    # Quadro na parede à esquerda e luminária à direita: dois volumes que dão
    # profundidade sem competir com a TV.
    q_l = round(largura * 0.055)
    q_x, q_y = round(largura * 0.045), round(altura * 0.13)
    desenho.rectangle(
        [q_x, q_y, q_x + q_l, q_y + round(q_l * 1.35)],
        outline=(*DETALHE, 255), width=max(2, moldura // 3),
    )
    lum_x = largura - round(largura * 0.062)
    desenho.line(
        [(lum_x, linha_piso), (lum_x, round(altura * 0.30))],
        fill=(*DETALHE, 255), width=max(2, moldura // 3),
    )
    cupula = round(largura * 0.035)
    desenho.polygon(
        [(lum_x - cupula, round(altura * 0.30)),
         (lum_x + cupula, round(altura * 0.30)),
         (lum_x + round(cupula * 0.6), round(altura * 0.22)),
         (lum_x - round(cupula * 0.6), round(altura * 0.22))],
        fill=(*DETALHE, 255),
    )

    # O buraco da tela por último: zera o alfa para o clipe aparecer por trás.
    desenho.rectangle(
        [tela_x, tela_y, tela_x + tela_l - 1, tela_y + tela_a - 1],
        fill=(0, 0, 0, 0),
    )

    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino)
    return destino, (tela_x, tela_y, tela_l, tela_a)
