"""Figuras geradas por IA (gpt-image-2) sobrepostas ao vídeo: gráficos,
tabelas, infográficos, diagramas e cartazes.

O corpo do vídeo continua sendo SÓ clipe de vídeo do X — a regra de que imagem
estática não ocupa a tela segue valendo. A figura é outra coisa: um cartão que
ENTRA POR CIMA do clipe no instante em que a narração diz o dado que ela
desenha, e sai. Mesma família visual das cartelas (cartelas.py) e dos
infográficos animados (grafico.py), com uma diferença de origem: aqui a imagem
não vem de lugar nenhum do mundo real — ela é DESENHADA a partir dos números
que a própria narração já falou.

Por que a IA e não o Pillow: grafico.py já desenha, com precisão perfeita,
contador e barra comparativa. O que ele não desenha é tabela, linha do tempo,
diagrama de fluxo, mapa de mercado e cartaz — e é justamente esse repertório
que um vídeo de análise sobre tecnologia, mercado de trabalho e mercado
financeiro pede. O gpt-image-2 cobre esse repertório.

O QUE ENTRA NA FIGURA É SÓ O QUE A NARRAÇÃO DISSE: cada figura é ancorada numa
CITAÇÃO LITERAL do texto narrado, e os rótulos e valores desenhados são os que
o modelo extraiu daquele trecho. Isso não é preciosismo — é o que impede o
vídeo de exibir na tela um número que ninguém falou.

ANIMAÇÃO (pedido do usuário): a figura SOBE suavemente de baixo do quadro até
a posição de leitura, fica parada enquanto é lida, e SAI POR CIMA do quadro.
Entrada e saída são movimentos de direção única — a figura atravessa a tela de
baixo para cima ao longo da vida dela.

Etapa opcional: qualquer falha (OpenAI, rede, Pillow, citação não encontrada)
só deixa o vídeo sem figuras — nunca derruba o pipeline.
"""

import base64
import json
from pathlib import Path

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, RAIZ, Config
from .cortes import _tempo_do_char
from .edicao import FPS

FONTE_FIGURA = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"

DUR_FIGURA = 4.0  # s; tempo-alvo de cada figura na tela (leitura de gráfico)
DUR_MINIMA = 2.6  # s; menos que isto não dá para ler uma tabela
GAP_FIGURAS = 1.2  # s; respiro mínimo entre figuras e para as outras camadas
# O gancho decide o swipe: os primeiros segundos ficam com o clipe limpo.
INICIO_MINIMO = 3.0

# Movimento: entra subindo de baixo do quadro, sai por cima do quadro.
T_ENTRADA = 0.55  # s; sobe de fora da tela até a posição de leitura
T_SAIDA = 0.50  # s; continua subindo até sumir acima do quadro

BRANCO = (255, 255, 255)
PRETO = (14, 14, 14)
CINZA_FONTE = (90, 90, 90)

# Tamanhos aceitos pelo gpt-image-2 (arestas múltiplas de 16, proporção até
# 3:1, total de pixels dentro da faixa permitida). Retrato para o Short,
# paisagem para o formato longo.
TAMANHO_VERTICAL = "1024x1536"
TAMANHO_HORIZONTAL = "1536x1024"

TIPOS = [
    "grafico_barras",
    "grafico_linha",
    "tabela",
    "infografico",
    "diagrama",
    "cartaz",
]

# Estilo visual fixo, aplicado a toda figura. Fica em código (e não a cargo do
# modelo de texto) porque identidade visual não pode variar de vídeo para
# vídeo: o canal precisa que duas figuras de dois vídeos diferentes pareçam do
# mesmo lugar.
ESTILO = (
    "Flat editorial data-visualization graphic, minimalist infographic poster "
    "style. Pure white background, generous margins, no photographic elements, "
    "no 3D, no gradients, no drop shadows, no glossy effects. Strong geometric "
    "shapes in a restrained palette: near-black (#111111) for structure and "
    "type, one single accent color (deep orange #E8590C) used only to "
    "highlight the most important value. Heavy grotesque sans-serif "
    "typography, very large and perfectly legible. Absolutely no watermark, no "
    "logo, no brand mark, no signature, no stock-photo artifacts, no human "
    "faces, no news-channel lower third."
)

