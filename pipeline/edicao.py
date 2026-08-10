"""Montagem final do vídeo com ffmpeg.

O vídeo é montado SOMENTE com clipes de vídeo dos posts do X (imagem estática
é proibida — a montagem aborta se receber uma). O fundo de cada momento é o
PRÓPRIO clipe daquele trecho, ampliado para cobrir a tela toda e BORRADO; por
cima entra o clipe nítido em largura total, centrado. Os clipes cobrem 100% da
narração — nunca há um instante sem imagem na tela — com um crossfade curto e
limpo entre si (corte editorial, sem deslizes). A narração TTS (sem silêncios)
é a única faixa contínua — o vídeo NÃO tem música de fundo (removida em
2026-07-30) —, e o crédito de reprodução ("Reprodução Imagem: X" + "Conta
@usuario" do post de origem) fica no canto superior direito da TELA enquanto o
clipe daquela conta está nela.

MOLDURA DE SMARTPHONE SOBRE UMA CAMA (2026-08-09, pedido do usuário). Nada
ocupa mais o quadro inteiro: o clipe, as cartelas e as figuras aparecem dentro
da TELA de um celular apoiado numa cama (cenario.py), nos DOIS formatos. O
aparelho fica EM PÉ quando o vídeo é vertical (Short 9:16) e DEITADO quando é
16:9 (formato longo). Substituiu a sala de estar com TV, que só o formato longo
usava. A área útil do clipe passa a ser o retângulo da TELA — o fundo borrado
preenche a tela quando o clipe não tem a proporção dela, e o PNG do cenário
entra por cima recortando tudo na moldura do aparelho.

CARROSSEL COM ARRASTO DA MÃO. As cartelas de imagem (cartelas.py) e as figuras
do gpt-image-2 (figuras.py) deixaram de ser cartões sobrepostos ao clipe: elas
agora ocupam a tela inteira do celular e entram por ARRASTO. No momento-chave
uma MÃO surge, arrasta o conteúdo PARA A ESQUERDA e a imagem entra pela direita
no lugar do vídeo; no fim da janela a mão volta, arrasta PARA A DIREITA e o
vídeo retorna. É um carrossel de duas posições: o clipe e a imagem do momento,
ambos deslocados pelo MESMO offset horizontal, de modo que a borda de um encosta
na do outro durante todo o arrasto. O que sai da tela some atrás do corpo do
aparelho — o recorte é o próprio PNG do cenário, sem máscara nenhuma no ffmpeg.

Com a imagem tomando a tela inteira, o DESFOQUE do que ficava atrás das
cartelas (CARTELA_BLUR_*) perdeu função e saiu junto: não há mais nada atrás
para tirar de foco. Os INFOGRÁFICOS ANIMADOS montados em ffmpeg (grafico.py)
já haviam sido REMOVIDOS em 2026-08-04 — os "big numbers" da tela vêm só das
figuras do gpt-image-2; não reintroduzir sem pedido explícito.

Clipe marcado como REPRESENTAÇÃO VISUAL (material de telejornal, que só o
formato longo admite — ver auditoria.py) entra dessaturado e com etiqueta no
rodapé esquerdo da tela, para não se confundir com material próprio do canal. A
marca é por clipe: os demais da mesma montagem seguem coloridos e sem etiqueta.
"""

import subprocess
import shutil
from pathlib import Path

from .cenario import gerar_cenario_celular, gerar_mao
from .config import RAIZ

FPS = 30
MIN_EXIBICAO = 3.0  # segundos mínimos de exibição de cada clipe
MAX_EXIBICAO = 15.0  # segundos máximos de exibição de cada clipe (só aviso)
# No formato longo (16:9, 120-150s) o clipe segura janelas maiores: com 8
# clipes em 2 minutos a média já é ~15s, e o aviso só interessa acima disso.
MAX_EXIBICAO_LONGO = 25.0
CROSSFADE = 0.3  # duração do crossfade entre clipes consecutivos
# Respiro entre o fim da narração e o fim do vídeo. Curto de propósito: o
# CORTE do roteiro emenda no hook do reinício (loop), e uma cauda longa de
# tela parada quebra exatamente essa emenda (era 0,6s).
RESPIRO_FINAL = 0.15
BLUR_SIGMA = 18  # intensidade do desfoque do fundo
ESCURECER = -0.05  # brilho aplicado ao fundo borrado (realça o clipe nítido)

