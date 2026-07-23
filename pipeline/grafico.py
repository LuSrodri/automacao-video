"""Infográficos animados sobrepostos ao vídeo (contadores e barras).

O GPT decide, a partir dos números REAIS da narração e das notícias, até 2
infográficos por vídeo: um CONTADOR (número que sobe do zero e termina verde,
ou desce e termina negativo e vermelho) ou BARRAS comparativas (a barra
destacada cresce mais que as outras). Cada infográfico é ancorado numa citação
exata da narração (convertida em tempo pelo alinhamento do ElevenLabs, como no
planejador de cortes) e renderizado pelo Pillow em frames RGBA transparentes
que o ffmpeg sobrepõe ao vídeo.

Estética: minimalista e editorial, coerente com o resto do vídeo — Barlow Bold
preta com stroke branco (as mesmas legendas/handle), emoji colorido com halo
branco, fonte dos dados citada no rodapé. O painel ocupa o terço superior (no
lugar do logo/handle do canal, que somem enquanto ele está na tela) e SEMPRE
surge deslizando da base do vídeo para cima, com easing suave.

Etapa opcional: qualquer falha (GPT, citação não encontrada, Pillow/fonte
ausente) só pula os infográficos — nunca derruba o pipeline.
"""

import json
from pathlib import Path

from openai import OpenAI

from .config import AVISO_DADOS_EXTERNOS, RAIZ, Config
from .cortes import _tempo_do_char
from .edicao import FPS
from .escritor import _resumo_noticias

FONTE_BARLOW = RAIZ / "fonts" / "Barlow-Bold.ttf"
FONTE_EMOJI = Path(r"C:\Windows\Fonts\seguiemj.ttf")

MAX_GRAFICOS = 2
DUR_GRAFICO = 4.8  # s; duração-alvo de cada infográfico na tela
DUR_MINIMA = 2.8  # s; janela menor que isto não dá tempo da animação respirar
GAP_GRAFICOS = 0.8  # s; respiro mínimo entre dois infográficos
T_ENTRADA = 0.7  # s; subida da base do vídeo até o terço superior (ease-out)
T_SAIDA = 0.45  # s; fade de saída
T_NUM_INICIO = 0.45  # s; o contador começa a contar no fim da subida
T_NUM_DUR = 1.5  # s; duração da contagem (ease-out)
T_BARRA_INICIO = 0.55  # s; primeira barra começa a crescer
T_BARRA_PASSO = 0.18  # s; atraso entre uma barra e a seguinte
T_BARRA_DUR = 0.9  # s; crescimento de cada barra

PRETO = (14, 14, 14)
BRANCO = (255, 255, 255)
VERDE = (18, 183, 106)
VERMELHO = (224, 36, 36)
CINZA_FONTE = (60, 60, 60)