# Regra dura de texto: o gpt-image-2 melhorou muito em tipografia, mas ainda
# erra colocação e ortografia quando o cartaz é cheio. Menos texto = menos
# chance de sair um rótulo torto ou uma palavra inventada na tela.
REGRAS_TEXTO = (
    "Render ONLY the exact labels and values listed below, spelled exactly as "
    "given, and nothing else. Do not invent extra numbers, axis ticks, legends, "
    "footnotes, captions or decorative words. Keep the total amount of text "
    "very small. Every character must be crisp and readable at small size on a "
    "phone screen."
)

ESQUEMA_FIGURAS = {
    "name": "figuras_do_video",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "figuras": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "trecho": {
                            "type": "string",
                            "description": (
                                "Citação EXATA e curta (3 a 8 palavras "
                                "consecutivas) da narração, copiada caractere "
                                "por caractere, marcando o momento em que a "
                                "figura entra — o instante em que o dado é "
                                "falado."
                            ),
                        },
                        "tipo": {
                            "type": "string",
                            "enum": TIPOS,
                            "description": (
                                "A forma que melhor mostra ESTE dado: "
                                "grafico_barras (comparar quantidades), "
                                "grafico_linha (evolução no tempo), tabela "
                                "(3 a 4 itens com 2 colunas), infografico "
                                "(uma relação ou proporção), diagrama (uma "
                                "cadeia de causa e efeito), cartaz (um único "
                                "número gigante com o rótulo)."
                            ),
                        },
                        "titulo": {
                            "type": "string",
                            "description": (
                                "Título da figura, no idioma da narração, no "
                                "máximo 6 palavras. É o que aparece escrito no "
                                "topo da imagem."
                            ),
                        },
                        "itens": {
                            "type": "array",
                            "description": (
                                "De 1 a 4 pares rótulo/valor que a figura "
                                "desenha. Os valores são os NÚMEROS QUE A "
                                "NARRAÇÃO DIZ, na mesma forma arredondada "
                                "('2 bilhões', '30%', '8 mil vagas'). Não "
                                "invente valor que não está na narração."
                            ),
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "rotulo": {
                                        "type": "string",
                                        "description": (
                                            "No máximo 3 palavras (ex.: "
                                            "'Vagas cortadas', '2024')."
                                        ),
                                    },
                                    "valor": {
                                        "type": "string",
                                        "description": (
                                            "O número ou a medida, curto "
                                            "(ex.: '21 mil', 'US$ 2 bi', "
                                            "'-30%')."
                                        ),
                                    },
                                },
                                "required": ["rotulo", "valor"],
                            },
                        },
                        "destaque": {
                            "type": "string",
                            "description": (
                                "O rótulo do item que deve receber a cor de "
                                "destaque (deve ser um dos rótulos de "
                                "'itens'); vazio se nenhum se destaca."
                            ),
                        },
                        "por_que": {
                            "type": "string",
                            "description": (
                                "Uma frase: o que o espectador entende olhando "
                                "esta figura que ele não entenderia só ouvindo."
                            ),
                        },
                    },
                    "required": [
                        "trecho",
                        "tipo",
                        "titulo",
                        "itens",
                        "destaque",
                        "por_que",
                    ],
                },
            },
        },
        "required": ["figuras"],
    },
}

