"""Capa do vídeo longo: montagem editorial em cima de um quadro real do vídeo.

A capa que o YouTube escolhe sozinho é um quadro qualquer — costuma cair num
frame borrado da transição. Até 2026-08-23 a nossa não era muito melhor: um
quadro escurecido por inteiro com uma tarja preta e uma frase branca. Lia bem e
não chamava ninguém: nenhuma cor, nenhum ponto de foco, nada que separasse o
vídeo dos outros vinte da mesma linha de resultados.

A CAPA AGORA É UMA MONTAGEM (2026-08-23, pedido do usuário), na mesma
identidade das manchetes do vídeo (identidade.py: aranhaverso sobre editorial
minimalista):

- FUNDO DESFOCADO e dessaturado, com um RECORTE NÍTIDO do assunto por cima,
  cercado por uma BORDA BRANCA grossa e uma segunda borda de cor deslocada (a
  desregistragem de impressão);
- um CÍRCULO FEITO À MÃO em volta do recorte e uma SETA TORTA apontando para
  ele — o rabisco de quem marcou a foto, que é o que faz o olho parar;
- RETÍCULA Ben-Day num canto e o texto em Archivo Black com fantasma
  ciano/magenta, uma palavra dentro de um BLOCO DE COR chapado.

ONDE FICA O ASSUNTO é decidido por VISÃO, não chutado: a mesma chamada que
escreve o texto recebe três quadros candidatos do vídeo já montado, escolhe o
melhor, devolve a caixa do que interessa nele e diz qual palavra do texto vai
no bloco de cor. Sem isso o círculo cairia no meio de um fundo vazio, que é
pior do que não ter círculo nenhum. Falha da visão cai num enquadramento
central e no primeiro quadro — a capa sai mais fraca, nunca quebrada.

O texto continua com as duas regras duras de sempre: ele diz o FATO, não
provoca ("GOOGLE CORTA 8 MIL VAGAS" chama mais atenção do que "VOCÊ NÃO VAI
ACREDITAR" e não queima a confiança de quem clica), e sai no IDIOMA DO CANAL —
português no brasileiro, inglês no americano —, que é dado do pipeline
(``cfg.publico``) e não coisa a deduzir do título.

Desde 2026-08-07 o modelo também recebe os TÍTULOS dos vídeos que outros canais
publicaram hoje sobre o mesmo assunto (``seo.py``): a capa é o que separa o
nosso vídeo dos deles numa linha de resultados, e repetir o recorte que todos
já usaram é a forma mais cara de desaparecer. Diferenciar aqui é escolher outro
fato VERDADEIRO do próprio vídeo — a regra de dizer o fato continua acima de
tudo.

Falha aqui NÃO aborta: o vídeo já está montado e publicar sem capa customizada
é muito melhor do que não publicar.
"""

import base64
import json
import subprocess
from pathlib import Path

from openai import OpenAI
from PIL import Image, ImageDraw, ImageEnhance

from . import identidade as ident
from .config import (
    AVISO_DADOS_EXTERNOS,
    Config,
    idioma_plausivel,
    nome_do_idioma,
)

# O YouTube aceita até 2 MB e recomenda 1280x720.
LARGURA, ALTURA = 1280, 720
MAX_BYTES = 2_000_000

MAX_PALAVRAS = 5
MAX_CARACTERES = 34  # acima disso a fonte encolhe demais para ler no celular

# QUADROS CANDIDATOS: frações da duração do vídeo de onde sai cada quadro que a
# visão avalia. Nunca no comecinho (crossfade de abertura) nem no fim (a
# conclusão é falada sobre o último clipe, que raramente é o mais forte).
INSTANTES_FRAC = (0.10, 0.38, 0.66)
LADO_VISAO = 768  # lado maior do JPEG mandado para a visão (custo por imagem)

