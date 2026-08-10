"""Cenário do vídeo: um SMARTPHONE apoiado sobre uma cama.

Substitui (2026-08-09, pedido do usuário) a sala de estar com TV que só o
formato longo usava. Agora os DOIS formatos são montados dentro do aparelho: o
clipe do X, as cartelas e as figuras aparecem na TELA do celular, e o resto do
quadro é a cama em volta.

A ORIENTAÇÃO do aparelho vem da orientação do vídeo: quadro vertical (Short
9:16) põe o celular EM PÉ, quadro deitado (formato longo, 16:9) põe o celular
DEITADO. É o que mantém a tela grande nos dois casos — celular em pé dentro de
um quadro 16:9 sobraria moldura por todo lado e encolheria o clipe.

Como no cenário antigo, a saída é um PNG RGBA OPACO em tudo menos no retângulo
da tela, que fica transparente. A montagem põe o conteúdo atrás e este PNG por
cima: o conteúdo só aparece pelo buraco, e o corpo do aparelho recorta as
bordas dele sem precisar de máscara no ffmpeg. É esse recorte que faz o
carrossel funcionar — o que desliza para fora da tela some atrás do aparelho.

Tudo é desenhado com Pillow: nada de asset externo, nenhuma licença de imagem
para administrar, e a paleta acompanha o vídeo.

Três entradas:
- `retangulo_tela` devolve o retângulo da tela SEM renderizar nada (as legendas
  e as cartelas precisam dele antes de a montagem existir);
- `gerar_cenario_celular` renderiza a cama + o aparelho;
- `gerar_mao` renderiza a mão que arrasta o conteúdo na tela.
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# Proporção da TELA do aparelho: largura/altura com ele EM PÉ (19,5:9 é a razão
# dos celulares atuais). Deitado, é o inverso.
TELA_RAZAO = 9 / 19.5

# Quanto do quadro o aparelho pode ocupar. O par muda com a orientação porque a
# sobra fica em eixos diferentes: em pé o que aperta é a altura, deitado é a
# largura. Os valores deixam uma faixa de cama visível em volta — sem ela o
# celular não lê como objeto sobre uma cama, lê como borda preta.
MAX_LARGURA_EM_PE = 0.68
MAX_ALTURA_EM_PE = 0.80
MAX_LARGURA_DEITADO = 0.82
MAX_ALTURA_DEITADO = 0.72

MOLDURA_FRAC = 0.038  # espessura da borda do aparelho, fração do lado MENOR da tela
RAIO_TELA_FRAC = 0.055  # raio dos cantos da tela, fração do lado menor

# Paleta da cama: dessaturada de propósito — a cama é moldura, não é o assunto;
# quem tem que puxar o olho é a tela. Mas não ESCURA: na primeira versão a
# colcha, a vinheta e o desfoque somados entregavam um retângulo cinza uniforme
# que não lia como cama nenhuma. O aparelho ocupa quase todo o quadro, então a
# faixa de cama que sobra precisa de luz e de contraste para ser reconhecida.
#
# O tom é de LINHO QUENTE, não de cinza-azulado: com a paleta fria o conjunto
# de dobras retas lia como painel acolchoado de parede, não como roupa de cama.
CAMA_TOPO = (150, 141, 130)
CAMA_BASE = (72, 66, 60)
LENCOL = (196, 187, 174)  # dobras iluminadas
LENCOL_SOMBRA = (42, 38, 34)
TRAVESSEIRO = (204, 196, 184)
VIRA = (182, 174, 162)  # o lençol virado sobre a colcha, na faixa de cima
APARELHO = (16, 16, 19)
APARELHO_BORDA = (78, 82, 95)

# Mão que arrasta o conteúdo na tela.
MAO_COR = (28, 29, 34)
MAO_RIM = (86, 90, 104)


def retangulo_tela(largura: int, altura: int) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) da tela do celular dentro do quadro.

    Determinístico e sem custo: `gerar_cenario_celular` usa exatamente este
    retângulo, e quem precisa dele antes da montagem (legendas, cartelas,
    figuras) chama esta função em vez de renderizar o cenário duas vezes.
    """
    em_pe = altura >= largura
    razao = TELA_RAZAO if em_pe else 1 / TELA_RAZAO  # largura/altura da tela
    max_l = largura * (MAX_LARGURA_EM_PE if em_pe else MAX_LARGURA_DEITADO)
    max_a = altura * (MAX_ALTURA_EM_PE if em_pe else MAX_ALTURA_DEITADO)
    tela_l = min(max_l, max_a * razao)
    tela_a = tela_l / razao
    # Lados PARES: o clipe é escalado para este retângulo, e libx264 com
    # yuv420p não aceita dimensão ímpar.
    tela_l = max(2, int(tela_l) // 2 * 2)
    tela_a = max(2, int(tela_a) // 2 * 2)
    return ((largura - tela_l) // 2, (altura - tela_a) // 2, tela_l, tela_a)


def _gradiente_vertical(img: Image.Image, cor0, cor1) -> None:
    """Preenche a imagem inteira com um gradiente vertical de cor0 a cor1."""
    desenho = ImageDraw.Draw(img)
    for i in range(img.height):
        t = i / max(img.height - 1, 1)
        cor = tuple(round(a + (b - a) * t) for a, b in zip(cor0, cor1))
        desenho.line([(0, i), (img.width, i)], fill=(*cor, 255))


def _capsula(desenho: ImageDraw.ImageDraw, p0, p1, r: float, cor) -> None:
    """Retângulo de pontas arredondadas entre dois pontos (em qualquer ângulo).

    `rounded_rectangle` do Pillow só desenha na horizontal/vertical; a mão e as
    dobras do lençol precisam de traços inclinados, e dois círculos mais um
    quadrilátero dão a mesma forma em qualquer direção.
    """
    for p in (p0, p1):
        desenho.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=cor)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    comp = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / comp * r, dx / comp * r
    desenho.polygon(
        [
            (p0[0] + nx, p0[1] + ny),
            (p1[0] + nx, p1[1] + ny),
            (p1[0] - nx, p1[1] - ny),
            (p0[0] - nx, p0[1] - ny),
        ],
        fill=cor,
    )


# Dobras do lençol, em frações do quadro (x0, y0, x1, y1, espessura). Fixas de
# propósito: o cenário precisa sair igual em toda execução, e ruído aleatório
# num fundo que fica os 25 segundos inteiros na tela só chama atenção para si.
#
# Traçadas para cruzar as FAIXAS QUE SOBRAM em volta do aparelho (as laterais e
# a barra de baixo): dobra que só existe atrás do celular não aparece no vídeo.
_DOBRAS = [
    (-0.05, 0.30, 0.30, 0.17, 0.022),
    (0.72, 0.19, 1.06, 0.34, 0.018),
    (-0.06, 0.58, 0.24, 0.71, 0.026),
    (0.78, 0.63, 1.08, 0.47, 0.020),
    (-0.04, 0.86, 0.22, 0.95, 0.017),
    (0.85, 0.82, 1.05, 0.94, 0.016),
    (0.02, 0.97, 0.70, 1.04, 0.024),
]


def _desenhar_cama(largura: int, altura: int) -> Image.Image:
    """Cama vista de cima: colcha em gradiente, travesseiro, vira e dobras."""
    img = Image.new("RGBA", (largura, altura), (0, 0, 0, 255))
    _gradiente_vertical(img, CAMA_TOPO, CAMA_BASE)

    # Travesseiro: um volume claro encostado no topo, desfocado para virar
    # relevo em vez de retângulo.
    # O travesseiro e a VIRA do lençol (a faixa de tecido dobrada sobre a
    # colcha) ficam ACIMA do aparelho, na faixa que sobra no topo do quadro: é
    # esse par — volume claro + borda horizontal com sombra — que faz a
    # superfície ser lida como CAMA e não como um fundo qualquer. Abaixo do
    # topo do celular não adiantaria nada: o aparelho cobre.
    topo = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    dr_topo = ImageDraw.Draw(topo)
    dr_topo.rounded_rectangle(
        [
            round(largura * 0.04),
            round(-altura * 0.09),
            round(largura * 0.96),
            round(altura * 0.032),
        ],
        radius=round(largura * 0.08),
        fill=(*TRAVESSEIRO, 235),
    )
    y_vira = round(altura * 0.072)
    dr_topo.rectangle(
        [0, round(altura * 0.030), largura, y_vira], fill=(*VIRA, 255)
    )
    dr_topo.rectangle(
        [0, y_vira, largura, y_vira + max(4, round(altura * 0.010))],
        fill=(*LENCOL_SOMBRA, 150),
    )
    img.alpha_composite(
        topo.filter(ImageFilter.GaussianBlur(max(4, largura * 0.010)))
    )

    # Dobras do lençol: traços claros com sombra colada embaixo — é o par que
    # dá o volume do tecido. Bem desfocadas: dobra de tecido não tem aresta, e
    # com o traço nítido o conjunto virava um painel acolchoado.
    dobras = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    dr_dobras = ImageDraw.Draw(dobras)
    for x0, y0, x1, y1, esp in _DOBRAS:
        p0 = (x0 * largura, y0 * altura)
        p1 = (x1 * largura, y1 * altura)
        raio = esp * largura
        _capsula(dr_dobras, p0, p1, raio, (*LENCOL, 150))
        _capsula(
            dr_dobras,
            (p0[0], p0[1] + raio * 2.1),
            (p1[0], p1[1] + raio * 2.1),
            raio,
            (*LENCOL_SOMBRA, 135),
        )
    img.alpha_composite(
        dobras.filter(ImageFilter.GaussianBlur(max(5, largura * 0.013)))
    )

    # Vinheta: escurece as bordas e empurra o olho para o centro, onde está o
    # aparelho. Discreta — a versão forte apagava a cama inteira.
    mascara = Image.new("L", (largura, altura), 255)
    ImageDraw.Draw(mascara).ellipse(
        [round(-largura * 0.10), round(-altura * 0.06),
         round(largura * 1.10), round(altura * 1.06)],
        fill=0,
    )
    mascara = mascara.filter(
        ImageFilter.GaussianBlur(max(20, min(largura, altura) * 0.16))
    ).point(lambda v: round(v * 0.75))
    img.paste(Image.new("RGBA", (largura, altura), (0, 0, 0, 255)), (0, 0), mascara)
    return img


def gerar_cenario_celular(
    largura: int, altura: int, destino: Path
) -> tuple[Path, tuple[int, int, int, int]]:
    """Renderiza a cena e devolve (PNG, (x, y, largura, altura) da tela).

    O PNG é opaco em tudo menos no retângulo da tela. Quem monta põe o conteúdo
    atrás e sobrepõe este PNG.
    """
    tela_x, tela_y, tela_l, tela_a = retangulo_tela(largura, altura)
    menor = min(tela_l, tela_a)
    moldura = max(4, round(menor * MOLDURA_FRAC))
    raio_tela = max(6, round(menor * RAIO_TELA_FRAC))
    raio_corpo = raio_tela + moldura

    img = _desenhar_cama(largura, altura)

    corpo = [
        tela_x - moldura,
        tela_y - moldura,
        tela_x + tela_l + moldura,
        tela_y + tela_a + moldura,
    ]

    # Sombra do aparelho na colcha: o celular está APOIADO, então a sombra é
    # curta e para baixo.
    desloc = max(3, round(moldura * 0.9))
    sombra = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle(
        [corpo[0], corpo[1] + desloc, corpo[2], corpo[3] + desloc * 2],
        radius=raio_corpo,
        fill=(0, 0, 0, 165),
    )
    img.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(moldura * 1.8)))

    desenho = ImageDraw.Draw(img)
    # Corpo do aparelho, com o fio de luz da lateral de alumínio.
    desenho.rounded_rectangle(
        corpo,
        radius=raio_corpo,
        fill=(*APARELHO, 255),
        outline=(*APARELHO_BORDA, 255),
        width=max(2, moldura // 3),
    )

    # Botões da lateral: dois riscos discretos no lado MAIOR do aparelho —
    # a lateral direita com ele em pé, a borda de cima com ele deitado. Ficam
    # colados na moldura (metade da espessura por dentro dela), senão viram
    # dois blocos soltos ao lado do celular.
    em_pe = altura >= largura
    botao = max(2, moldura // 3)
    for f0, f1 in ((0.22, 0.28), (0.33, 0.42)):
        if em_pe:
            pontos = [
                (corpo[2], tela_y + tela_a * f0), (corpo[2], tela_y + tela_a * f1)
            ]
        else:
            pontos = [
                (tela_x + tela_l * f0, corpo[1]), (tela_x + tela_l * f1, corpo[1])
            ]
        desenho.line(pontos, fill=(*APARELHO_BORDA, 255), width=botao)

    # O buraco da tela por último: alfa zero para o conteúdo aparecer por trás.
    desenho.rounded_rectangle(
        [tela_x, tela_y, tela_x + tela_l - 1, tela_y + tela_a - 1],
        radius=raio_tela,
        fill=(0, 0, 0, 0),
    )

    # Câmera frontal: uma ilha preta DENTRO da tela, no topo (em pé) ou na
    # lateral esquerda (deitado). Desenhada depois do buraco porque ela é o
    # único ponto opaco dentro dele.
    furo = max(3, round(menor * 0.020))
    if em_pe:
        cx, cy = tela_x + tela_l // 2, tela_y + round(menor * 0.055)
    else:
        cx, cy = tela_x + round(menor * 0.055), tela_y + tela_a // 2
    desenho.ellipse(
        [cx - furo, cy - furo, cx + furo, cy + furo], fill=(*APARELHO, 255)
    )

    destino.parent.mkdir(parents=True, exist_ok=True)
    img.save(destino)
    return destino, (tela_x, tela_y, tela_l, tela_a)


def gerar_mao(
    tela_l: int, tela_a: int, destino: Path
) -> tuple[Path, tuple[int, int]]:
    """Renderiza a mão que arrasta o conteúdo; devolve (PNG, ponta do dedo).

    A ponta do dedo é o ponto de contato com a tela: a montagem posiciona a mão
    subtraindo esse offset da coordenada do toque, de modo que o dedo — e não o
    canto do PNG — é o que acompanha o arrasto.

    Silhueta estilizada (dedo indicador estendido, punho fechado), escura, com
    um fio de luz na borda e um halo de toque na ponta. Não é uma foto de mão:
    é o mesmo vocabulário de mockup de interface que o espectador já reconhece,
    e desenhá-la com Pillow evita depender de asset ou licença.
    """
    # Alta e estreita: a primeira versão saiu com a palma larga demais e o dedo
    # curto, e o conjunto lia como uma luva. O que identifica a mão num vídeo
    # de 25 segundos é o DEDO ESTENDIDO — ele precisa de comprimento, e a palma,
    # de menos largura.
    alt = max(60, round(min(tela_a * 0.92, tela_l * 0.80)))
    larg = max(34, round(alt * 0.58))
    margem = max(8, round(larg * 0.12))  # espaço para a sombra
    imagem = Image.new("RGBA", (larg + 2 * margem, alt + 2 * margem), (0, 0, 0, 0))

    def p(fx: float, fy: float) -> tuple[float, float]:
        return (margem + larg * fx, margem + alt * fy)

    ponta = p(0.30, 0.035)
    no_dedo = p(0.46, 0.50)
    r_dedo = larg * 0.082
    palma0, palma1 = p(0.40, 0.60), p(0.56, 1.02)
    r_palma = larg * 0.230
    polegar0, polegar1 = p(0.34, 0.72), p(0.13, 0.62)
    r_polegar = larg * 0.072
    # Nós dos outros dedos, dobrados sobre a palma: dois volumes pequenos na
    # borda esquerda do punho, que é o que distingue um punho fechado de um
    # bloco arredondado.
    nos = [(p(0.26, 0.70), p(0.34, 0.70)), (p(0.24, 0.82), p(0.33, 0.82))]
    r_no = larg * 0.090

    def silhueta(folga: float, cor) -> None:
        dr = ImageDraw.Draw(imagem)
        _capsula(dr, palma0, palma1, r_palma + folga, cor)
        for a, b in nos:
            _capsula(dr, a, b, r_no + folga, cor)
        _capsula(dr, polegar0, polegar1, r_polegar + folga, cor)
        _capsula(dr, ponta, no_dedo, r_dedo + folga, cor)

    # Sombra da mão sobre a tela, depois o fio de luz e o corpo por cima.
    sombra = Image.new("RGBA", imagem.size, (0, 0, 0, 0))
    dr_sombra = ImageDraw.Draw(sombra)
    _capsula(dr_sombra, palma0, palma1, r_palma * 1.05, (0, 0, 0, 150))
    _capsula(dr_sombra, ponta, no_dedo, r_dedo * 1.15, (0, 0, 0, 150))
    imagem.alpha_composite(
        sombra.filter(ImageFilter.GaussianBlur(max(4, larg * 0.05)))
    )
    silhueta(max(1.5, larg * 0.012), (*MAO_RIM, 255))
    silhueta(0.0, (*MAO_COR, 255))

    # Halo do toque na ponta do dedo: o sinal visual de que o arrasto é dali.
    halo = Image.new("RGBA", imagem.size, (0, 0, 0, 0))
    dr_halo = ImageDraw.Draw(halo)
    r_halo = larg * 0.17
    dr_halo.ellipse(
        [ponta[0] - r_halo, ponta[1] - r_halo, ponta[0] + r_halo, ponta[1] + r_halo],
        fill=(255, 255, 255, 45),
        outline=(255, 255, 255, 120),
        width=max(2, round(larg * 0.014)),
    )
    imagem.alpha_composite(halo.filter(ImageFilter.GaussianBlur(max(1, larg * 0.006))))

    destino.parent.mkdir(parents=True, exist_ok=True)
    imagem.save(destino)
    return destino, (round(ponta[0]), round(ponta[1]))