# Efeito sonoro de "woosh" tocado em cada transição entre clipes.
WOOSH = RAIZ / "assets" / "woosh.mp3"
WOOSH_VOL = 0.5  # volume do efeito relativo à narração

# --- Carrossel (arrasto da mão) ---------------------------------------------
# Tempo de cada arrasto, de uma ponta à outra da tela. 0,42s é a faixa em que o
# gesto lê como arrasto e não como corte: abaixo de ~0,3 vira piscada, acima de
# ~0,6 o espectador espera o conteúdo que ainda está entrando. Os DOIS arrastos
# (o de ida, que traz a imagem, e o de volta, que devolve o vídeo) cabem DENTRO
# da janela da cartela, então DUR_MINIMA lá precisa continuar bem acima de
# 2 * T_ARRASTO.
T_ARRASTO = 0.42
# A mão aparece um pouco antes de o conteúdo começar a andar e sai um pouco
# depois de ele parar — mão que surge já em movimento lê como falha de render.
MAO_ANTECIPACAO = 0.25
MAO_PERMANENCIA = 0.25
MAO_SUBIDA = 0.22  # sobe de fora do quadro até encostar na tela
MAO_DESCIDA = 0.22
# Percurso do dedo na tela, em fração da largura dela: começa perto da borda
# direita e termina perto da esquerda (e o inverso no arrasto de volta, que é o
# mesmo percurso lido ao contrário).
MAO_X_INICIO = 0.78
MAO_X_FIM = 0.22
MAO_Y_TELA = 0.55  # altura do toque, em fração da altura da tela
# Janela mínima de uma imagem no carrossel: os dois arrastos, mais a entrada e
# a saída da mão em cada um, sem que as duas aparições dela se encavalem.
MIN_JANELA_CARROSSEL = 2 * (T_ARRASTO + MAO_ANTECIPACAO + MAO_PERMANENCIA)

# Crédito de reprodução no canto superior direito DA TELA, por clipe: linha 1
# fixa ("Reprodução Imagem: X") e linha 2 com a conta do post de origem.
# Estética editorial de rede social: Archivo Black branca sobre tarja preta
# semitransparente, alinhada à direita. Some enquanto a imagem do carrossel
# está na tela — ela traz o próprio crédito, e manter o do clipe ali creditaria
# a conta errada.
FONTE_CREDITO = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"
CREDITO_TEXTOS = {
    "brasil": ("Reprodução Imagem: X", "Conta {conta}"),
    "usa": ("Image Credit: X", "Account {conta}"),
}
# As frações abaixo são da TELA do celular, não do quadro: é dentro dela que o
# crédito mora desde que a moldura entrou.
CREDITO_FONTE_FRAC = 0.030  # tamanho da fonte como fração do lado menor da tela
CREDITO_MARGEM_FRAC = 0.035  # distância da borda direita (fração da largura da tela)
CREDITO_Y_FRAC = 0.045  # distância do topo da tela como fração da altura dela
CREDITO_ENTRELINHA = 1.55  # distância entre as duas linhas (fração da fonte)
CREDITO_TARJA = 0.45  # opacidade da tarja preta atrás do texto
CREDITO_TARJA_PAD_FRAC = 0.45  # respiro da tarja ao redor do texto (fração da fonte)

# Marcação de REPRESENTAÇÃO VISUAL: no formato longo o material de telejornal
# não é mais vetado (auditoria.py) — entra dessaturado e etiquetado no rodapé
# esquerdo da tela, para o espectador não tomar cobertura de terceiro por
# material do canal. Só o clipe marcado ("representacao" na sobreposição)
# recebe o tratamento; os demais seguem coloridos e sem etiqueta.
REPR_SATURACAO = 0.10  # 0 = P&B puro; sobra um resto de cor, menos chapado
REPR_TEXTOS = {
    "brasil": "REPRESENTAÇÃO VISUAL",
    "usa": "ILLUSTRATIVE FOOTAGE",
}
REPR_FONTE_FRAC = 0.028  # fração do lado menor da tela (mesma lógica do crédito)
REPR_MARGEM_FRAC = 0.035  # distância da borda esquerda da tela
REPR_Y_FRAC = 0.912  # distância do topo da tela como fração da altura dela


def _exigir_ffmpeg() -> None:
    for binario in ("ffmpeg", "ffprobe"):
        if shutil.which(binario) is None:
            raise SystemExit(
                f"{binario} não encontrado no PATH. "
                "Instale o ffmpeg (winget install Gyan.FFmpeg) e reabra o terminal."
            )