# IDIOMA DA CAPA — determinado pelo CANAL, nunca inferido (2026-08-04).
# O prompt antigo era escrito em português e pedia "no MESMO IDIOMA do título
# que receber": o modelo tinha que deduzir o idioma de um sinal fraco (o
# título) contra um sinal forte (o prompt inteiro em português) e, com o
# TEXT_MODEL menor que roda em produção, deduziu errado — o último vídeo longo
# do canal americano saiu com a capa "GOOGLE LEVA ROBÔS AO CORPO" em cima de um
# vídeo narrado em inglês. Idioma do canal é dado do pipeline (cfg.publico),
# não coisa a adivinhar: agora ele entra explícito na instrução e o texto
# devolvido é verificado em código (`idioma_plausivel`, em config.py).
#
# O nome do idioma e a checagem vivem em config.py porque valem para o canal
# inteiro; aqui ficam só a regra e os exemplos ESPECÍFICOS da capa.
IDIOMAS = {
    "brasil": {
        "regra": (
            "Escreva EXCLUSIVAMENTE em PORTUGUÊS DO BRASIL. Uma capa em "
            "inglês neste canal está ERRADA, mesmo que o assunto seja "
            "americano e mesmo que o título tenha nomes em inglês."
        ),
        "exemplos": (
            '"GOOGLE CORTA 8 MIL VAGAS", "PETRÓLEO CAI 11%", '
            '"APPLE PASSA A NVIDIA"'
        ),
    },
    "usa": {
        "regra": (
            "Write EXCLUSIVELY in AMERICAN ENGLISH. A Portuguese cover on "
            "this channel is WRONG, no matter what language the source posts "
            "or the news articles were written in."
        ),
        "exemplos": (
            '"GOOGLE CUTS 8,000 JOBS", "OIL DROPS 11%", '
            '"APPLE PASSES NVIDIA"'
        ),
    },
}

# --- Geometria da montagem (frações da capa) ---------------------------------
MARGEM_FRAC = 0.045
TEXTO_FRAC = 0.135  # altura da fonte do texto, fração da altura da capa
ENTRELINHA = 1.10
TEXTO_LARGURA_FRAC = 0.66  # largura máxima do bloco de texto
BORDA_RECORTE = 10  # espessura da borda branca em volta do recorte
FOCO_MIN_FRAC = 0.16  # menor lado aceito para a caixa do assunto
FOCO_MAX_FRAC = 0.70  # acima disso não é destaque, é a capa inteira
TRACO = 9  # espessura do círculo e da seta feitos à mão

ESQUEMA = {
    "name": "capa_do_video",
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
            },
            "palavra_destacada": {
                "type": "string",
                "description": (
                    "UMA palavra de 'texto', copiada exatamente, que vai num "
                    "bloco de cor chapado. Escolha a que carrega o fato — o "
                    "número, o valor ou o verbo da ação. String vazia se "
                    "nenhuma se destaca."
                ),
            },
            "quadro": {
                "type": "integer",
                "description": (
                    "Número do quadro escolhido (1, 2 ou 3): o que tem o "
                    "assunto mais reconhecível e legível como miniatura."
                ),
            },
            "foco": {
                "type": "object",
                "additionalProperties": False,
                "description": (
                    "Caixa do que interessa NO QUADRO ESCOLHIDO, em frações de "
                    "0 a 1 (x e y do canto superior esquerdo, largura e "
                    "altura). É essa região que sai nítida e circulada a mão "
                    "na capa: enquadre a pessoa, o produto ou o objeto do "
                    "fato, com uma folga pequena, NUNCA a imagem inteira."
                ),
                "properties": {
                    "x": {"type": "number"},
                    "y": {"type": "number"},
                    "largura": {"type": "number"},
                    "altura": {"type": "number"},
                },
                "required": ["x", "y", "largura", "altura"],
            },
        },
        "required": ["texto", "palavra_destacada", "quadro", "foco"],
    },
}