INSTRUCOES_FIGURAS = """\
Você é o editor de INFOGRAFIA de um canal de vídeos de análise sobre
tecnologia, inteligência artificial, mercado de trabalho e mercado financeiro.

Você recebe a NARRAÇÃO de um vídeo e o material que a embasou (resumo da pauta
e notícias). Escolha até {maximo} MOMENTOS em que uma figura desenhada —
gráfico, tabela, infográfico, diagrama ou cartaz — aparece por cerca de
{duracao} segundos sobreposta ao vídeo.

A figura existe para uma coisa só: transformar em IMAGEM um dado que, falado,
passa batido. Número solto no meio de uma frase evapora; o mesmo número numa
barra ao lado de outra barra fica. Se o trecho não tem dado, não tem figura.

REGRAS:
1. "trecho" é citação LITERAL da narração (localizada por busca exata;
   paráfrase descarta a figura). Escolha o instante em que o dado é DITO — não
   antes, não depois.
2. Só entra dado que ESTÁ NA NARRAÇÃO. Os valores da figura são os mesmos que o
   espectador acabou de ouvir, na mesma forma arredondada. É PROIBIDO trazer
   número das notícias que a narração não diz: a tela mostrando um número que
   ninguém falou é o pior defeito possível aqui.
3. Escolha a FORMA pelo dado, não por estética: duas quantidades comparáveis
   pedem barras; uma série no tempo pede linha; três ou quatro itens com um
   atributo cada pedem tabela; uma cadeia de causa e efeito pede diagrama; um
   número único e brutal pede cartaz.
4. No máximo 4 itens por figura, com rótulos de até 3 palavras. Figura cheia
   não é lida em {duracao} segundos num celular.
5. Não repita o mesmo dado em duas figuras e não coloque duas figuras no mesmo
   trecho; espalhe pela narração.
6. NÃO escolha um trecho das primeiras frases: o gancho fica com o clipe limpo.
7. Menos é mais: devolva a lista VAZIA se a narração não tiver dado que renda
   figura. Vídeo sem figura é melhor que figura genérica.

Responda somente com o JSON pedido.\
"""


# ---- Prompt de imagem -------------------------------------------------------


DESCRICAO_TIPO = {
    "grafico_barras": (
        "A simple vertical bar chart comparing the values. Bars are solid "
        "rectangles of equal width with the value printed above each bar and "
        "the label printed below it. No axis lines, no grid, no legend."
    ),
    "grafico_linha": (
        "A single simple line chart showing the trend across the labels. One "
        "polyline with round dots at each point, the value printed next to "
        "each dot and the label below it. No grid, no axis numbers, no legend."
    ),
    "tabela": (
        "A clean two-column table: label on the left, value on the right, one "
        "row per item, separated by thin horizontal rules. No outer border, no "
        "zebra striping, no header row other than the title."
    ),
    "infografico": (
        "A minimal pictogram infographic: one bold geometric icon per item "
        "(square, circle, arrow or simple silhouette of an object) with the "
        "value in very large type next to it and the label underneath."
    ),
    "diagrama": (
        "A left-to-right flow diagram: one rounded box per item containing the "
        "label and, under it, the value, connected by thick straight arrows. "
        "No branching, no extra nodes."
    ),
    "cartaz": (
        "A poster with ONE enormous number filling most of the canvas, the "
        "short label directly underneath it in much smaller type, and nothing "
        "else."
    ),
}


def _prompt_imagem(figura: dict, vertical: bool) -> str:
    """Monta o prompt do gpt-image-2 para uma figura do plano."""
    itens = figura.get("itens") or []
    linhas = "\n".join(
        f'- label "{(i.get("rotulo") or "").strip()}" with value '
        f'"{(i.get("valor") or "").strip()}"'
        for i in itens
    )
    destaque = (figura.get("destaque") or "").strip()
    realce = (
        f'Use the accent color ONLY on the item labeled "{destaque}".'
        if destaque
        else "Use the accent color on at most one element."
    )
    forma = DESCRICAO_TIPO.get(figura["tipo"], DESCRICAO_TIPO["cartaz"])
    orientacao = (
        "Portrait composition, the content stacked vertically and centered."
        if vertical
        else "Landscape composition, the content spread horizontally."
    )
    return (
        f"{forma}\n\n"
        f'Title at the top, exactly: "{(figura.get("titulo") or "").strip()}"\n'
        f"Data to render:\n{linhas}\n\n"
        f"{realce}\n{orientacao}\n\n{ESTILO}\n\n{REGRAS_TEXTO}"
    )