def duracao_audio(audio: Path) -> float:
    saida = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "csv=p=0",
            str(audio),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return float(saida.stdout.strip())


# Extensões aceitas nas sobreposições (clipes dos posts do X baixados pelo
# midia_x.py). Qualquer outra coisa é imagem estática — proibida no formato.
EXTENSOES_VIDEO = {".mp4", ".mov", ".webm", ".mkv"}


def _e_video(caminho: Path) -> bool:
    return Path(caminho).suffix.lower() in EXTENSOES_VIDEO


def _ordenar(sobreposicoes: list[dict]) -> list[dict]:
    """Ordena as imagens pelo ponto da narração em que cada uma entra.

    Entradas com "inicio_s" (tempo explícito do planejador de cortes) ordenam
    por ele; as demais, pela fração do texto. As duas formas não se misturam na
    prática (o plano ou vale para todas as mídias, ou é descartado inteiro).
    """
    def chave(s: dict) -> tuple:
        if s.get("inicio_s") is not None:
            return (False, s["inicio_s"])
        return (s.get("inicio_frac") is None, s.get("inicio_frac") or 0.0)

    return sorted(sobreposicoes, key=chave)


# Quanto puxar o início de cada clipe para a distribuição uniforme (0 = usa só
# o ponto do trecho, gerando durações bem irregulares; 1 = ignora o trecho e
# espaça tudo igual). 0.6 equilibra: cada clipe fica perto do momento da
# narração que ilustra, mas sem piscar nem eternizar.
PESO_UNIFORME = 0.6


def _calcular_janelas(
    sobreposicoes: list[dict], duracao: float
) -> list[tuple[float, float]]:
    """Janelas (início, fim) contíguas que cobrem TODA a narração.

    Com tempos explícitos do planejador de cortes ("inicio_s" em todas as
    entradas), os inícios são usados como estão, só com saneamento (ordem,
    piso, limites). Sem plano, cada clipe entra perto do ponto da narração do
    seu trecho e fica até o próximo entrar, misturando o ponto do trecho com
    uma distribuição uniforme para evitar durações irregulares; clipes sem
    sincronização conhecida entram na posição uniforme.

    O piso de exibição é MIN_EXIBICAO, mas nunca mais que a fatia média
    (duração/n): com poucos clipes a fatia média é larga e o piso só protege
    de cortes colados; num vídeo curto demais para o piso, ele cede em vez de
    empilhar todos os clipes no fim.
    """
    n = len(sobreposicoes)
    if n == 0:
        return []

    piso = min(MIN_EXIBICAO, duracao / n)
    if all(s.get("inicio_s") is not None for s in sobreposicoes):
        inicios = [min(max(0.0, float(s["inicio_s"])), duracao) for s in sobreposicoes]
    else:
        passo = duracao / n
        inicios = []
        for i, s in enumerate(sobreposicoes):
            uniforme = i * passo
            frac = s.get("inicio_frac")
            if frac is None:
                inicios.append(uniforme)
            else:
                alvo = max(0.0, frac * duracao)
                inicios.append(PESO_UNIFORME * uniforme + (1 - PESO_UNIFORME) * alvo)

    # Garante ordem crescente, início em 0 e duração mínima (piso) em todos,
    # inclusive no último (reservando 'piso' para cada clipe ainda por vir).
    inicios[0] = 0.0
    for i in range(1, n):
        inicios[i] = max(inicios[i], inicios[i - 1] + piso)
        inicios[i] = min(inicios[i], duracao - (n - i) * piso)

    janelas = []
    for i in range(n):
        ini = inicios[i]
        fim = inicios[i + 1] if i + 1 < n else duracao
        janelas.append((ini, fim))
    return janelas


def intervalos_imagens(
    sobreposicoes: list[dict], duracao: float
) -> list[tuple[float, float]]:
    """Janelas em que há imagem na tela (com a cobertura total, é o vídeo todo).

    Mantido para as legendas decidirem a posição de cada trecho.
    """
    return _calcular_janelas(_ordenar(sobreposicoes), duracao)


def _caminho_filtro(caminho: Path) -> str:
    """Escapa um caminho Windows para uso dentro de filter_complex."""
    return str(caminho).replace("\\", "/").replace(":", "\\:")