INSTRUCOES = """\
Você monta a CAPA (thumbnail) de um vídeo de notícias. Recebe o título, a
narração e TRÊS QUADROS do vídeo já montado, na ordem, e devolve o texto da
capa mais as decisões visuais dela.

IDIOMA — A REGRA QUE MANDA EM TODAS AS OUTRAS: o canal deste vídeo publica em
{idioma}. {regra}

TEXTO: de 2 a {max_palavras} palavras, no máximo {max_caracteres} caracteres,
em MAIÚSCULAS.

O texto tem que dizer O FATO, de forma que alguém que não conhece o assunto
entenda o que aconteceu só de bater o olho. Nome próprio conhecido ajuda, e
número concreto ajuda mais ainda.

NÃO use: pergunta, reticências, "veja", "urgente", "chocante", "você não vai
acreditar", nem qualquer promessa que a capa não cumpra. Curiosidade fabricada
traz clique e perde a audiência no primeiro segundo — o que retém é o fato.

Exemplos do que funciona neste canal: {exemplos}.
Exemplos do que NÃO funciona: "O QUE NINGUÉM TE CONTOU", "ISSO MUDA TUDO",
"ATENÇÃO: URGENTE".

PALAVRA DESTACADA: uma palavra do próprio texto, copiada igual, que vai sair
dentro de um bloco de cor chapado. Escolha a que CARREGA O FATO — o número, o
valor em dinheiro ou o verbo da ação —, nunca um artigo, uma preposição ou um
nome próprio comprido.

QUADRO: escolha entre os três o que tem o assunto mais RECONHECÍVEL — rosto
inteiro, produto, lugar, objeto do fato — e que continua legível reduzido ao
tamanho de uma miniatura de celular. Descarte quadro borrado, escuro demais,
com o rosto cortado ou com a cena vazia.

FOCO: no quadro escolhido, a caixa do que interessa (x, y, largura, altura em
frações de 0 a 1, medidas da borda superior esquerda). Na capa, essa região sai
NÍTIDA sobre o resto desfocado, com borda branca, um círculo desenhado à mão em
volta e uma seta apontando para ela. Enquadre o assunto com uma folga pequena:
uma caixa que pega a imagem inteira não destaca nada, e uma caixa minúscula
vira um selo ilegível. Se não houver assunto claro, devolva a região central.

CONCORRÊNCIA DO DIA — quando vier a lista de vídeos já publicados hoje sobre
este mesmo assunto, eles são o que vai aparecer na mesma linha de resultados
que o nosso. A capa é o que diferencia: NÃO repita o recorte que todos já
usaram. Se os títulos deles giram todos em torno do anúncio, a capa traz o
NÚMERO; se todos trazem o número, a capa traz quem ganha ou quem paga. O fato
continua sendo obrigatório — diferenciar é escolher OUTRO fato verdadeiro do
vídeo, nunca inventar um.

Responda somente com o JSON pedido, com o texto em {idioma}.\
"""


def _instrucoes(publico: str) -> str:
    idioma = IDIOMAS.get(publico, IDIOMAS["brasil"])
    return INSTRUCOES.format(
        idioma=nome_do_idioma(publico),
        regra=idioma["regra"],
        exemplos=idioma["exemplos"],
        max_palavras=MAX_PALAVRAS,
        max_caracteres=MAX_CARACTERES,
    )


# ---- Quadros do vídeo -------------------------------------------------------


def _duracao(video: Path) -> float:
    try:
        saida = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video)],
            check=True, capture_output=True, text=True,
        )
        return float((saida.stdout or "0").strip())
    except (subprocess.CalledProcessError, OSError, ValueError):
        return 0.0


def _quadro_do_video(video: Path, destino: Path, instante: float) -> Path | None:
    """Extrai um quadro do vídeo já montado, no tamanho da capa."""
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


def _candidatos(video: Path, pasta: Path) -> list[Path]:
    """Os quadros que a visão vai comparar; lista vazia se nenhum sair."""
    dur = _duracao(video)
    if dur <= 0:
        quadro = _quadro_do_video(video, pasta / "thumb_quadro_1.png", 2.0)
        return [quadro] if quadro else []
    instantes = [max(1.5, dur * f) for f in INSTANTES_FRAC]
    quadros = []
    for k, instante in enumerate(instantes, 1):
        quadro = _quadro_do_video(video, pasta / f"thumb_quadro_{k}.png", instante)
        if quadro:
            quadros.append(quadro)
    return quadros