def _gerar_imagem(cfg: Config, figura: dict, destino: Path, vertical: bool) -> Path | None:
    """Chama o gpt-image-2 e salva o PNG; None se a geração falhar."""
    cliente = OpenAI(api_key=cfg.openai_api_key)
    try:
        resposta = cliente.images.generate(
            model=cfg.imagem_model,
            prompt=_prompt_imagem(figura, vertical),
            size=TAMANHO_VERTICAL if vertical else TAMANHO_HORIZONTAL,
            quality=cfg.imagem_qualidade,
            n=1,
        )
        dados = resposta.data[0].b64_json
    except Exception as erro:  # noqa: BLE001 — figura nunca derruba o vídeo
        print(f"[figuras] Geração da imagem falhou ({erro}); figura pulada.")
        return None
    if not dados:
        print("[figuras] A API não devolveu imagem; figura pulada.")
        return None
    destino.write_bytes(base64.b64decode(dados))
    return destino


# ---- Planejamento -----------------------------------------------------------


def _planejar(
    cfg: Config, texto_video: str, trend: dict, noticias: list[dict], maximo: int
) -> list[dict]:
    contexto = (trend or {}).get("resumo", "")
    manchetes = "\n".join(
        f"- {(n.get('titulo') or '').strip()}" for n in (noticias or [])[:6]
    )
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO DO VÍDEO (é daqui que saem os dados):\n{texto_video}\n\n"
        f"CONTEXTO DA PAUTA (só para você entender o assunto — NÃO tire números "
        f"daqui):\n{contexto}\n{manchetes}"
    )
    cliente = OpenAI(api_key=cfg.openai_api_key)
    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {
                "role": "system",
                "content": INSTRUCOES_FIGURAS.format(
                    maximo=maximo, duracao=round(DUR_FIGURA)
                ),
            },
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_FIGURAS},
    )
    return json.loads(resposta.choices[0].message.content)["figuras"]


# ---- Renderização (Pillow) --------------------------------------------------