def _texto_drawtext(texto: str) -> str:
    """Escapa um texto para uso dentro de text='...' do filtro drawtext.

    O ':' precisa de escape próprio: as aspas simples protegem no nível do
    GRAFO de filtros, mas o parser de opções do drawtext ainda divide em ':'
    — sem o '\\:' um texto como "Reprodução Imagem: X" quebra o filtro.
    """
    return (
        texto.replace("\\", "\\\\").replace("'", r"'\''").replace(":", "\\:")
    )


# ---- Expressões de tempo do carrossel ---------------------------------------


def _suave(u: str) -> str:
    """smoothstep sobre uma expressão ffmpeg `u` já normalizada em [0,1].

    Aceleração e desaceleração nas pontas: o arrasto de um dedo real não começa
    nem termina na velocidade máxima. Escrito como expressão porque `overlay`
    avalia x/y por quadro — não há como pré-calcular a curva em Python.
    """
    return f"({u})*({u})*(3-2*({u}))"


def _expr_progresso(
    janelas: list[tuple[float, float]], subida: float, descida: float
) -> str:
    """Expressão ffmpeg: 0 fora das janelas, 1 dentro, com rampa nas pontas.

    Em cada janela (ini, fim) o valor sobe de 0 a 1 em `subida` segundos a
    partir de `ini`, fica em 1, e desce de 1 a 0 nos `descida` segundos finais.
    Os intervalos são semiabertos (`gte`/`lt`) para que dois termos nunca
    valham ao mesmo tempo na fronteira e o resultado passe de 1.

    É a mesma curva para duas coisas diferentes: o deslocamento do carrossel
    (rampa = arrasto) e a presença da mão em quadro (rampa = entrar/sair).
    """
    termos: list[str] = []
    for ini, fim in janelas:
        # Janela curta demais para as duas rampas: encolhe as duas na mesma
        # proporção em vez de deixar a subida invadir a descida (o que faria a
        # expressão saltar de um valor intermediário para 0).
        total = subida + descida
        sub, desc = subida, descida
        if fim - ini < total and total > 0:
            escala = (fim - ini) / total
            sub, desc = subida * escala, descida * escala
        sub, desc = max(sub, 0.001), max(desc, 0.001)
        a, b = ini, ini + sub
        c, d = fim - desc, fim
        termos.append(f"gte(t,{a:.3f})*lt(t,{b:.3f})*{_suave(f'(t-{a:.3f})/{sub:.3f}')}")
        if c > b:
            termos.append(f"gte(t,{b:.3f})*lt(t,{c:.3f})")
        termos.append(
            f"gte(t,{c:.3f})*lt(t,{d:.3f})*(1-{_suave(f'(t-{c:.3f})/{desc:.3f}')})"
        )
    return "+".join(termos) if termos else "0"


def _expr_janelas(janelas: list[tuple[float, float]]) -> str:
    """Expressão ffmpeg verdadeira dentro das janelas (para `enable`)."""
    return "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in janelas)


def _subtrair(
    janela: tuple[float, float], remocoes: list[tuple[float, float]]
) -> list[tuple[float, float]]:
    """`janela` menos os intervalos de `remocoes`; pedaços curtos são descartados."""
    partes = [janela]
    for ra, rb in remocoes:
        novas: list[tuple[float, float]] = []
        for a, b in partes:
            if rb <= a or ra >= b:
                novas.append((a, b))
                continue
            if a < ra:
                novas.append((a, ra))
            if rb < b:
                novas.append((rb, b))
        partes = novas
    return [(a, b) for a, b in partes if b - a > 0.15]