def _data_uri(caminho: Path, pasta: Path) -> str:
    """JPEG reduzido do quadro, em data URI — a visão não precisa do 720p."""
    reduzido = pasta / f"{caminho.stem}_visao.jpg"
    try:
        with Image.open(caminho) as img:
            copia = img.convert("RGB")
            copia.thumbnail((LADO_VISAO, LADO_VISAO), Image.LANCZOS)
            copia.save(reduzido, "JPEG", quality=82)
        dados = base64.b64encode(reduzido.read_bytes()).decode()
    except OSError:
        dados = base64.b64encode(caminho.read_bytes()).decode()
        return f"data:image/png;base64,{dados}"
    return f"data:image/jpeg;base64,{dados}"


# ---- Decisões da capa (texto + visão) ---------------------------------------


def _foco_padrao() -> dict:
    """Caixa central — o que vale quando a visão não responde."""
    return {"x": 0.30, "y": 0.18, "largura": 0.40, "altura": 0.52}


def _decidir(
    cfg: Config,
    titulo: str,
    narracao: str,
    quadros: list[Path],
    pasta: Path,
    titulos_do_dia: list[str] | None = None,
) -> dict:
    """Texto, quadro e enquadramento da capa; cai no título se o GPT falha.

    O idioma vem de ``cfg.publico`` (o canal), nunca da inferência do modelo —
    ver o comentário de IDIOMAS. Quando a resposta sai no idioma errado, uma
    segunda chamada cobra a correção; se ela também sair errada, o título do
    vídeo (que já está no idioma certo, garantido por FOCO_USA/FOCO_BRASIL no
    escritor) vira a capa.

    `titulos_do_dia` são os títulos dos vídeos que outros canais publicaram
    hoje sobre o mesmo assunto (``seo.titulos_do_dia``). A capa disputa o
    clique lado a lado com eles na busca, então ela precisa dizer outra coisa —
    outro fato verdadeiro do mesmo vídeo, nunca um fato inventado.
    """
    reserva = {
        "texto": " ".join(titulo.split()[:MAX_PALAVRAS]).upper(),
        "palavra_destacada": "",
        "quadro": 1,
        "foco": _foco_padrao(),
    }
    concorrencia = ""
    if titulos_do_dia:
        concorrencia = (
            "\n\nJÁ PUBLICADOS HOJE SOBRE O MESMO ASSUNTO (a capa precisa se "
            "diferenciar destes):\n"
            + "\n".join(f"- {t}" for t in titulos_do_dia)
        )
    conteudo = [
        {"type": "text", "text": AVISO_DADOS_EXTERNOS},
        {
            "type": "text",
            "text": (
                f"TÍTULO: {titulo}\n\nNARRAÇÃO:\n{narracao}{concorrencia}\n\n"
                f"Os {len(quadros)} quadros a seguir estão na ordem "
                f"(1 a {len(quadros)})."
            ),
        },
    ] + [
        {"type": "image_url", "image_url": {"url": _data_uri(q, pasta)}}
        for q in quadros
    ]

    try:
        cliente = OpenAI(api_key=cfg.openai_api_key)
        mensagens = [
            {"role": "system", "content": _instrucoes(cfg.publico)},
            {"role": "user", "content": conteudo},
        ]
        resposta = cliente.chat.completions.create(
            model=cfg.text_model,
            messages=mensagens,
            response_format={"type": "json_schema", "json_schema": ESQUEMA},
        )
        decisao = json.loads(resposta.choices[0].message.content)

        if decisao.get("texto") and not idioma_plausivel(
            decisao["texto"], cfg.publico
        ):
            idioma = nome_do_idioma(cfg.publico)
            print(
                f"[thumbnail] aviso: capa \"{decisao['texto']}\" saiu fora do "
                f"idioma do canal ({idioma}); pedindo correção."
            )
            resposta = cliente.chat.completions.create(
                model=cfg.text_model,
                messages=mensagens
                + [
                    {
                        "role": "assistant",
                        "content": resposta.choices[0].message.content,
                    },
                    {
                        "role": "user",
                        "content": (
                            f"O texto saiu no idioma errado. Reescreva a capa "
                            f"em {idioma}, mantendo o mesmo fato, o mesmo "
                            "quadro e o mesmo foco."
                        ),
                    },
                ],
                response_format={"type": "json_schema", "json_schema": ESQUEMA},
            )
            corrigida = json.loads(resposta.choices[0].message.content)
            if corrigida.get("texto") and idioma_plausivel(
                corrigida["texto"], cfg.publico
            ):
                decisao = corrigida
            else:
                print(
                    "[thumbnail] aviso: a correção também saiu fora do idioma; "
                    "usando o título do vídeo."
                )
                return reserva
    except Exception as erro:  # noqa: BLE001 — capa não vale abortar publicação
        print(f"[thumbnail] aviso: GPT falhou ({erro}); usando o título.")
        return reserva

    texto = " ".join((decisao.get("texto") or "").split()).upper()
    if not texto:
        return reserva
    decisao["texto"] = " ".join(texto.split()[:MAX_PALAVRAS])

    destaque = " ".join((decisao.get("palavra_destacada") or "").split()).upper()
    palavras = decisao["texto"].split()
    decisao["palavra_destacada"] = destaque if destaque in palavras else ""

    try:
        indice = int(decisao.get("quadro") or 1)
    except (TypeError, ValueError):
        indice = 1
    decisao["quadro"] = indice if 1 <= indice <= len(quadros) else 1

    decisao["foco"] = _sanear_foco(decisao.get("foco"))
    return decisao