ESQUEMA_GRAFICOS = {
    "name": "infograficos_do_video",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "graficos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "tipo": {
                            "type": "string",
                            "enum": ["contador", "barras"],
                            "description": (
                                "contador = um número que anima do zero até o "
                                "valor; barras = comparação de 2 a 4 grandezas."
                            ),
                        },
                        "rotulo": {
                            "type": "string",
                            "description": (
                                "O que o número/comparação significa, curto e "
                                "concreto (ex.: 'vagas cortadas pela Oracle'). "
                                "No idioma do vídeo. Máximo 6 palavras."
                            ),
                        },
                        "emoji": {
                            "type": "string",
                            "description": (
                                "UM emoji pertinente ao dado (📉 💰 🚀 ⚠️...). "
                                "String vazia se nenhum couber."
                            ),
                        },
                        "prefixo": {
                            "type": "string",
                            "description": (
                                "Prefixo do número do contador (ex.: 'US$ '); "
                                "vazio se não houver."
                            ),
                        },
                        "sufixo": {
                            "type": "string",
                            "description": (
                                "Sufixo curto do número (ex.: '%', ' mil', "
                                "' bi'); vazio se não houver."
                            ),
                        },
                        "valor": {
                            "type": "number",
                            "description": (
                                "Valor final do contador. NEGATIVO para queda/"
                                "corte/perda (o número desce até ele). Use no "
                                "máximo 2 dígitos significativos e o sufixo "
                                "para a escala (21 + ' mil', nunca 21000). "
                                "Zero quando tipo = barras."
                            ),
                        },
                        "cor": {
                            "type": "string",
                            "enum": ["verde", "vermelho", "neutro"],
                            "description": (
                                "verde = alta/ganho/avanço; vermelho = queda/"
                                "corte/perda; neutro = fato sem direção."
                            ),
                        },
                        "barras": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "rotulo": {
                                        "type": "string",
                                        "description": (
                                            "Nome da barra, máximo 12 "
                                            "caracteres."
                                        ),
                                    },
                                    "valor": {
                                        "type": "number",
                                        "description": (
                                            "Grandeza da barra (sempre >= 0, "
                                            "todas na MESMA unidade)."
                                        ),
                                    },
                                    "destaque": {
                                        "type": "boolean",
                                        "description": (
                                            "true na barra que a narração "
                                            "destaca (uma só)."
                                        ),
                                    },
                                },
                                "required": ["rotulo", "valor", "destaque"],
                            },
                            "description": (
                                "2 a 4 barras quando tipo = barras; lista "
                                "vazia quando tipo = contador."
                            ),
                        },
                        "fonte": {
                            "type": "string",
                            "description": (
                                "De onde o número saiu: veículo ou conta do X "
                                "DAS LISTAS recebidas (ex.: 'Reuters', "
                                "'@unusual_whales'). Obrigatório."
                            ),
                        },
                        "trecho": {
                            "type": "string",
                            "description": (
                                "Citação EXATA e curta (3 a 8 palavras "
                                "consecutivas) da narração, copiada caractere "
                                "por caractere, marcando o momento em que o "
                                "infográfico entra (quando a narração fala "
                                "desse número)."
                            ),
                        },
                    },
                    "required": [
                        "tipo",
                        "rotulo",
                        "emoji",
                        "prefixo",
                        "sufixo",
                        "valor",
                        "cor",
                        "barras",
                        "fonte",
                        "trecho",
                    ],
                },
            }
        },
        "required": ["graficos"],
    },
}

IDIOMA_BRASIL = """\
Todo texto que aparece na tela (rotulo, prefixo, sufixo e rótulos das barras)
deve estar em PORTUGUÊS DO BRASIL (ex.: sufixos " mil", " bi"; prefixo "R$ ").\
"""

IDIOMA_USA = """\
Todo texto que aparece na tela (rotulo, prefixo, sufixo e rótulos das barras)
deve estar em INGLÊS AMERICANO, sem nenhuma palavra em português (ex.: sufixos
"K", "M", "B"; prefixo "$"; rotulo como 'jobs cut by Oracle').\
"""

INSTRUCOES_GRAFICOS = """\
Você é o editor de infográficos de um canal de vídeos curtos (YouTube Shorts)
de notícias. Você recebe a NARRAÇÃO de um vídeo e as NOTÍCIAS que a embasaram,
e decide até {maximo} infográficos animados minimalistas para reforçar os
NÚMEROS centrais da história na tela.

{idioma}

REGRAS:
1. SÓ use números REAIS que aparecem na narração ou nas notícias recebidas —
   NUNCA invente, estime ou extrapole um valor.
2. Menos é mais: 1 infográfico certeiro vale mais que 2 fracos. Se a história
   não tem número forte, devolva a lista vazia — infográfico sem número real é
   proibido.
3. "contador" é o formato padrão (um número marcante: dinheiro, vagas,
   porcentagem, unidades). "barras" só quando a narração COMPARA grandezas na
   mesma unidade (antes/depois, empresa A vs B).
4. Queda/corte/perda: valor NEGATIVO e cor "vermelho" (o número desce até o
   negativo). Alta/ganho: valor positivo e cor "verde".
5. Máximo 2 dígitos significativos no valor; a escala vai no sufixo, no idioma
   do vídeo (valor 21, sufixo " mil" ou "K" — nunca valor 21000).
6. "trecho" é citação LITERAL da narração (será localizada por busca exata;
   paráfrase descarta o infográfico). Escolha o momento em que a narração fala
   do número.
7. "fonte" cita nominalmente o veículo/conta de onde o número veio, somente
   das listas recebidas.
Responda somente com o JSON pedido.\
"""


