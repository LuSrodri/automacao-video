"""As quatro partes do vídeo longo e o painel de texto que nomeia cada uma.

DESENHO DO USUÁRIO (2026-08-25). O vídeo longo tem QUATRO PARTES, montadas
separadamente e coladas no ffmpeg (montagem_longa.py):

    +--------------+ +----------+ +----------+ +----------+
    |   3 clipes   | | clipe 1  | | clipe 2  | | clipe 3  |
    | [AINDA NESTE | | [MANCHETE| | [MANCHETE| | [MANCHETE|
    |    VÍDEO]    | |    1]    | |    2]    | |    3]    |
    +--------------+ +----------+ +----------+ +----------+
         ~10s       ^           ^            ^         fade
                  pausa       pausa        pausa       out 3s
                  0,7s        0,7s         0,7s

O que mudou em relação à versão de 2026-08-23, e por quê — o usuário viu o
vídeo publicado e disse que "ainda ficou uma merda":

1. O PAINEL NUNCA SAI DA TELA. Antes cada manchete durava DUR_MANCHETE = 4,2s
   e sumia, deixando 40 segundos de tela sem nenhuma marca de onde o
   espectador está — que é justamente o problema que a camada existia para
   resolver. Agora o painel da parte fica de ponta a ponta dela, e o que
   acontece na virada é uma TROCA: o painel velho sai deslizando e o novo
   entra, dentro da pausa de silêncio. Três trocas no vídeo inteiro, uma por
   virada de pauta.
2. O ÍNDICE É UM PAINEL SÓ, com os três títulos listados. Antes eram três
   painéis piscando um de cada vez (1/3, 2/3, 3/3) dentro dos ~6s da pauta
   falada — tempo de ver que algo piscou, não de ler.
3. AS PARTES SÃO O CORTE DO VÍDEO, não uma sobreposição sobre um vídeo corrido.
   Cada parte é renderizada sozinha, com o SEU clipe (montagem_longa.py), o que
   torna impossível um clipe atravessar duas pautas.

Por isso esta camada deixou de ser opcional. Antes qualquer falha só deixava o
vídeo sem manchetes; agora ela devolve a divisão do vídeo, e falhar aqui é
falhar a montagem inteira — `planejar_partes` levanta SystemExit em vez de
devolver lista vazia. O que protege a execução é a conferência de estrutura no
escritor (`_conferir_estrutura_longa`), que roda ANTES da narração e garante os
três tópicos com citação literal.

AS DURAÇÕES DO DESENHO SÃO CONFERIDAS AQUI (2026-08-26). O ~10s da abertura e o
tamanho das pautas eram texto de prompt e nada mais: as bordas das partes saem
das citações dos tópicos, e enquanto a única regra da citação foi "existir e
estar em ordem", a do tópico 1 podia pousar no meio do bloco dele. O vídeo do
canal US de 26/08 saiu com abertura de 45,4s e pauta 1 de 10,2s — o índice
"ainda neste vídeo" ficou 30% do vídeo na tela enquanto a narração já contava a
primeira história. `planejar_partes` agora ABORTA fora da faixa
(config.LONGO_ABERTURA_MAX_S e config.LONGO_PAUTA_MIN_S). É a rede de baixo: a
de cima é o teto em palavras no escritor, que reprova de graça e com reescrita.

ESTILO — o MESMO da capa (identidade.py): etiqueta de cor chapada com retícula
Ben-Day, título em grotesca pesada com a desregistragem ciano/magenta e um
grifo à mão por baixo. O MOVIMENTO é do ffmpeg (montagem_longa.py): o painel
entra deslizando da borda esquerda com aceleração suave e sai pelo mesmo
caminho.

Só o formato LONGO usa esta camada: o Short tem legenda queimada ocupando a
tela e 25 segundos que não comportam índice nenhum.
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw

from . import identidade as ident
from .config import (
    LONGO_ABERTURA_MAX_S,
    LONGO_ABERTURA_S,
    LONGO_PAUTA_MIN_S,
    Config,
)

# --- Rótulos por canal -------------------------------------------------------
# Idioma é regra de CANAL (config.IDIOMA_CANAL), nunca inferido: texto na tela é
# texto do canal como qualquer outro.
RUBRICAS = {
    "brasil": "AINDA NESTE VÍDEO",
    "usa": "COMING UP",
}

# --- Geometria (frações do quadro) -------------------------------------------
MARGEM_X_FRAC = 0.052
# Base do painel. Fica ACIMA da etiqueta de REPRESENTAÇÃO VISUAL
# (montagem_longa.REPR_Y_FRAC = 0.912), que é marcação obrigatória de material
# de terceiro e não pode ser coberta.
BASE_FRAC = 0.880
LARGURA_MAX_FRAC = 0.62
TITULO_FRAC = 0.050  # tamanho da fonte do título, fração da altura do quadro
# As linhas do índice são menores que a manchete de uma pauta: são três, e o
# painel inteiro tem que caber acima da etiqueta de representação.
INDICE_FRAC = 0.033
KICKER_FRAC = 0.020
PAD_FRAC = 0.020
FUNDO_ALFA = 232
ENTRELINHA = 1.14
ENTRELINHA_INDICE = 1.42  # respiro maior: três linhas coladas viram parágrafo
TRACKING_FRAC = 0.34  # espaçamento do kicker, fração do tamanho da fonte

# A duração mínima de uma parte era PARTE_CURTA_S = 6.0 e só imprimia aviso.
# Saiu em 2026-08-26: a faixa agora é dura e mora em config.py
# (LONGO_ABERTURA_MAX_S e LONGO_PAUTA_MIN_S), com os dois lados medidos —
# o piso não pegava nada com 6s, e não havia TETO nenhum para a abertura,
# que é o lado por onde o vídeo saiu errado.


def _medidor() -> ImageDraw.ImageDraw:
    """Um Draw descartável só para medir texto antes de criar a tela real."""
    return ImageDraw.Draw(Image.new("RGB", (1, 1)))


def _etiqueta_medida(
    medidor: ImageDraw.ImageDraw,
    kicker: str,
    f_kicker,
    tracking: float,
    tam_kicker: int,
) -> tuple[int, int, int]:
    """(largura, altura, padding) da etiqueta de cor chapada do topo do painel."""
    pad_et = max(4, round(tam_kicker * 0.45))
    larg = ident.largura_espacada(medidor, kicker, f_kicker, tracking)
    return round(larg + 2 * pad_et), round(tam_kicker + 2 * pad_et), pad_et


def _fundo_slab(tela: Image.Image, topo: int, altura_quadro: int) -> None:
    """Pinta o corpo do painel: preto quase opaco com a retícula da capa."""
    largura, altura = tela.size
    dr = ImageDraw.Draw(tela, "RGBA")
    dr.rectangle([0, topo, largura, altura], fill=(*ident.PRETO, FUNDO_ALFA))
    # Retícula bem fraca no corpo do slab: a textura de impressão que liga a
    # manchete à capa, sem virar ruído atrás do texto.
    ident.reticula(
        tela,
        (0, topo, largura, altura),
        cor=ident.BRANCO,
        passo=max(9, round(altura_quadro * 0.012)),
        raio=1,
        alfa=20,
    )


def _encurtar(medidor, texto: str, fonte, largura_max: float) -> str:
    """Corta o texto com reticências até caber em `largura_max`."""
    if medidor.textlength(texto, font=fonte) <= largura_max:
        return texto
    corte = texto
    while corte and medidor.textlength(corte + "...", font=fonte) > largura_max:
        corte = corte[:-1].rstrip()
    return (corte + "...") if corte else texto


def _painel_pauta(
    titulo: str,
    kicker: str,
    destino: Path,
    altura_quadro: int,
    largura_max: int,
    cor: tuple,
    altura_minima: int = 0,
) -> tuple[Path, int, int]:
    """Painel de UMA pauta; devolve (caminho, largura, altura).

    O PNG tem o tamanho do CONTEÚDO — não a largura do quadro. Um PNG de faixa
    inteira custaria memória de overlay em cada frame da janela sem desenhar
    nada nas bordas, e este é um formato que já estourou o container.

    `altura_minima` iguala a altura dos três painéis de pauta. Sem isso, um
    título que quebra em duas linhas gera um painel mais alto que o do vizinho,
    e como o painel é ancorado pela BASE, a troca vira solavanco em vez de
    deslize. Com a altura fixa, o título ganha o espaço que sobra centrado.
    """
    medidor = _medidor()
    pad = round(altura_quadro * PAD_FRAC)
    tam_kicker = max(11, round(altura_quadro * KICKER_FRAC))
    f_kicker = ident.fonte(tam_kicker)
    # O tracking largo é o que faz uma linha pequena ler como RÓTULO. Num
    # kicker de duas letras ("02") ele só afasta os dois algarismos e o número
    # deixa de ser um número: aí o espaçamento sai.
    tracking = tam_kicker * TRACKING_FRAC if len(kicker) > 3 else 0.0

    util_max = largura_max - 2 * pad
    f_titulo, linhas = ident.caber(
        medidor,
        titulo.upper(),
        util_max,
        round(altura_quadro * TITULO_FRAC),
        minimo=max(16, round(altura_quadro * 0.028)),
        maximo_linhas=2,
    )
    larg_titulo = max(
        (medidor.textlength(linha, font=f_titulo) for linha in linhas), default=0
    )
    larg_etiqueta, alt_etiqueta, pad_et = _etiqueta_medida(
        medidor, kicker, f_kicker, tracking, tam_kicker
    )

    alt_linha = round(f_titulo.size * ENTRELINHA)
    largura = round(max(larg_etiqueta, min(util_max, larg_titulo) + 2 * pad))
    alt_slab = round(2 * pad + alt_linha * len(linhas))
    alt_conteudo = alt_etiqueta + alt_slab
    altura = max(alt_conteudo, int(altura_minima))
    # A etiqueta fica colada no topo; a folga da altura uniforme cai no slab,
    # com o título centrado nela.
    sobra = altura - alt_conteudo

    tela = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    dr = ImageDraw.Draw(tela, "RGBA")
    _fundo_slab(tela, alt_etiqueta, altura_quadro)
    ident.etiqueta(
        tela,
        (0, 0, larg_etiqueta, alt_etiqueta),
        cor,
        passo_reticula=max(6, round(tam_kicker * 0.42)),
    )
    ident.escrever_espacado(
        dr, (pad_et, pad_et), kicker, f_kicker, ident.PRETO, tracking
    )

    y = alt_etiqueta + pad + sobra // 2
    for i, linha in enumerate(linhas):
        ident.escrever_cromatico(tela, (pad, y), linha, f_titulo, ident.BRANCO)
        if i == len(linhas) - 1:
            # Grifo à mão sob a última linha: o traço da capa, reduzido. 1,10 do
            # corpo da fonte deixa o traço ABAIXO das maiúsculas do Archivo
            # Black; em 1,02 ele cortava o pé das letras.
            larg_linha = medidor.textlength(linha, font=f_titulo)
            ident.risco_a_mao(
                tela,
                pad,
                pad + larg_linha,
                y + f_titulo.size * 1.10,
                cor,
                largura=max(3, round(f_titulo.size * 0.085)),
                sem=ident.semente(titulo),
            )
        y += alt_linha

    destino.parent.mkdir(parents=True, exist_ok=True)
    tela.save(destino)
    return destino, largura, altura


def _painel_indice(
    itens: list[str],
    rubrica: str,
    destino: Path,
    altura_quadro: int,
    largura_max: int,
    cor: tuple,
) -> tuple[Path, int, int]:
    """Painel da abertura: a rubrica e os três títulos LISTADOS de uma vez.

    Um painel, não três. Na versão anterior os títulos entravam um a um dentro
    dos ~6 segundos da pauta falada, o que dava menos de dois segundos por item
    — tempo de ver que algo piscou, não de ler. Aqui os três ficam juntos na
    tela durante a abertura inteira, numerados, e o espectador lê no ritmo dele
    enquanto a narração diz os mesmos três assuntos na mesma ordem.
    """
    medidor = _medidor()
    pad = round(altura_quadro * PAD_FRAC)
    tam_kicker = max(11, round(altura_quadro * KICKER_FRAC))
    f_kicker = ident.fonte(tam_kicker)
    tracking = tam_kicker * TRACKING_FRAC
    larg_etiqueta, alt_etiqueta, pad_et = _etiqueta_medida(
        medidor, rubrica, f_kicker, tracking, tam_kicker
    )

    # O número de cada linha ("01") é desenhado na cor de destaque e ocupa uma
    # coluna fixa, para os títulos alinharem entre si.
    tam_num = max(12, round(altura_quadro * INDICE_FRAC * 0.72))
    f_num = ident.fonte(tam_num)
    col_num = round(medidor.textlength("00", font=f_num) + tam_num * 0.75)

    util_max = largura_max - 2 * pad - col_num
    # Uma fonte só para as três linhas: tamanhos diferentes entre itens leriam
    # como hierarquia que não existe. Cai até a MAIS LONGA caber em uma linha.
    tam = round(altura_quadro * INDICE_FRAC)
    minimo = max(14, round(altura_quadro * 0.021))
    while tam > minimo:
        f = ident.fonte(tam)
        if all(medidor.textlength(i.upper(), font=f) <= util_max for i in itens):
            break
        tam = int(tam * 0.94)
    f_item = ident.fonte(tam)
    # O que ainda não couber (título longo demais mesmo no menor corpo) é
    # cortado com reticências: melhor um item truncado do que um painel que
    # vaza do quadro.
    linhas = [_encurtar(medidor, i.upper(), f_item, util_max) for i in itens]

    alt_linha = round(f_item.size * ENTRELINHA_INDICE)
    larg_texto = max(
        (medidor.textlength(linha, font=f_item) for linha in linhas), default=0
    )
    largura = round(
        max(larg_etiqueta, min(util_max, larg_texto) + col_num + 2 * pad)
    )
    alt_slab = round(2 * pad + alt_linha * len(linhas))
    altura = alt_etiqueta + alt_slab

    tela = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    dr = ImageDraw.Draw(tela, "RGBA")
    _fundo_slab(tela, alt_etiqueta, altura_quadro)
    ident.etiqueta(
        tela,
        (0, 0, larg_etiqueta, alt_etiqueta),
        cor,
        passo_reticula=max(6, round(tam_kicker * 0.42)),
    )
    ident.escrever_espacado(
        dr, (pad_et, pad_et), rubrica, f_kicker, ident.PRETO, tracking
    )

    y = alt_etiqueta + pad
    for k, linha in enumerate(linhas, 1):
        # A linha de base do número acompanha a do título, não o topo da caixa:
        # o corpo do número é menor e alinhar pelo topo o deixaria flutuando.
        dr.text(
            (pad, y + (f_item.size - f_num.size) * 0.85),
            f"{k:02d}",
            font=f_num,
            fill=cor,
        )
        ident.escrever_cromatico(
            tela, (pad + col_num, y), linha, f_item, ident.BRANCO
        )
        y += alt_linha

    destino.parent.mkdir(parents=True, exist_ok=True)
    tela.save(destino)
    return destino, largura, altura


def instantes_das_viradas(
    roteiro: dict, texto_video: str, alinhamento: dict, dur_total: float
) -> list[float]:
    """Instantes em que cada pauta começa — onde o silêncio deve ser aberto.

    Roda ANTES de `planejar_partes` e antes de a pausa existir: os tempos saem
    do alinhamento do áudio já aparado, e é `silencio.inserir_pausas` que os
    consome, devolvendo em troca o começo REAL de cada silêncio no áudio novo.
    São esses silêncios — não estes instantes — que viram as bordas das partes,
    porque depois da inserção toda a linha do tempo andou.

    As citações já foram conferidas no escritor (`_conferir_estrutura_longa`),
    que roda ANTES da narração; aqui elas só são convertidas em segundos.
    """
    from .cortes import _tempo_do_char, localizar_citacao

    instantes: list[float] = []
    cursor = 0
    for topico in roteiro.get("topicos") or []:
        pos = localizar_citacao(texto_video, topico.get("citacao") or "", cursor)
        if pos is None:
            print(
                "[partes] Tópico sem âncora na narração: "
                f"{topico.get('titulo', '')}"
            )
            continue
        cursor = pos + 1
        instantes.append(_tempo_do_char(alinhamento, texto_video, pos, dur_total))
    return instantes


def planejar_partes(
    cfg: Config,
    roteiro: dict,
    pausas: list[tuple[float, float]],
    duracao: float,
    pasta: Path,
    tela: tuple[int, int],
) -> list[dict]:
    """As quatro partes do vídeo, com o painel de texto de cada uma.

    `pausas` são os silêncios abertos por `silencio.inserir_pausas`, já em
    coordenadas do áudio FINAL: (início, fim) de cada um. São eles que definem
    as bordas — a parte nova começa quando o silêncio começa, de modo que o
    painel troque DENTRO do silêncio e a narração da pauta nova seja a primeira
    coisa que se ouve depois dele.

    Devolve, na ordem: [{"indice", "rotulo", "titulo", "inicio_s", "fim_s",
    "pausa_s", "painel", "painel_saindo"}], onde cada painel é
    {"imagem", "x", "y", "largura", "altura"} — a posição é o canto superior
    esquerdo em repouso; o deslize até lá é do ffmpeg (montagem_longa.py).

    Levanta SystemExit se a divisão não fechar: sem as quatro partes não existe
    o vídeo que o usuário desenhou, e o que sairia é o bloco corrido que ele
    rejeitou. Também levanta se as partes existirem mas com as DURAÇÕES
    erradas — abertura acima de LONGO_ABERTURA_MAX_S ou pauta abaixo de
    LONGO_PAUTA_MIN_S —, porque quatro partes na proporção errada são o mesmo
    vídeo errado com outra aparência.
    """
    topicos = roteiro.get("topicos") or []
    # Uma pausa por VIRADA de pauta, e uma parte a mais que as pausas (a
    # abertura): três tópicos são três pausas e quatro partes.
    if len(pausas) != len(topicos):
        raise SystemExit(
            f"O roteiro tem {len(topicos)} tópico(s) e a narração recebeu "
            f"{len(pausas)} pausa(s) de virada — a divisão do vídeo em "
            f"{len(topicos) + 1} partes não fecha. Uma virada de pauta caiu "
            "perto demais da outra (ou da borda do áudio) e o silêncio não pôde "
            "ser aberto ali; abortando sem publicar."
        )
    if not ident.fonte_disponivel():
        raise SystemExit(
            "Fonte Archivo Black ausente — o formato longo é montado em torno "
            "do painel de texto de cada parte, e sem a fonte não há painel; "
            "abortando sem publicar."
        )

    titulos = [" ".join((t.get("titulo") or "").split()) for t in topicos]
    if not all(titulos):
        raise SystemExit(
            "Um dos tópicos do roteiro veio sem título, e ele é o texto do "
            "painel daquela parte; abortando sem publicar."
        )

    largura_quadro, altura_quadro = tela
    margem_x = round(largura_quadro * MARGEM_X_FRAC)
    largura_max = round(largura_quadro * LARGURA_MAX_FRAC)
    base = round(altura_quadro * BASE_FRAC)
    cor = ident.DESTAQUES[0]  # uma cor por canal, estável em todo o vídeo
    rubrica = RUBRICAS.get(cfg.publico, RUBRICAS["brasil"])

    # Os três painéis de pauta são desenhados duas vezes: a primeira mede, a
    # segunda iguala a altura de todos. Painel de altura variável faz a troca
    # saltar, porque a âncora é a base.
    def _desenhar_pautas(altura_minima: int) -> list[tuple[Path, int, int]]:
        return [
            _painel_pauta(
                titulo,
                f"{k:02d}",
                pasta / f"painel_pauta_{k}.png",
                altura_quadro,
                largura_max,
                cor,
                altura_minima,
            )
            for k, titulo in enumerate(titulos, 1)
        ]

    desenhos = _desenhar_pautas(0)
    alvo = max(alt for _, _, alt in desenhos)
    if any(alt != alvo for _, _, alt in desenhos):
        desenhos = _desenhar_pautas(alvo)
    desenhos.insert(
        0,
        _painel_indice(
            titulos,
            rubrica,
            pasta / "painel_indice.png",
            altura_quadro,
            largura_max,
            cor,
        ),
    )

    paineis = [
        {
            "imagem": str(caminho),
            "x": margem_x,
            "y": max(0, base - alt),
            "largura": larg,
            "altura": alt,
        }
        for caminho, larg, alt in desenhos
    ]

    # Bordas: a parte nova começa no INÍCIO do silêncio.
    bordas = [0.0, *(inicio for inicio, _ in pausas), duracao]
    rotulos = ["abertura", *(f"pauta {k}" for k in range(1, len(titulos) + 1))]
    nomes = [rubrica, *titulos]

    partes: list[dict] = []
    for i in range(len(bordas) - 1):
        inicio, fim = bordas[i], bordas[i + 1]
        if fim - inicio <= 0:
            raise SystemExit(
                f"A parte '{rotulos[i]}' do vídeo longo ficaria com "
                f"{fim - inicio:.2f}s — as viradas de pauta saíram fora de "
                "ordem na narração; abortando sem publicar."
            )
        # FAIXA DE DURAÇÃO DAS PARTES (2026-08-26). Antes daqui só saía um
        # aviso no log, com piso de 6s, e ele nem chegou a disparar no vídeo
        # que motivou esta conferência (pauta 1 de 10,2s debaixo de uma
        # abertura de 45,4s). Aviso em log não segura nada: o cron roda
        # sozinho, ninguém lê, e o vídeo sobe. Agora aborta.
        #
        # É a rede de BAIXO. Quem deveria pegar isto é
        # `escritor._falhas_de_estrutura`, que mede em palavras antes da
        # narração e ainda tem reescrita; se chegou aqui, o texto passou no
        # orçamento de palavras e mesmo assim o áudio saiu fora da faixa —
        # ritmo do TTS. Cair aqui custa a narração já paga, e é o preço de não
        # publicar o vídeo errado.
        if i == 0 and fim - inicio > LONGO_ABERTURA_MAX_S:
            raise SystemExit(
                f"A abertura ficou com {fim - inicio:.1f}s e o teto é "
                f"{LONGO_ABERTURA_MAX_S:.0f}s (o desenho pede ~"
                f"{LONGO_ABERTURA_S:.0f}s). A abertura é TUDO que vem antes da "
                "citação do tópico 1, então uma citação copiada do meio do "
                "bloco dele faz o índice 'ainda neste vídeo' ficar na tela "
                "enquanto a narração já conta a primeira pauta, e a manchete "
                "dela entrar quando a história acabou; abortando sem publicar."
            )
        if i and fim - inicio < LONGO_PAUTA_MIN_S:
            raise SystemExit(
                f"A parte '{rotulos[i]}' ficou com {fim - inicio:.1f}s e o "
                f"piso é {LONGO_PAUTA_MIN_S:.0f}s — o roteiro distribuiu mal o "
                "texto entre as pautas, e uma pauta curta demais é a manchete "
                "dela aparecendo depois de a história já ter sido contada "
                "debaixo do painel da parte anterior; abortando sem publicar."
            )
        partes.append(
            {
                "indice": i,
                "rotulo": rotulos[i],
                "titulo": nomes[i],
                "inicio_s": round(inicio, 3),
                "fim_s": round(fim, 3),
                # Silêncio no COMEÇO desta parte, onde a troca de painel
                # acontece. A abertura não tem: ela começa com o painel
                # entrando sobre a primeira palavra.
                "pausa_s": (
                    round(pausas[i - 1][1] - pausas[i - 1][0], 3) if i else 0.0
                ),
                "painel": paineis[i],
                "painel_saindo": paineis[i - 1] if i else None,
            }
        )

    (pasta / "partes.json").write_text(
        json.dumps(partes, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    for parte in partes:
        print(
            f"[partes] {parte['rotulo']}: {parte['inicio_s']:.1f}s -> "
            f"{parte['fim_s']:.1f}s ({parte['fim_s'] - parte['inicio_s']:.1f}s)"
            f" - {parte['titulo']}"
        )
    return partes