def _sanear_foco(foco: dict | None) -> dict:
    """Caixa do assunto dentro de limites úteis, em frações de 0 a 1.

    A visão às vezes devolve a imagem inteira (destaque que não destaca nada) ou
    um selo minúsculo, e às vezes uma caixa que vaza a borda. Aqui ela é
    fechada nos dois extremos em vez de descartada: uma caixa exagerada ainda
    diz de que LADO da imagem está o assunto, que é a parte que mais importa
    para a montagem.
    """
    padrao = _foco_padrao()
    if not isinstance(foco, dict):
        return padrao
    try:
        x = float(foco.get("x", padrao["x"]))
        y = float(foco.get("y", padrao["y"]))
        largura = float(foco.get("largura", padrao["largura"]))
        altura = float(foco.get("altura", padrao["altura"]))
    except (TypeError, ValueError):
        return padrao
    largura = min(max(largura, FOCO_MIN_FRAC), FOCO_MAX_FRAC)
    altura = min(max(altura, FOCO_MIN_FRAC), FOCO_MAX_FRAC)
    x = min(max(x, 0.0), 1.0 - largura)
    y = min(max(y, 0.0), 1.0 - altura)
    return {"x": x, "y": y, "largura": largura, "altura": altura}


# ---- Montagem (Pillow) ------------------------------------------------------


def _caixa_em_pixels(foco: dict) -> tuple[int, int, int, int]:
    x0 = int(foco["x"] * LARGURA)
    y0 = int(foco["y"] * ALTURA)
    x1 = min(LARGURA, x0 + int(foco["largura"] * LARGURA))
    y1 = min(ALTURA, y0 + int(foco["altura"] * ALTURA))
    return x0, y0, x1, y1


