"""Identidade visual do canal: paleta e traços compartilhados da marca.

Existe porque a MANCHETE do vídeo (manchetes.py) e a CAPA (thumbnail.py) são a
mesma identidade em dois lugares: se a paleta e o traço vivessem duplicados, os
dois lados iam divergir no primeiro ajuste e o canal voltaria a parecer montado
por duas pessoas diferentes.

O ESTILO é MISTO, como pedido em 2026-08-23:

- ARANHAVERSO: a desregistragem de impressão barata — o mesmo texto repetido em
  ciano e magenta, deslocado alguns pixels para cada lado, como uma revista em
  quadrinhos impressa fora de registro; retículas Ben-Day (a malha de
  pontinhos) nos blocos de cor; traço de caneta que não fecha certo (o círculo
  feito à mão, a seta torta).
- EDITORIAL MINIMALISTA: por baixo disso, estrutura de jornal — retângulo
  preto, tipografia grotesca pesada em caixa alta, um fio fino, muito espaço
  vazio e UMA cor de destaque por peça. É o que impede a parte de quadrinhos de
  virar poluição.

Tudo aqui é Pillow puro e determinístico: nenhuma chamada paga, nenhum modelo.
A aleatoriedade do traço à mão vem de uma SEMENTE derivada do texto da peça — o
mesmo vídeo redesenha igual, e dois vídeos diferentes não saem com o mesmo
rabisco.
"""

import math
import random

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .config import RAIZ

FONTE_TITULO = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"

# --- Paleta ------------------------------------------------------------------
# Preto e branco carregam a estrutura (editorial); as cores quentes são o lado
# quadrinho. UMA delas por peça, nunca duas disputando a atenção.
PRETO = (14, 14, 16)
BRANCO = (255, 255, 255)
MAGENTA = (255, 42, 122)
CIANO = (0, 229, 255)
AMARELO = (255, 214, 0)
LARANJA = (232, 89, 12)  # a mesma cor de destaque das figuras (figuras.ESTILO)

# Cores de destaque que uma peça pode sortear, na ordem de contraste sobre o
# preto. A manchete usa sempre a primeira (a identidade do vídeo não pode
# piscar de cor a cada tópico); a capa sorteia pela semente do título, para dois
# vídeos seguidos não saírem idênticos na prateleira.
DESTAQUES = (AMARELO, MAGENTA, CIANO, LARANJA)

# Deslocamento da desregistragem, em fração do tamanho da fonte. Acima de ~0,06
# o texto vira borrão vermelho-azul; abaixo de ~0,02 ninguém vê o efeito.
CROMATICO_FRAC = 0.035


def semente(texto: str) -> int:
    """Semente estável a partir de um texto (mesma peça, mesmo traço)."""
    return sum((i + 1) * ord(c) for i, c in enumerate(texto)) % 10_000


def destaque_por(texto: str) -> tuple[int, int, int]:
    """Cor de destaque da peça, sorteada de forma estável pelo texto."""
    return DESTAQUES[semente(texto) % len(DESTAQUES)]


def fonte_disponivel() -> bool:
    return FONTE_TITULO.is_file()


# --- Tipografia --------------------------------------------------------------


def fonte(tamanho: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTE_TITULO), max(8, int(tamanho)))


def quebrar(
    dr: ImageDraw.ImageDraw,
    texto: str,
    f: ImageFont.FreeTypeFont,
    largura_max: float,
    maximo_linhas: int = 2,
) -> list[str]:
    """Quebra o texto em até `maximo_linhas`, sem cortar palavra.

    Diferente do textwrap por caracteres: mede a largura REAL de cada linha na
    fonte, que é o que decide se cabe. Devolve a melhor tentativa mesmo quando
    não cabe — quem chama encolhe a fonte e pergunta de novo.
    """
    palavras = texto.split()
    if not palavras:
        return []
    linhas: list[str] = []
    atual = palavras[0]
    for palavra in palavras[1:]:
        tentativa = atual + " " + palavra
        if dr.textlength(tentativa, font=f) <= largura_max:
            atual = tentativa
        else:
            linhas.append(atual)
            atual = palavra
    linhas.append(atual)
    if len(linhas) > maximo_linhas:
        # Junta o excesso na última linha permitida, em vez de devolver linhas
        # soltas que quem chama teria de descartar.
        cabeca = linhas[: maximo_linhas - 1]
        cabeca.append(" ".join(linhas[maximo_linhas - 1 :]))
        return cabeca
    return linhas