def _ease_out(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return 1 - (1 - u) ** 3


def _ease_in(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return u**3


ETIQUETA = {"brasil": "INFOGRÁFICO DO CANAL", "usa": "CHANNEL GRAPHIC"}


def _montar_cartao(caminho: Path, largura: int, altura: int, publico: str):
    """Monta o cartão estático (figura + moldura + etiqueta) uma única vez.

    A etiqueta no rodapé não é decoração: a figura é DESENHADA pelo canal a
    partir do que a narração disse, e o espectador precisa poder distinguí-la
    de um gráfico publicado por uma fonte externa — o mesmo cuidado que já vale
    para o material de terceiros (crédito de reprodução) e para o material de
    telejornal (etiqueta de representação visual).
    """
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    vertical = altura > largura
    larg_alvo = round(largura * (0.72 if vertical else 0.40))
    alt_max = round(altura * (0.52 if vertical else 0.66))

    with Image.open(caminho) as bruta:
        figura = bruta.convert("RGB")
    borda = max(6, round(min(largura, altura) * 0.007))
    faixa = max(22, round(min(largura, altura) * 0.040))  # altura da etiqueta

    larg_fig = larg_alvo - 2 * borda
    alt_fig = round(larg_fig * figura.height / max(figura.width, 1))
    if alt_fig + 2 * borda + faixa > alt_max:
        alt_fig = alt_max - 2 * borda - faixa
        larg_fig = round(alt_fig * figura.width / max(figura.height, 1))
    larg_fig, alt_fig = max(1, larg_fig), max(1, alt_fig)
    figura = figura.resize((larg_fig, alt_fig), Image.LANCZOS)

    larg_card = larg_fig + 2 * borda
    alt_card = alt_fig + 2 * borda + faixa
    raio = max(8, round(borda * 1.6))

    cartao = Image.new("RGBA", (larg_card, alt_card), (0, 0, 0, 0))
    dr = ImageDraw.Draw(cartao)
    dr.rounded_rectangle(
        [0, 0, larg_card - 1, alt_card - 1], radius=raio, fill=BRANCO + (255,)
    )
    cartao.paste(figura, (borda, borda))

    texto = ETIQUETA.get(publico, ETIQUETA["brasil"])
    tam = max(11, round(faixa * 0.38))
    fonte = ImageFont.truetype(str(FONTE_FIGURA), tam)
    while dr.textlength(texto, font=fonte) > larg_card - 2 * borda and tam > 9:
        tam -= 1
        fonte = ImageFont.truetype(str(FONTE_FIGURA), tam)
    dr.text(
        (larg_card // 2, alt_fig + borda + faixa // 2),
        texto,
        font=fonte,
        fill=CINZA_FONTE + (255,),
        anchor="mm",
    )

    desfoque = max(8, round(borda * 2.2))
    margem = desfoque * 3
    tela = Image.new(
        "RGBA", (larg_card + 2 * margem, alt_card + 2 * margem), (0, 0, 0, 0)
    )
    sombra = Image.new("RGBA", tela.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle(
        [margem, margem + desfoque // 2,
         margem + larg_card, margem + alt_card + desfoque // 2],
        radius=raio,
        fill=PRETO + (160,),
    )
    tela.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(desfoque)))
    tela.alpha_composite(cartao, (margem, margem))
    return tela


def _renderizar_frames(
    imagem: Path, destino: Path, largura: int, altura: int, dur: float, publico: str
) -> int:
    """Gera os PNGs RGBA da figura; devolve o número de frames.

    O movimento é o pedido pelo usuário e tem uma direção só: a figura entra
    subindo de FORA DO QUADRO, por baixo, até a posição de leitura; fica parada
    o tempo do meio; e sai continuando a subir, saindo POR CIMA do quadro.
    """
    from PIL import Image

    destino.mkdir(parents=True, exist_ok=True)
    cartao = _montar_cartao(imagem, largura, altura, publico)
    # Vertical: um pouco acima do centro, longe da faixa das legendas queimadas.
    # 16:9 (sem legendas): centro da tela.
    cy_final = round(altura * 0.42) if altura > largura else altura // 2
    cx = largura // 2
    # Fora do quadro embaixo e fora do quadro em cima, com folga da sombra.
    cy_baixo = altura + cartao.height // 2
    cy_cima = -cartao.height // 2
    nframes = max(1, round(dur * FPS))

    for f in range(nframes):
        t = f / FPS
        if t < T_ENTRADA:
            p = _ease_out(t / T_ENTRADA)
            cy = cy_baixo + (cy_final - cy_baixo) * p
        elif t > dur - T_SAIDA:
            p = _ease_in((t - (dur - T_SAIDA)) / T_SAIDA)
            cy = cy_final + (cy_cima - cy_final) * p
        else:
            cy = cy_final

        quadro = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
        quadro.alpha_composite(
            cartao, (cx - cartao.width // 2, round(cy) - cartao.height // 2)
        )
        quadro.save(destino / f"f_{f + 1:04d}.png")
    return nframes


# ---- Entrada do pipeline ----------------------------------------------------


def gerar_figuras(
    cfg: Config,
    texto_video: str,
    trend: dict,
    noticias: list[dict],
    alinhamento: dict,
    dur_total: float,
    pasta: Path,
    ocupadas: list[tuple[float, float]] | None = None,
) -> list[dict]:
    """Gera as figuras do vídeo; devolve a lista para `montar_video`.

    Retorno: [{"pattern": str, "inicio_s": float, "dur_s": float}, ...] — vazio
    quando a narração não tem dado que renda figura ou quando qualquer etapa
    falha (a camada é opcional por construção).

    `ocupadas`: janelas (início, fim) já usadas por infográficos e cartelas;
    nenhuma figura entra em cima delas — duas coisas sobrepostas ao mesmo tempo
    viram poluição.
    """
    maximo = cfg.max_figuras
    if maximo <= 0:
        return []
    if not FONTE_FIGURA.is_file():
        print("[figuras] Fonte Archivo Black ausente; vídeo sem figuras.")
        return []
    try:
        import PIL  # noqa: F401 — dependência opcional (requirements.txt)
    except ImportError:
        print("[figuras] Pillow não instalado; vídeo sem figuras.")
        return []

    try:
        plano = _planejar(cfg, texto_video, trend, noticias, maximo)
    except Exception as erro:  # noqa: BLE001 — figura nunca derruba o vídeo
        print(f"[aviso] Planejamento das figuras falhou ({erro}); seguindo sem.")
        return []

    if not plano:
        print("[figuras] A narração não trouxe dado que renda figura.")
        return []

    # Ancoragem na narração ANTES de gerar imagem: a geração é a única etapa
    # cara aqui, e figura cuja citação não existe no texto seria descartada
    # depois de paga.
    texto_baixo = texto_video.lower()
    candidatas: list[tuple[float, float, dict]] = []
    for fig in plano[:maximo]:
        trecho = (fig.get("trecho") or "").strip().lower()
        pos = texto_baixo.find(trecho) if trecho else -1
        if pos < 0:
            print(f"[figuras] Citação não encontrada, descartada: \"{trecho}\"")
            continue
        if not (fig.get("itens") or []):
            print("[figuras] Figura sem dado nenhum; descartada.")
            continue
        inicio = _tempo_do_char(alinhamento, texto_video, pos, dur_total)
        if inicio < INICIO_MINIMO:
            print(
                f"[figuras] Momento em {inicio:.1f}s cai no gancho "
                f"(< {INICIO_MINIMO:.0f}s); descartada."
            )
            continue
        inicio = min(inicio, dur_total)
        dur = min(DUR_FIGURA, dur_total - inicio - 0.2)
        if dur < DUR_MINIMA:
            print("[figuras] Janela curta demais no fim do vídeo; descartada.")
            continue
        candidatas.append((inicio, dur, fig))

    candidatas.sort(key=lambda c: c[0])
    ocupadas = list(ocupadas or [])
    vertical = cfg.video_altura > cfg.video_largura
    resultado: list[dict] = []
    registro: list[dict] = []
    for k, (inicio, dur, fig) in enumerate(candidatas, 1):
        conflito = next(
            (
                (a, b) for a, b in ocupadas
                if inicio < b + GAP_FIGURAS and a < inicio + dur + GAP_FIGURAS
            ),
            None,
        )
        if conflito:
            print(
                f"[figuras] Figura @ {inicio:.1f}s cai em cima de outra "
                f"sobreposição ({conflito[0]:.1f}-{conflito[1]:.1f}s); "
                "descartada."
            )
            continue

        imagem = _gerar_imagem(
            cfg, fig, pasta / f"figura_{k}.png", vertical
        )
        if imagem is None:
            continue

        pasta_frames = pasta / f"figura_{k}"
        try:
            nframes = _renderizar_frames(
                imagem, pasta_frames, cfg.video_largura, cfg.video_altura, dur,
                cfg.publico,
            )
        except Exception as erro:  # noqa: BLE001 — renderização nunca derruba
            print(f"[aviso] Renderização da figura falhou ({erro}); pulada.")
            continue

        item = {
            "pattern": str(pasta_frames / "f_%04d.png"),
            "inicio_s": inicio,
            "dur_s": nframes / FPS,
        }
        resultado.append(item)
        ocupadas.append((inicio, inicio + item["dur_s"]))
        registro.append(
            dict(
                item,
                arquivo=imagem.name,
                tipo=fig.get("tipo", ""),
                titulo=fig.get("titulo", ""),
                itens=fig.get("itens", []),
                trecho=fig.get("trecho", ""),
                por_que=fig.get("por_que", ""),
            )
        )
        print(
            f"[figuras] {fig.get('tipo')} \"{fig.get('titulo')}\" @ "
            f"{inicio:.1f}s por {dur:.1f}s — {fig.get('por_que', '')}"
        )

    if registro:
        (pasta / "figuras.json").write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return resultado