def _bloco_de_texto(
    tela: Image.Image, texto: str, destaque: str, cor: tuple,
    caixa_foco: tuple[int, int, int, int],
) -> None:
    """Escreve o texto da capa no canto mais livre, com a palavra em bloco.

    O texto NUNCA vai por cima do recorte: se a caixa do assunto ocupa a base,
    o bloco sobe para o topo. Capa em que o texto tapa justamente o rosto que a
    montagem destacou é pior do que a capa antiga.
    """
    dr = ImageDraw.Draw(tela, "RGBA")
    margem = round(LARGURA * MARGEM_FRAC)
    largura_util = round(LARGURA * TEXTO_LARGURA_FRAC)

    # Em cima ou embaixo: fica no lado em que sobra mais espaço livre do
    # recorte. Texto por cima do rosto que a montagem acabou de destacar é
    # pior do que a capa antiga.
    _, y0_foco, _, y1_foco = caixa_foco
    embaixo = (ALTURA - y1_foco) >= y0_foco
    # E encolhe até caber nesse espaço. O piso existe porque capa ilegível na
    # miniatura não serve para nada: com o recorte tomando quase tudo, é melhor
    # o texto encostar nele do que virar uma linha de formiga.
    livre = max(
        (ALTURA - y1_foco) if embaixo else y0_foco, round(ALTURA * 0.30)
    ) - margem - round(ALTURA * 0.025)  # folga do bloco de cor da palavra

    minimo = round(ALTURA * 0.075)
    tamanho = round(ALTURA * TEXTO_FRAC)
    while True:
        fonte, linhas = ident.caber(
            dr, texto, largura_util, tamanho, minimo=minimo, maximo_linhas=2
        )
        alt_linha = round(fonte.size * ENTRELINHA)
        bloco = alt_linha * len(linhas)
        if bloco <= livre or fonte.size <= minimo:
            break
        tamanho = int(fonte.size * 0.92)

    topo = ALTURA - margem - bloco if embaixo else margem
    ident.sombra_de_base(
        tela,
        altura_frac=min(0.60, (bloco + 2 * margem) / ALTURA),
        no_topo=not embaixo,
    )

    y = topo
    for linha in linhas:
        x = margem
        for palavra in linha.split():
            largura_palavra = dr.textlength(palavra, font=fonte)
            if destaque and palavra == destaque:
                # Bloco chapado com retícula: a palavra do fato vira etiqueta.
                folga = round(fonte.size * 0.16)
                caixa = (
                    x - folga, y - folga * 0.5,
                    x + largura_palavra + folga, y + fonte.size + folga * 0.9,
                )
                dr.rectangle(caixa, fill=(*cor, 255))
                ident.reticula(
                    tela, tuple(int(v) for v in caixa), cor=ident.PRETO,
                    passo=max(8, round(fonte.size * 0.16)),
                    raio=max(1, round(fonte.size * 0.03)), alfa=70,
                )
                ImageDraw.Draw(tela, "RGBA").text(
                    (x, y), palavra, font=fonte, fill=ident.PRETO
                )
                destaque = ""  # uma vez só, mesmo se a palavra se repetir
            else:
                ident.escrever_cromatico(
                    tela, (x, y), palavra, fonte, ident.BRANCO, contorno=
                    max(2, round(fonte.size / 16)),
                )
            x += largura_palavra + dr.textlength(" ", font=fonte)
        y += alt_linha