def caber(
    dr: ImageDraw.ImageDraw,
    texto: str,
    largura_max: float,
    tamanho: int,
    minimo: int = 14,
    maximo_linhas: int = 2,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Maior fonte (até `tamanho`) em que o texto cabe na caixa."""
    while tamanho > minimo:
        f = fonte(tamanho)
        linhas = quebrar(dr, texto, f, largura_max, maximo_linhas)
        if all(dr.textlength(linha, font=f) <= largura_max for linha in linhas):
            return f, linhas
        tamanho = int(tamanho * 0.94)
    f = fonte(minimo)
    return f, quebrar(dr, texto, f, largura_max, maximo_linhas)


def escrever_espacado(
    dr: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    texto: str,
    f: ImageFont.FreeTypeFont,
    cor: tuple,
    tracking: float = 0.0,
) -> float:
    """Escreve letra a letra com espaçamento extra; devolve a largura usada.

    O tracking largo é o que faz uma linha pequena em caixa alta ler como
    RÓTULO de jornal, e não como um texto que sobrou pequeno.
    """
    x, y = xy
    for caractere in texto:
        dr.text((x, y), caractere, font=f, fill=cor)
        x += dr.textlength(caractere, font=f) + tracking
    return max(0.0, x - xy[0] - (tracking if texto else 0))


def largura_espacada(
    dr: ImageDraw.ImageDraw, texto: str, f: ImageFont.FreeTypeFont,
    tracking: float = 0.0,
) -> float:
    """Largura que `escrever_espacado` vai ocupar, para medir antes de desenhar."""
    return dr.textlength(texto, font=f) + max(0, len(texto) - 1) * tracking


def escrever_cromatico(
    tela: Image.Image,
    xy: tuple[float, float],
    texto: str,
    f: ImageFont.FreeTypeFont,
    cor: tuple = BRANCO,
    desloc: int | None = None,
    contorno: int = 0,
    anchor: str = "la",
) -> None:
    """Texto com a desregistragem ciano/magenta do aranhaverso.

    Desenha primeiro o fantasma ciano deslocado para um lado e o magenta para o
    outro, e só então o texto principal por cima. Sobre fundo escuro isso lê
    como impressão fora de registro; sobre foto, o `contorno` preto garante que
    o texto continue legível.
    """
    dr = ImageDraw.Draw(tela, "RGBA")
    if desloc is None:
        desloc = max(2, round(f.size * CROMATICO_FRAC))
    # O contorno vem ANTES dos fantasmas, numa passada só dele. Desenhado junto
    # com o texto principal (stroke_width no mesmo `text`), ele pintava preto
    # por cima do ciano e do magenta e a desregistragem sumia — que foi
    # exatamente o que aconteceu na primeira capa montada.
    if contorno:
        dr.text(
            xy, texto, font=f, fill=PRETO, anchor=anchor,
            stroke_width=contorno, stroke_fill=PRETO,
        )
    for cor_fantasma, (dx, dy) in (
        (CIANO, (-desloc, desloc)),
        (MAGENTA, (desloc, -desloc)),
    ):
        dr.text(
            (xy[0] + dx, xy[1] + dy),
            texto,
            font=f,
            fill=(*cor_fantasma, 210),
            anchor=anchor,
        )
    dr.text(xy, texto, font=f, fill=cor, anchor=anchor)


# --- Traços de quadrinho -----------------------------------------------------


def reticula(
    tela: Image.Image,
    caixa: tuple[int, int, int, int],
    cor: tuple = BRANCO,
    passo: int = 14,
    raio: int = 3,
    alfa: int = 70,
) -> None:
    """Malha de pontinhos Ben-Day dentro da caixa (x0, y0, x1, y1).

    A retícula é a assinatura barata do estilo: é o que faz um retângulo de cor
    chapada parecer impresso em vez de gerado. Fica em alfa baixo de propósito —
    ela é textura, não elemento.
    """
    x0, y0, x1, y1 = (int(v) for v in caixa)
    if x1 <= x0 or y1 <= y0:
        return
    camada = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(camada)
    for j, y in enumerate(range(y0, y1, passo)):
        # Linhas ímpares deslocadas meio passo: malha hexagonal, como a de
        # impressão, em vez de grade de xadrez.
        desloc = passo // 2 if j % 2 else 0
        for x in range(x0 + desloc, x1, passo):
            dr.ellipse([x - raio, y - raio, x + raio, y + raio], fill=(*cor, alfa))
    tela.alpha_composite(camada)


def _pontos_ovalados(
    caixa: tuple[float, float, float, float],
    voltas: float,
    jitter: float,
    rnd: random.Random,
) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = caixa
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = max((x1 - x0) / 2, 1.0), max((y1 - y0) / 2, 1.0)
    inicio = -0.9  # começa perto de "duas horas", como quem circula à mão
    passos = max(48, int(72 * voltas))
    pontos = []
    for i in range(passos + 1):
        t = inicio + (2 * math.pi * voltas) * i / passos
        # Ruído em duas frequências: uma ondulação longa (a mão não faz um
        # círculo) e um tremor curto (a caneta não corre lisa).
        onda = math.sin(t * 2.7 + rnd.random()) * jitter * 0.6
        tremor = rnd.uniform(-jitter, jitter) * 0.4
        fator = 1 + (onda + tremor) / max(rx, ry)
        pontos.append((cx + rx * fator * math.cos(t), cy + ry * fator * math.sin(t)))
    return pontos


def circulo_a_mao(
    tela: Image.Image,
    caixa: tuple[float, float, float, float],
    cor: tuple,
    largura: int = 8,
    sem: int = 0,
    voltas: float = 1.35,
) -> None:
    """Círculo de caneta em volta de algo — torto, e dando mais de uma volta.

    A volta e pouco é o detalhe que faz o traço parecer humano: um círculo que
    fecha exatamente onde começou lê como forma vetorial.
    """
    rnd = random.Random(sem)
    jitter = max(3.0, min(caixa[2] - caixa[0], caixa[3] - caixa[1]) * 0.035)
    pontos = _pontos_ovalados(caixa, voltas, jitter, rnd)
    camada = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(camada)
    # Sombra do traço: dá corpo sobre foto clara sem virar contorno duro.
    sombra = [(x + largura * 0.35, y + largura * 0.35) for x, y in pontos]
    dr.line(sombra, fill=(*PRETO, 120), width=largura, joint="curve")
    dr.line(pontos, fill=(*cor, 245), width=largura, joint="curve")
    tela.alpha_composite(camada)


def seta_a_mao(
    tela: Image.Image,
    origem: tuple[float, float],
    destino: tuple[float, float],
    cor: tuple,
    largura: int = 8,
    sem: int = 0,
    curvatura: float = 0.22,
) -> None:
    """Seta desenhada à mão apontando de `origem` para `destino`."""
    rnd = random.Random(sem + 7)
    ox, oy = origem
    dx, dy = destino
    comprimento = math.hypot(dx - ox, dy - oy)
    if comprimento < 10:
        return
    # Ponto de controle fora da reta: a seta faz uma curva, como a de quem
    # rabisca por cima de uma foto impressa.
    mx, my = (ox + dx) / 2, (oy + dy) / 2
    nx, ny = -(dy - oy) / comprimento, (dx - ox) / comprimento
    lado = 1 if rnd.random() < 0.5 else -1
    cx = mx + nx * comprimento * curvatura * lado
    cy = my + ny * comprimento * curvatura * lado

    pontos = []
    passos = 26
    tremor = largura * 0.22
    for i in range(passos + 1):
        t = i / passos
        x = (1 - t) ** 2 * ox + 2 * (1 - t) * t * cx + t**2 * dx
        y = (1 - t) ** 2 * oy + 2 * (1 - t) * t * cy + t**2 * dy
        pontos.append(
            (x + rnd.uniform(-tremor, tremor), y + rnd.uniform(-tremor, tremor))
        )

    camada = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(camada)
    sombra = [(x + largura * 0.35, y + largura * 0.35) for x, y in pontos]
    dr.line(sombra, fill=(*PRETO, 120), width=largura, joint="curve")
    dr.line(pontos, fill=(*cor, 245), width=largura, joint="curve")

    # Ponta: triângulo alinhado com o último trecho da curva.
    px, py = pontos[-1]
    ax, ay = pontos[-4]
    ang = math.atan2(py - ay, px - ax)
    tam = max(18, largura * 3.2)
    ponta = [
        (px, py),
        (px - tam * math.cos(ang - 0.42), py - tam * math.sin(ang - 0.42)),
        (px - tam * math.cos(ang + 0.42), py - tam * math.sin(ang + 0.42)),
    ]
    dr.polygon(
        [(x + largura * 0.35, y + largura * 0.35) for x, y in ponta],
        fill=(*PRETO, 120),
    )
    dr.polygon(ponta, fill=(*cor, 245))
    tela.alpha_composite(camada)


def moldura_recorte(
    tela: Image.Image,
    caixa: tuple[int, int, int, int],
    cor_fuga: tuple,
    borda: int = 10,
) -> None:
    """Borda BRANCA grossa em volta de um recorte, com uma fuga de cor atrás.

    É o destaque de revista: o assunto sai da página com um contorno branco. A
    segunda borda, deslocada e colorida, é a mesma desregistragem do texto —
    duas chapas que não bateram na impressão.
    """
    x0, y0, x1, y1 = (int(v) for v in caixa)
    d = max(3, borda // 2)
    camada = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    ImageDraw.Draw(camada).rectangle(
        [x0 - d, y0 + d, x1 - d, y1 + d], outline=(*cor_fuga, 230), width=borda
    )
    tela.alpha_composite(camada)
    ImageDraw.Draw(tela).rectangle([x0, y0, x1, y1], outline=BRANCO, width=borda)


def sombra_de_base(
    tela: Image.Image, altura_frac: float = 0.45, alfa: int = 205,
    no_topo: bool = False,
) -> None:
    """Escurecimento em degradê numa borda — texto legível sem tarja chapada.

    A tarja retangular resolvia a legibilidade e matava a imagem: virava um
    bloco preto colado embaixo. O degradê faz o mesmo trabalho sem anunciar que
    existe. `no_topo` inverte o sentido, para quando o texto sobe (o assunto
    destacado ocupa a base da peça).
    """
    largura, altura = tela.size
    faixa = max(1, int(altura * altura_frac))
    degrade = Image.new("L", (1, faixa))
    for y in range(faixa):
        posicao = (faixa - 1 - y) if no_topo else y
        degrade.putpixel((0, y), int(alfa * (posicao / max(faixa - 1, 1)) ** 1.6))
    preto = Image.new("RGBA", (largura, faixa), (*PRETO, 255))
    preto.putalpha(degrade.resize((largura, faixa)))
    tela.alpha_composite(preto, (0, 0 if no_topo else altura - faixa))


def sombra_projetada(
    tela: Image.Image, caixa: tuple[int, int, int, int], desloc: int = 12,
    alfa: int = 165, desfoque: int = 14,
) -> None:
    """Sombra difusa sob um recorte — o que o descola do fundo desfocado.

    Sombra de borda dura entregaria o retângulo colado; o desfoque é o que faz
    o recorte parecer uma foto por cima da página.
    """
    x0, y0, x1, y1 = (int(v) for v in caixa)
    camada = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    ImageDraw.Draw(camada).rectangle(
        [x0 + desloc, y0 + desloc, x1 + desloc, y1 + desloc], fill=(*PRETO, alfa)
    )
    tela.alpha_composite(camada.filter(ImageFilter.GaussianBlur(desfoque)))


def desfocar_fundo(
    foto: Image.Image,
    sigma_frac: float = 0.018,
    brilho: float = 0.55,
    saturacao: float = 0.55,
) -> Image.Image:
    """Cópia desfocada, escurecida e dessaturada da imagem — o fundo da capa."""
    sigma = max(4, round(min(foto.size) * sigma_frac))
    fundo = foto.filter(ImageFilter.GaussianBlur(sigma))
    fundo = ImageEnhance.Color(fundo).enhance(saturacao)
    return ImageEnhance.Brightness(fundo).enhance(brilho)