def _planejar(
    cfg: Config, texto_video: str, noticias: list[dict]
) -> list[dict]:
    cliente = OpenAI(api_key=cfg.openai_api_key)
    conteudo = (
        AVISO_DADOS_EXTERNOS + "\n\n"
        f"NARRAÇÃO DO VÍDEO:\n{texto_video}\n\n"
        "NOTÍCIAS QUE EMBASARAM O ROTEIRO:\n" + _resumo_noticias(noticias)
    )
    resposta = cliente.chat.completions.create(
        model=cfg.text_model,
        messages=[
            {
                "role": "system",
                "content": INSTRUCOES_GRAFICOS.format(
                    maximo=MAX_GRAFICOS,
                    idioma=IDIOMA_USA if cfg.publico == "usa" else IDIOMA_BRASIL,
                ),
            },
            {"role": "user", "content": conteudo},
        ],
        response_format={"type": "json_schema", "json_schema": ESQUEMA_GRAFICOS},
    )
    return json.loads(resposta.choices[0].message.content)["graficos"]


# ---- Renderização (Pillow) ----


def _ease_out(u: float) -> float:
    u = min(max(u, 0.0), 1.0)
    return 1 - (1 - u) ** 3


def _ease_out_back(u: float) -> float:
    """Ease-out com overshoot leve (a barra destacada 'passa' e assenta)."""
    u = min(max(u, 0.0), 1.0)
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (u - 1) ** 3 + c1 * (u - 1) ** 2


def _lerp_cor(a: tuple, b: tuple, u: float) -> tuple:
    u = min(max(u, 0.0), 1.0)
    return tuple(round(ca + (cb - ca) * u) for ca, cb in zip(a, b))


def _cor_alvo(nome: str) -> tuple:
    return {"verde": VERDE, "vermelho": VERMELHO}.get(nome, PRETO)


def _formatar_numero(v: float, publico: str, inteiro: bool) -> str:
    neg = v < 0
    a = abs(v)
    s = f"{int(round(a)):,}" if inteiro else f"{a:,.1f}"
    if publico != "usa":  # pt-BR: milhar com ponto, decimal com vírgula
        s = s.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return ("-" if neg else "") + s