def montar_video(
    narracao: Path,
    sobreposicoes: list[dict],
    destino: Path,
    largura: int,
    altura: int,
    legendas: Path | None = None,
    cartelas: list[dict] | None = None,
    figuras: list[dict] | None = None,
    publico: str = "brasil",
    formato: str = "curto",
) -> Path:
    """Monta o vídeo final: celular sobre a cama, com o clipe do X na tela.

    `sobreposicoes`: [{"caminho": Path, "inicio_frac": float|None,
    "fim_frac": float|None, "conta": str, "representacao": bool}, ...] —
    frações (0 a 1) da narração em que o clipe entra; None usa distribuição
    uniforme. SOMENTE clipes de vídeo (imagem estática aborta). Os clipes
    cobrem 100% da narração (sem instante vazio) e fazem crossfade entre si;
    "conta" (@usuario do post de origem) alimenta o crédito de reprodução no
    canto superior direito da tela. "representacao" marca o clipe de telejornal
    que a auditoria admitiu no formato longo: ele entra dessaturado e com a
    etiqueta "REPRESENTAÇÃO VISUAL" no rodapé, enquanto os outros clipes da
    mesma montagem seguem coloridos e sem etiqueta.

    `cartelas`: imagens dos momentos-chave (cartelas.py) — [{"imagem": str,
    "inicio_s": float, "dur_s": float}, ...], cada uma um PNG do TAMANHO EXATO
    da tela do celular. Entram por arrasto da mão, ocupando a tela toda no
    lugar do clipe, e saem pelo arrasto de volta.

    `figuras`: gráficos, tabelas e cartazes gerados pelo gpt-image-2
    (figuras.py), no mesmo formato das cartelas e tratados exatamente como
    elas na montagem; a diferença está na origem da imagem, não no ffmpeg.

    `publico`: "brasil" ou "usa" — define o idioma do crédito de reprodução.

    `formato`: "curto" (Shorts 9:16, com legendas queimadas) ou "longo"
    (--long-take: 16:9, sem legendas) — muda a orientação do aparelho (em pé /
    deitado, via cenario.py) e a tolerância de tempo de cada clipe na tela.
    """
    _exigir_ffmpeg()
    if not FONTE_CREDITO.is_file():
        raise SystemExit(
            f"Fonte do crédito de reprodução ausente ({FONTE_CREDITO}) — sem "
            "ela o vídeo sairia sem creditar a conta de origem dos clipes; "
            "abortando."
        )

    duracao = duracao_audio(narracao) + RESPIRO_FINAL
    # Cartelas e figuras compartilham a camada: as duas são imagens que tomam a
    # tela do celular pelo mesmo arrasto. Ordenadas pelo início para o log e a
    # pilha ficarem previsíveis.
    cartelas = sorted(
        (cartelas or []) + (figuras or []), key=lambda c: float(c["inicio_s"])
    )

    # Celular sobre a cama: a área útil de TUDO passa a ser o retângulo da tela.
    cenario, (tela_x, tela_y, tela_l, tela_a) = gerar_cenario_celular(
        largura, altura, destino.parent / "cenario_celular.png"
    )

    sobreposicoes = _ordenar(sobreposicoes)
    estaticas = [s for s in sobreposicoes if not _e_video(s["caminho"])]
    if estaticas:
        raise SystemExit(
            "Imagem estática na montagem é proibida (o formato usa só clipes "
            "de vídeo do X): "
            + ", ".join(Path(s["caminho"]).name for s in estaticas)
        )
    janelas = _calcular_janelas(sobreposicoes, duracao)
    pares = list(zip(sobreposicoes, janelas))
    n = len(pares)
    max_exibicao = MAX_EXIBICAO_LONGO if formato == "longo" else MAX_EXIBICAO
    for s, (ini, fim) in pares:
        if fim - ini > max_exibicao + 0.01:
            print(
                f"[edicao] aviso: clipe fica {fim - ini:.1f}s na tela "
                f"(acima do alvo de {max_exibicao:.0f}s)"
            )

    # Janelas do carrossel: em cada uma a tela sai do clipe e vai para a imagem
    # do momento, voltando ao clipe no fim.
    janelas_cart = [
        (
            max(0.0, float(c["inicio_s"])),
            min(float(c["inicio_s"]) + float(c["dur_s"]), duracao),
        )
        for c in cartelas
    ]
    # Janela curta demais não comporta os dois arrastos mais as duas aparições
    # da mão: as duas aparições se encavalariam e a expressão de presença
    # passaria de 1, jogando a mão para fora do lugar. Quem chama já respeita
    # DUR_MINIMA (2,2s nas cartelas, 2,6s nas figuras); isto é a guarda.
    pares_cart = [
        (c, (a, b))
        for c, (a, b) in zip(cartelas, janelas_cart)
        if b - a >= MIN_JANELA_CARROSSEL
    ]
    for c, (a, b) in zip(cartelas, janelas_cart):
        if b - a < MIN_JANELA_CARROSSEL:
            print(
                f"[edicao] aviso: janela de {b - a:.1f}s em {a:.1f}s é curta "
                f"demais para o arrasto (mínimo {MIN_JANELA_CARROSSEL:.1f}s); "
                "imagem descartada."
            )
    cartelas = [c for c, _ in pares_cart]
    janelas_cart = [j for _, j in pares_cart]
    # Deslocamento do carrossel, de 0 (vídeo na tela) a 1 (imagem na tela). O
    # MESMO valor move o clipe para fora e a imagem para dentro — é isso que
    # mantém as duas coladas durante o arrasto.
    desloc = _expr_progresso(janelas_cart, T_ARRASTO, T_ARRASTO)

    # Base preta (entrada 0); narração é a entrada 1. Com cobertura total, a
    # base só aparece se faltarem clipes.
    filtros = [f"[0:v]fps={FPS},format=rgba[base]"]
    corrente = "base"

    comando = [
        "ffmpeg", "-y", "-hide_banner",
        "-f", "lavfi",
        "-i", f"color=c=black:s={largura}x{altura}:r={FPS}:d={duracao:.2f}",
        "-i", str(narracao),
    ]

    for i, (s, (ini, fim)) in enumerate(pares):
        fim_render = min(fim + CROSSFADE, duracao)
        dur_render = fim_render - ini
        # Clipe: repete em loop se for mais curto que a janela; -t corta.
        comando += ["-stream_loop", "-1", "-t", f"{dur_render:.2f}",
                    "-i", str(s["caminho"])]

        idx = i + 2

        fade_in = (
            f"fade=t=in:st=0:d={CROSSFADE}:alpha=1," if i > 0 else ""
        )
        fade_out = (
            f"fade=t=out:st={max(0.0, dur_render - CROSSFADE):.2f}:d={CROSSFADE}:alpha=1,"
            if i < n - 1 else ""
        )

        filtros.append(
            f"[{idx}:v]fps={FPS},format=rgba,split[in_bg{i}][in_fg{i}]"
        )

        # Clipe marcado como representação visual perde a cor — convenção de
        # material ilustrativo/de arquivo. Fundo e frente juntos: dessaturar só
        # a frente deixaria um halo colorido em volta do clipe em P&B.
        dessat = f"eq=saturation={REPR_SATURACAO}," if s.get("representacao") else ""

        # Fundo: o próprio clipe cobrindo a TELA do celular, borrado e levemente
        # escuro. É ele que mantém a tela sempre preenchida quando o clipe não
        # tem a proporção do aparelho.
        filtros.append(
            f"[in_bg{i}]scale={tela_l}:{tela_a}:force_original_aspect_ratio=increase,"
            f"crop={tela_l}:{tela_a},gblur=sigma={BLUR_SIGMA},"
            f"eq=brightness={ESCURECER},{dessat}"
            f"{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[bg{i}]"
        )

        # Frente: o clipe nítido no maior tamanho que CABE na tela, centrado.
        # Sem zoom nem deslize — o clipe já tem movimento próprio; a transição
        # editorial é um crossfade curto e limpo.
        filtros.append(
            f"[in_fg{i}]scale={tela_l}:{tela_a}:force_original_aspect_ratio=decrease,"
            f"format=rgba,{dessat}{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[fg{i}]"
        )

        # Sobrepõe fundo e depois a frente, ambos ativos na janela (+ crossfade),
        # ancorados no canto da tela e ARRASTADOS para a esquerda pelo carrossel.
        filtros.append(
            f"[{corrente}][bg{i}]overlay=x='{tela_x}-{tela_l}*({desloc})':y={tela_y}"
            f":eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[b{i}]"
        )
        filtros.append(
            f"[b{i}][fg{i}]overlay="
            f"x='{tela_x}+({tela_l}-w)/2-{tela_l}*({desloc})'"
            f":y='{tela_y}+({tela_a}-h)/2'"
            f":eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[f{i}]"
        )
        corrente = f"f{i}"

    # Imagens do carrossel (cartelas.py e figuras.py): cada uma é um PNG do
    # tamanho da tela, que espera FORA dela, à direita, e entra empurrada pelo
    # mesmo deslocamento que tira o clipe. Entram ANTES do cenário porque é o
    # corpo do aparelho que as recorta na moldura.
    prox_entrada = 2 + n
    for j, (c, (ini, fim)) in enumerate(zip(cartelas, janelas_cart)):
        idx_cart = prox_entrada
        prox_entrada += 1
        comando += [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{duracao:.2f}",
            "-i", str(c["imagem"]),
        ]
        # Deslocamento só desta janela: duas cartelas nunca andam juntas.
        d_j = _expr_progresso([(ini, fim)], T_ARRASTO, T_ARRASTO)
        filtros.append(f"[{idx_cart}:v]format=rgba[cart{j}]")
        filtros.append(
            f"[{corrente}][cart{j}]"
            f"overlay=x='{tela_x}+{tela_l}*(1-({d_j}))':y={tela_y}"
            f":eof_action=repeat"
            f":enable='between(t,{ini:.3f},{fim:.3f})'[vcart{j}]"
        )
        corrente = f"vcart{j}"

    # O celular entra por cima do conteúdo: opaco em tudo menos no buraco da
    # tela, ele é que recorta o carrossel na moldura do aparelho. Vem ANTES da
    # mão, das legendas e do crédito — esses ficam sobre o aparelho.
    comando += [
        "-loop", "1", "-framerate", str(FPS), "-t", f"{duracao:.2f}",
        "-i", str(cenario),
    ]
    filtros.append(f"[{prox_entrada}:v]format=rgba[aparelho]")
    filtros.append(f"[{corrente}][aparelho]overlay=0:0:eof_action=repeat[vcel]")
    corrente = "vcel"
    prox_entrada += 1

    # A MÃO que arrasta: sobe de fora do quadro pouco antes de cada arrasto,
    # acompanha o dedo pela tela e desce depois. Duas aparições por imagem — a
    # de ida (arrasta o vídeo para a esquerda) e a de volta (arrasta a imagem
    # para a direita) —, e o percurso do dedo é o mesmo lido nos dois sentidos,
    # porque é o próprio deslocamento do carrossel que o comanda.
    if janelas_cart:
        mao, (ponta_x, ponta_y) = gerar_mao(
            tela_l, tela_a, destino.parent / "mao.png"
        )
        janelas_mao: list[tuple[float, float]] = []
        for ini, fim in janelas_cart:
            janelas_mao.append(
                (
                    max(0.0, ini - MAO_ANTECIPACAO),
                    min(duracao, ini + T_ARRASTO + MAO_PERMANENCIA),
                )
            )
            janelas_mao.append(
                (
                    max(0.0, fim - T_ARRASTO - MAO_ANTECIPACAO),
                    min(duracao, fim + MAO_PERMANENCIA),
                )
            )
        presenca = _expr_progresso(janelas_mao, MAO_SUBIDA, MAO_DESCIDA)
        toque_x = tela_x + tela_l * MAO_X_INICIO - ponta_x
        percurso = tela_l * (MAO_X_INICIO - MAO_X_FIM)
        repouso_y = tela_y + tela_a * MAO_Y_TELA - ponta_y

        comando += [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{duracao:.2f}",
            "-i", str(mao),
        ]
        filtros.append(f"[{prox_entrada}:v]format=rgba[mao]")
        filtros.append(
            f"[{corrente}][mao]"
            f"overlay=x='{toque_x:.1f}-{percurso:.1f}*({desloc})'"
            f":y='{repouso_y:.1f}+({altura}-{repouso_y:.1f})*(1-({presenca}))'"
            f":eof_action=repeat"
            f":enable='{_expr_janelas(janelas_mao)}'[vmao]"
        )
        corrente = "vmao"
        prox_entrada += 1

    if legendas is not None:
        fontes = RAIZ / "fonts"
        filtro_ass = f"ass='{_caminho_filtro(legendas)}'"
        if fontes.is_dir():
            filtro_ass += f":fontsdir='{_caminho_filtro(fontes)}'"
        filtros.append(f"[{corrente}]{filtro_ass}[vleg]")
        corrente = "vleg"

    # Crédito de reprodução no canto superior direito DA TELA: linha 1 fixa e
    # linha 2 com a conta do post de origem do clipe que está na tela — cada
    # clipe liga o seu crédito na sua janela, DESCONTADAS as janelas do
    # carrossel: enquanto a imagem do momento ocupa a tela, o clipe não está
    # visível e o crédito dele creditaria a coisa errada (a imagem traz o seu).
    rotulo_fixo, rotulo_conta = CREDITO_TEXTOS.get(publico, CREDITO_TEXTOS["brasil"])
    menor_tela = min(tela_l, tela_a)
    fonte = round(menor_tela * CREDITO_FONTE_FRAC)
    margem = round(tela_l * CREDITO_MARGEM_FRAC)
    pad = max(6, round(fonte * CREDITO_TARJA_PAD_FRAC))
    y1 = tela_y + round(tela_a * CREDITO_Y_FRAC)
    y2 = y1 + round(fonte * CREDITO_ENTRELINHA) + 2 * pad
    base_credito = (
        f"drawtext=fontfile='{_caminho_filtro(FONTE_CREDITO)}'"
        f":fontcolor=white:fontsize={fonte}"
        f":box=1:boxcolor=black@{CREDITO_TARJA}:boxborderw={pad}"
    )
    seq = 0
    borda_direita = tela_x + tela_l - margem
    for s, (ini, fim) in pares:
        visiveis = _subtrair((ini, fim), janelas_cart)
        if not visiveis:
            continue
        linhas = [rotulo_fixo]
        conta = (s.get("conta") or "").strip()
        if conta:
            linhas.append(rotulo_conta.format(conta=conta))
        enable = f":enable='{_expr_janelas(visiveis)}'"
        for texto, y in zip(linhas, (y1, y2)):
            filtros.append(
                f"[{corrente}]{base_credito}"
                f":text='{_texto_drawtext(texto)}'"
                f":x={borda_direita}-text_w:y={y}"
                f"{enable}[vcred{seq}]"
            )
            corrente = f"vcred{seq}"
            seq += 1

    # Etiqueta de representação visual no rodapé esquerdo da tela, só nas
    # janelas dos clipes marcados (também descontado o carrossel: com a imagem
    # na tela não há material de telejornal a sinalizar). A etiqueta acompanha
    # o clipe de ponta a ponta enquanto ele está visível, senão o material de
    # emissora aparece um trecho sem aviso nenhum — que é justamente o que a
    # marcação existe para impedir.
    texto_repr = REPR_TEXTOS.get(publico, REPR_TEXTOS["brasil"])
    fonte_repr = round(menor_tela * REPR_FONTE_FRAC)
    margem_repr = tela_x + round(tela_l * REPR_MARGEM_FRAC)
    pad_repr = max(6, round(fonte_repr * CREDITO_TARJA_PAD_FRAC))
    y_repr = tela_y + round(tela_a * REPR_Y_FRAC)
    for s, (ini, fim) in pares:
        if not s.get("representacao"):
            continue
        visiveis = _subtrair((ini, fim), janelas_cart)
        if not visiveis:
            continue
        filtros.append(
            f"[{corrente}]drawtext=fontfile='{_caminho_filtro(FONTE_CREDITO)}'"
            f":fontcolor=white:fontsize={fonte_repr}"
            f":box=1:boxcolor=black@{CREDITO_TARJA}:boxborderw={pad_repr}"
            f":text='{_texto_drawtext(texto_repr)}'"
            f":x={margem_repr}:y={y_repr}"
            f":enable='{_expr_janelas(visiveis)}'[vrepr{seq}]"
        )
        corrente = f"vrepr{seq}"
        seq += 1

    # Áudio: narração + woosh em cada transição de clipe. SEM música de fundo
    # (removida em 2026-07-30). O primeiro clipe não tem transição de entrada.
    mapa_audio = "1:a"
    transicoes = [ini for _, (ini, _) in pares[1:]]
    usar_woosh = WOOSH.is_file() and bool(transicoes)
    entradas_mix: list[str] = []
    if usar_woosh:
        filtros.append(
            "[1:a]aformat=channel_layouts=stereo:sample_rates=44100[narr]"
        )
        idx_woosh = prox_entrada
        prox_entrada += 1
        comando += ["-i", str(WOOSH)]
        m = len(transicoes)
        filtros.append(
            f"[{idx_woosh}:a]asplit={m}" + "".join(f"[ws{k}]" for k in range(m))
        )
        for k, t in enumerate(transicoes):
            ms = max(0, round(t * 1000))
            filtros.append(
                f"[ws{k}]adelay={ms}:all=1,"
                f"aformat=channel_layouts=stereo:sample_rates=44100,"
                f"volume={WOOSH_VOL}[wd{k}]"
            )
            entradas_mix.append(f"[wd{k}]")
    if entradas_mix:
        filtros.append(
            f"[narr]{''.join(entradas_mix)}amix=inputs={len(entradas_mix) + 1}"
            f":normalize=0:duration=first,alimiter=limit=0.97[aout]"
        )
        mapa_audio = "[aout]"

    comando += [
        "-filter_complex", ";".join(filtros),
        "-map", f"[{corrente}]",
        "-map", mapa_audio,
        "-t", f"{duracao:.2f}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(destino),
    ]

    print("[edicao] Montando vídeo final com ffmpeg...")
    resultado = subprocess.run(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise SystemExit(f"ffmpeg falhou:\n{resultado.stderr[-2000:]}")

    print(f"[edicao] Vídeo final salvo em {destino}")
    return destino