def _montar(quadro: Path, decisao: dict, destino: Path) -> Path:
    """Compõe a capa inteira a partir do quadro e das decisões da visão."""
    cor = ident.destaque_por(decisao["texto"])
    sem = ident.semente(decisao["texto"])

    with Image.open(quadro) as bruta:
        base = bruta.convert("RGB").resize((LARGURA, ALTURA), Image.LANCZOS)
    # Mais cor, não menos: a capa antiga escurecia o quadro inteiro para o texto
    # ler, e o que sobrava era cinza. Agora o contraste vem do desfoque e do
    # degradê — o quadro pode ficar saturado.
    base = ImageEnhance.Color(base).enhance(1.28)
    base = ImageEnhance.Contrast(base).enhance(1.12)

    tela = ident.desfocar_fundo(base).convert("RGBA")

    x0, y0, x1, y1 = _caixa_em_pixels(decisao["foco"])
    # Retícula só no canto de cima OPOSTO ao recorte: textura de impressão onde
    # não há nada acontecendo. Numa faixa que atravessa a capa inteira ela para
    # de ler como trama e passa a parecer sujeira no fundo.
    if (x0 + x1) / 2 > LARGURA / 2:
        canto = (0, 0, round(LARGURA * 0.42), round(ALTURA * 0.32))
    else:
        canto = (round(LARGURA * 0.58), 0, LARGURA, round(ALTURA * 0.32))
    ident.reticula(tela, canto, cor=ident.BRANCO, passo=18, raio=3, alfa=26)
    recorte = base.crop((x0, y0, x1, y1))
    # Sombra difusa sob o recorte: é ela que descola o assunto do fundo.
    ident.sombra_projetada(tela, (x0, y0, x1, y1))
    tela.paste(recorte, (x0, y0))
    ident.moldura_recorte(tela, (x0, y0, x1, y1), cor, borda=BORDA_RECORTE)

    # Círculo à mão em volta do recorte, com folga para não encostar na borda.
    folga = round(min(x1 - x0, y1 - y0) * 0.10) + BORDA_RECORTE
    ident.circulo_a_mao(
        tela,
        (max(2, x0 - folga), max(2, y0 - folga),
         min(LARGURA - 2, x1 + folga), min(ALTURA - 2, y1 + folga)),
        cor, largura=TRACO, sem=sem,
    )

    # Seta partindo do canto mais vazio (o oposto ao recorte) até a borda dele.
    centro_x = (x0 + x1) / 2
    da_esquerda = centro_x > LARGURA / 2
    origem = (
        (LARGURA * 0.10, ALTURA * 0.22) if da_esquerda
        else (LARGURA * 0.90, ALTURA * 0.22)
    )
    alvo = (
        (x0 - folga * 0.6, y0 + (y1 - y0) * 0.30) if da_esquerda
        else (x1 + folga * 0.6, y0 + (y1 - y0) * 0.30)
    )
    ident.seta_a_mao(tela, origem, alvo, cor, largura=TRACO, sem=sem)

    _bloco_de_texto(
        tela, decisao["texto"], decisao.get("palavra_destacada") or "", cor,
        (x0, y0, x1, y1),
    )

    final = tela.convert("RGB")
    qualidade = 92
    final.save(destino, "JPEG", quality=qualidade)
    while destino.stat().st_size > MAX_BYTES and qualidade > 40:
        qualidade -= 10
        final.save(destino, "JPEG", quality=qualidade)
    return destino


def gerar_thumbnail(
    cfg: Config,
    video: Path,
    titulo: str,
    narracao: str,
    pasta: Path,
    titulos_do_dia: list[str] | None = None,
) -> Path | None:
    """Monta a capa e devolve o caminho; None se não foi possível.

    `titulos_do_dia` é a concorrência real daquele assunto no YouTube de hoje
    (``seo.titulos_do_dia``), usada para a capa não repetir o recorte que todo
    mundo já ocupou.
    """
    if not ident.fonte_disponivel():
        print(f"[thumbnail] aviso: fonte ausente ({ident.FONTE_TITULO}); sem capa.")
        return None

    quadros = _candidatos(video, pasta)
    if not quadros:
        return None

    decisao = _decidir(cfg, titulo, narracao, quadros, pasta, titulos_do_dia)
    quadro = quadros[min(decisao["quadro"], len(quadros)) - 1]
    print(
        f"[thumbnail] Texto da capa: {decisao['texto']} "
        f"(quadro {decisao['quadro']}/{len(quadros)}"
        + (
            f", destaque \"{decisao['palavra_destacada']}\""
            if decisao.get("palavra_destacada")
            else ""
        )
        + ")"
    )

    destino = pasta / "thumbnail.jpg"
    try:
        _montar(quadro, decisao, destino)
    except Exception as erro:  # noqa: BLE001 — capa não vale abortar publicação
        print(f"[thumbnail] aviso: montagem falhou ({erro}); sem capa.")
        return None
    (pasta / "thumbnail.json").write_text(
        json.dumps(decisao, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[thumbnail] Capa salva em {destino} ({destino.stat().st_size} bytes)")
    return destino