def _emoji_com_halo(emoji: str, altura_px: int):
    """Renderiza o emoji colorido com halo branco (alfa dilatado); None se falhar."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    if not emoji or not FONTE_EMOJI.is_file():
        return None
    try:
        fonte = ImageFont.truetype(str(FONTE_EMOJI), 160)
        tela = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
        ImageDraw.Draw(tela).text(
            (320, 320), emoji, font=fonte, embedded_color=True, anchor="mm"
        )
        caixa = tela.getbbox()
        if not caixa:
            return None
        recorte = tela.crop(caixa)
        fator = altura_px / max(recorte.height, 1)
        recorte = recorte.resize(
            (max(1, round(recorte.width * fator)), altura_px), Image.LANCZOS
        )
        borda = max(3, altura_px // 16)
        base = Image.new(
            "RGBA",
            (recorte.width + 4 * borda, recorte.height + 4 * borda),
            (0, 0, 0, 0),
        )
        base.paste(recorte, (2 * borda, 2 * borda), recorte)
        alfa = base.getchannel("A").filter(ImageFilter.MaxFilter(2 * borda + 1))
        alfa = alfa.filter(ImageFilter.GaussianBlur(1))
        halo = Image.new("RGBA", base.size, BRANCO + (0,))
        halo.putalpha(alfa)
        return Image.alpha_composite(halo, base)
    except Exception as erro:  # noqa: BLE001 — emoji é decorativo, nunca derruba
        print(f"[grafico] aviso: emoji '{emoji}' não renderizou ({erro})")
        return None


def _texto_que_cabe(draw, texto: str, fonte_path: str, tamanho: int, larg_max: int):
    """Fonte reduzida até o texto caber em `larg_max` (piso de 40% do tamanho)."""
    from PIL import ImageFont

    tam = tamanho
    while tam > max(12, int(tamanho * 0.4)):
        fonte = ImageFont.truetype(fonte_path, tam)
        if draw.textlength(texto, font=fonte) <= larg_max:
            return fonte
        tam -= 2
    return ImageFont.truetype(fonte_path, tam)


def _com_alpha(img, fator: float):
    if fator >= 1.0:
        return img
    alfa = img.getchannel("A").point(lambda p: int(p * max(fator, 0.0)))
    img.putalpha(alfa)
    return img


def _desenhar_contador(painel, g: dict, t: float, largura: int, publico: str,
                       emoji_img) -> None:
    from PIL import ImageDraw

    dr = ImageDraw.Draw(painel)
    terco = painel.height
    cx = largura // 2

    valor = float(g["valor"])
    inteiro = abs(valor - round(valor)) < 1e-9
    p_num = _ease_out((t - T_NUM_INICIO) / T_NUM_DUR)
    atual = valor * p_num
    cor = _lerp_cor(PRETO, _cor_alvo(g["cor"]), p_num ** 2)

    y = round(terco * 0.16)
    if emoji_img is not None:
        painel.alpha_composite(
            emoji_img, (cx - emoji_img.width // 2, y - emoji_img.height // 2)
        )
        y += round(terco * 0.16)

    texto_num = (
        f"{g.get('prefixo', '')}"
        f"{_formatar_numero(atual, publico, inteiro)}"
        f"{g.get('sufixo', '')}"
    )
    sw = max(4, round(largura * 0.008))
    fonte_num = _texto_que_cabe(
        dr, texto_num, str(FONTE_BARLOW), round(largura * 0.14), round(largura * 0.9)
    )
    dr.text(
        (cx, y + round(terco * 0.20)),
        texto_num,
        font=fonte_num,
        fill=cor + (255,),
        stroke_width=sw,
        stroke_fill=BRANCO + (255,),
        anchor="mm",
    )

    rotulo = (g.get("rotulo") or "").upper()
    if rotulo:
        fonte_rot = _texto_que_cabe(
            dr, rotulo, str(FONTE_BARLOW), round(largura * 0.042), round(largura * 0.86)
        )
        dr.text(
            (cx, round(terco * 0.72)),
            rotulo,
            font=fonte_rot,
            fill=PRETO + (255,),
            stroke_width=max(2, sw // 2),
            stroke_fill=BRANCO + (255,),
            anchor="mm",
        )


def _desenhar_barras(painel, g: dict, t: float, largura: int, publico: str,
                     emoji_img) -> None:
    from PIL import ImageDraw

    dr = ImageDraw.Draw(painel)
    terco = painel.height
    cx = largura // 2
    sw = max(3, round(largura * 0.005))

    titulo = (g.get("rotulo") or "").upper()
    fonte_tit = _texto_que_cabe(
        dr, titulo, str(FONTE_BARLOW), round(largura * 0.040), round(largura * 0.70)
    )
    larg_tit = dr.textlength(titulo, font=fonte_tit) if titulo else 0
    y_tit = round(terco * 0.12)
    if titulo:
        x_tit = cx + (emoji_img.width // 2 + 10 if emoji_img is not None else 0)
        dr.text(
            (x_tit, y_tit),
            titulo,
            font=fonte_tit,
            fill=PRETO + (255,),
            stroke_width=max(2, sw),
            stroke_fill=BRANCO + (255,),
            anchor="mm",
        )
    if emoji_img is not None:
        x_emoji = round(cx - larg_tit / 2 - emoji_img.width / 2)
        painel.alpha_composite(
            emoji_img, (x_emoji - 10, y_tit - emoji_img.height // 2)
        )

    barras = g["barras"]
    n = len(barras)
    maximo = max(abs(float(b["valor"])) for b in barras) or 1.0
    y_base = round(terco * 0.76)
    y_topo = round(terco * 0.28)
    w = min(round(largura * 0.16), round(largura * 0.66 / n))
    gap = round(w * 0.45)
    x0 = cx - (n * w + (n - 1) * gap) // 2
    cor_destaque = _cor_alvo(g["cor"] if g["cor"] != "neutro" else "verde")

    for i, b in enumerate(barras):
        val = abs(float(b["valor"]))
        h_final = (y_base - y_topo) * (0.15 + 0.85 * val / maximo)
        u = (t - (T_BARRA_INICIO + i * T_BARRA_PASSO)) / T_BARRA_DUR
        p = _ease_out_back(u) if b.get("destaque") else _ease_out(u)
        h = max(0.0, h_final * p)
        if h < 1:
            continue
        x = x0 + i * (w + gap)
        cor = cor_destaque if b.get("destaque") else PRETO
        dr.rounded_rectangle(
            [x, y_base - h, x + w, y_base],
            radius=max(6, w // 6),
            fill=cor + (255,),
            outline=BRANCO + (255,),
            width=sw,
        )
        # Valor contando em cima da barra
        p_num = min(max(u, 0.0), 1.0)
        inteiro = abs(val - round(val)) < 1e-9
        texto_val = _formatar_numero(val * p_num, publico, inteiro)
        fonte_val = _texto_que_cabe(
            dr, texto_val, str(FONTE_BARLOW), round(largura * 0.034), round(w * 1.5)
        )
        dr.text(
            (x + w // 2, y_base - h - round(largura * 0.028)),
            texto_val,
            font=fonte_val,
            fill=cor + (255,),
            stroke_width=max(2, sw),
            stroke_fill=BRANCO + (255,),
            anchor="mm",
        )
        # Rótulo embaixo
        rot = (b.get("rotulo") or "")[:12].upper()
        if rot:
            fonte_rot = _texto_que_cabe(
                dr, rot, str(FONTE_BARLOW), round(largura * 0.026), round(w * 1.4)
            )
            dr.text(
                (x + w // 2, y_base + round(largura * 0.026)),
                rot,
                font=fonte_rot,
                fill=PRETO + (255,),
                stroke_width=max(2, sw),
                stroke_fill=BRANCO + (255,),
                anchor="mm",
            )


def _renderizar_frames(
    g: dict, destino: Path, largura: int, altura: int, dur: float, publico: str
) -> int:
    """Gera os PNGs RGBA do infográfico; devolve o número de frames."""
    from PIL import Image, ImageDraw

    destino.mkdir(parents=True, exist_ok=True)
    terco = altura // 3
    y_final = round(altura * 0.04)
    nframes = max(1, round(dur * FPS))
    emoji_altura = round(
        terco * (0.30 if g["tipo"] == "contador" else 0.13)
    )
    emoji_img = _emoji_com_halo((g.get("emoji") or "").strip(), emoji_altura)
    rotulo_fonte = (g.get("fonte") or "").strip()

    for f in range(nframes):
        t = f / FPS
        painel = Image.new("RGBA", (largura, terco), (0, 0, 0, 0))
        if g["tipo"] == "barras":
            _desenhar_barras(painel, g, t, largura, publico, emoji_img)
        else:
            _desenhar_contador(painel, g, t, largura, publico, emoji_img)
        if rotulo_fonte:
            dr = ImageDraw.Draw(painel)
            prefixo = "Source" if publico == "usa" else "Fonte"
            texto = f"{prefixo}: {rotulo_fonte}"
            fonte_f = _texto_que_cabe(
                dr, texto, str(FONTE_BARLOW), round(largura * 0.026),
                round(largura * 0.8),
            )
            dr.text(
                (largura // 2, round(terco * 0.92)),
                texto,
                font=fonte_f,
                fill=CINZA_FONTE + (235,),
                stroke_width=2,
                stroke_fill=BRANCO + (235,),
                anchor="mm",
            )

        # Entrada: o painel inteiro sobe da base do vídeo até o terço superior.
        p_in = _ease_out(t / T_ENTRADA)
        y = round(altura - (altura - y_final) * p_in)
        # Saída: fade suave no fim da janela.
        if t > dur - T_SAIDA:
            painel = _com_alpha(painel, (dur - t) / T_SAIDA)

        quadro = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
        quadro.alpha_composite(painel, (0, y))
        quadro.save(destino / f"f_{f + 1:04d}.png")
    return nframes


def gerar_graficos(
    cfg: Config,
    texto_video: str,
    noticias: list[dict],
    alinhamento: dict,
    dur_total: float,
    pasta: Path,
) -> list[dict]:
    """Planeja e renderiza os infográficos; devolve a lista para montar_video.

    Retorno: [{"pattern": str, "inicio_s": float, "dur_s": float}, ...] —
    vazio quando não há número forte ou qualquer etapa falha (opcional).
    """
    if not FONTE_BARLOW.is_file():
        print("[grafico] Fonte Barlow ausente; vídeo sem infográficos.")
        return []
    try:
        import PIL  # noqa: F401 — dependência opcional (requirements.txt)
    except ImportError:
        print("[grafico] Pillow não instalado; vídeo sem infográficos.")
        return []

    try:
        plano = _planejar(cfg, texto_video, noticias)
    except Exception as erro:  # noqa: BLE001 — infográfico nunca derruba o vídeo
        print(f"[aviso] Planejamento de infográficos falhou ({erro}); seguindo sem.")
        return []
    if not plano:
        print("[grafico] Nenhum número forte na história; vídeo sem infográficos.")
        return []

    texto_baixo = texto_video.lower()
    candidatos: list[tuple[float, float, dict]] = []
    for g in plano[:MAX_GRAFICOS]:
        if g["tipo"] == "barras":
            barras = [
                b for b in (g.get("barras") or [])
                if isinstance(b.get("valor"), (int, float))
            ][:4]
            if len(barras) < 2:
                print("[grafico] Barras com menos de 2 itens válidos; descartado.")
                continue
            g["barras"] = barras
        elif not isinstance(g.get("valor"), (int, float)) or not g["valor"]:
            print("[grafico] Contador sem valor numérico; descartado.")
            continue
        trecho = (g.get("trecho") or "").strip().lower()
        pos = texto_baixo.find(trecho) if trecho else -1
        if pos < 0:
            print(f"[grafico] Citação não encontrada, descartado: \"{trecho}\"")
            continue
        inicio = _tempo_do_char(alinhamento, texto_video, pos, dur_total)
        inicio = min(max(0.0, inicio), dur_total)
        dur = min(DUR_GRAFICO, dur_total - inicio - 0.2)
        if dur < DUR_MINIMA:
            print("[grafico] Janela curta demais no fim do vídeo; descartado.")
            continue
        candidatos.append((inicio, dur, g))

    candidatos.sort(key=lambda c: c[0])
    resultado: list[dict] = []
    registro: list[dict] = []
    fim_anterior = -1e9
    for k, (inicio, dur, g) in enumerate(candidatos, 1):
        if inicio < fim_anterior + GAP_GRAFICOS:
            print(f"[grafico] '{g['rotulo']}' sobrepõe o anterior; descartado.")
            continue
        pasta_frames = pasta / f"grafico_{k}"
        try:
            nframes = _renderizar_frames(
                g, pasta_frames, cfg.video_largura, cfg.video_altura, dur,
                cfg.publico,
            )
        except Exception as erro:  # noqa: BLE001 — renderização nunca derruba
            print(f"[aviso] Renderização do infográfico falhou ({erro}); pulado.")
            continue
        item = {
            "pattern": str(pasta_frames / "f_%04d.png"),
            "inicio_s": inicio,
            "dur_s": nframes / FPS,
        }
        resultado.append(item)
        registro.append(dict(item, plano=g))
        fim_anterior = inicio + dur
        print(
            f"[grafico] {g['tipo']} '{g['rotulo']}' @ {inicio:.1f}s "
            f"por {dur:.1f}s (fonte: {g.get('fonte', '?')})"
        )

    if registro:
        (pasta / "graficos.json").write_text(
            json.dumps(registro, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    return resultado
