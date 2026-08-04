"""Montagem final do vídeo com ffmpeg.

O vídeo é montado SOMENTE com clipes de vídeo dos posts do X (imagem estática
é proibida — a montagem aborta se receber uma). O fundo de cada momento é o
PRÓPRIO clipe daquele trecho, ampliado para cobrir a tela toda e BORRADO; por
cima entra o clipe nítido em largura total, centrado. Os clipes cobrem 100% da
narração — nunca há um instante sem imagem na tela — com um crossfade curto e
limpo entre si (corte editorial, sem deslizes). A narração TTS (sem silêncios)
é a única faixa contínua — o vídeo NÃO tem música de fundo (removida em
2026-07-30) —, e o crédito de reprodução ("Reprodução Imagem: X" + "Conta
@usuario" do post de origem) fica no canto superior direito enquanto o clipe
daquela conta está na tela.

Clipe marcado como REPRESENTAÇÃO VISUAL (material de telejornal, que só o
formato longo admite — ver auditoria.py) entra dessaturado e com etiqueta no
rodapé esquerdo, para não se confundir com material próprio do canal. A marca
é por clipe: os demais da mesma montagem seguem coloridos e sem etiqueta.

No FORMATO LONGO o clipe não ocupa o quadro inteiro: ele aparece dentro da TV
de uma sala de estar (cenario.py), identidade visual só desse formato. A área
útil do clipe passa a ser o retângulo da TELA — o fundo borrado preenche a
tela quando o clipe é vertical, e o PNG da sala entra por cima recortando o
clipe na moldura. Crédito, etiquetas e sobreposições ficam SOBRE a sala.

Por cima disso entra UMA camada de sobreposição, como sequências de PNG RGBA já
renderizadas: as CARTELAS de imagem dos momentos-chave (cartelas.py) e as
FIGURAS desenhadas pelo gpt-image-2 (figuras.py), ambas no miolo da tela. As
janelas das duas nunca coincidem — quem monta as figuras recebe as janelas das
cartelas e desvia delas. Enquanto uma delas está na tela, tudo que está atrás
sai de foco (CARTELA_BLUR_SIGMA), para a imagem do momento-chave não disputar
atenção com o clipe em movimento; o desfoque ENTRA E SAI EM RAMPA, acompanhando
o movimento do cartão (ver `_filtros_desfoque`).

Os INFOGRÁFICOS ANIMADOS montados em ffmpeg (contadores e barras renderizados
em Pillow pelo antigo grafico.py) foram REMOVIDOS em 2026-08-04, a pedido do
usuário: os "big numbers" da tela passam a vir só das figuras do gpt-image-2,
que já cobrem o mesmo repertório com identidade visual única. O módulo
grafico.py foi apagado junto — não reintroduzir sem pedido explícito.
"""

import subprocess
import shutil
from pathlib import Path

from .cenario import gerar_cenario_tv
from .config import RAIZ

FPS = 30
MIN_EXIBICAO = 3.0  # segundos mínimos de exibição de cada clipe
MAX_EXIBICAO = 15.0  # segundos máximos de exibição de cada clipe (só aviso)
# No formato longo (16:9, 90-120s) o clipe segura janelas maiores: com 8
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

# TRILHA MUSICAL REMOVIDA em 2026-07-30 (pedido do usuário). O vídeo sai só com
# a narração e os wooshes das transições: o formato virou análise/educacional e
# música de fundo disputa atenção com a informação falada. O arquivo
# assets/trilha.mp3 foi apagado do repositório junto com este código — não
# reintroduzir mixagem de música sem pedido explícito.

# Crédito de reprodução no canto superior direito, por clipe: linha 1 fixa
# ("Reprodução Imagem: X") e linha 2 com a conta do post de origem. Estética
# editorial de rede social: Archivo Black branca sobre tarja preta
# semitransparente, alinhada à direita. Some enquanto um infográfico ocupa o
# terço superior (mesmo mecanismo que escondia o antigo branding).
FONTE_CREDITO = RAIZ / "fonts" / "ArchivoBlack-Regular.ttf"
CREDITO_TEXTOS = {
    "brasil": ("Reprodução Imagem: X", "Conta {conta}"),
    "usa": ("Image Credit: X", "Account {conta}"),
}
# O tamanho da fonte é fração do LADO MENOR do vídeo: no formato vertical o
# lado menor é a largura (nada muda), e no 16:9 ele impede que o crédito saia
# gigante por causa dos 1920 de largura.
CREDITO_FONTE_FRAC = 0.026  # tamanho da fonte como fração do lado menor
CREDITO_MARGEM_FRAC = 0.030  # distância da borda direita (fração da largura)
CREDITO_Y_FRAC = 0.045  # distância do topo como fração da altura
CREDITO_ENTRELINHA = 1.55  # distância entre as duas linhas (fração da fonte)
CREDITO_TARJA = 0.45  # opacidade da tarja preta atrás do texto
CREDITO_TARJA_PAD_FRAC = 0.45  # respiro da tarja ao redor do texto (fração da fonte)

# Marcação de REPRESENTAÇÃO VISUAL: no formato longo o material de telejornal
# não é mais vetado (auditoria.py) — entra dessaturado e etiquetado no rodapé
# esquerdo, para o espectador não tomar cobertura de terceiro por material do
# canal. Só o clipe marcado ("representacao" na sobreposição) recebe o
# tratamento; os demais seguem coloridos e sem etiqueta na mesma montagem.
REPR_SATURACAO = 0.10  # 0 = P&B puro; sobra um resto de cor, menos chapado
REPR_TEXTOS = {
    "brasil": "REPRESENTAÇÃO VISUAL",
    "usa": "ILLUSTRATIVE FOOTAGE",
}
REPR_FONTE_FRAC = 0.024  # fração do lado menor (mesma lógica do crédito)
REPR_MARGEM_FRAC = 0.030  # distância da borda esquerda (fração da largura)
REPR_Y_FRAC = 0.912  # distância do topo como fração da altura (rodapé)

# Desfoque aplicado ao que está ATRÁS de uma cartela ou figura, enquanto ela
# está na tela: tira o clipe em movimento da disputa pela atenção enquanto a
# imagem do momento-chave é lida. Vale só no intervalo de cada cartela.
# Subiu de 14 para 20 em 2026-08-04 junto com o aumento dos cartões: cartão
# maior deixa menos fundo à mostra, e o pouco que sobra precisa sair de foco
# com mais convicção para não virar uma moldura de ruído em volta da imagem.
CARTELA_BLUR_SIGMA = 20
# RAMPA do desfoque (2026-08-04, pedido do usuário: "deixe o fundo borrado …
# com uma animação suave"). O desfoque entrava e saía de um quadro para o
# outro, e um corte seco de nitidez no meio de um clipe em movimento é
# exatamente o tipo de solavanco que o resto da montagem evita.
#
# gblur NÃO aceita expressão por quadro em `sigma` (só `enable`, de timeline),
# então a rampa é feita por NÍVEIS: CARTELA_BLUR_NIVEIS filtros gblur, cada um
# com um sigma fixo e ligado apenas nas fatias de tempo em que aquele nível
# vale — somadas as fatias de TODAS as cartelas. Como as fatias são disjuntas,
# o custo total é o de um único desfoque; o que muda é só quando cada um liga.
CARTELA_BLUR_NIVEIS = 5
# Duração de cada ponta da rampa. Casada com o movimento do cartão (T_ENTRADA /
# T_SAIDA em cartelas.py e figuras.py, 0,45-0,55s): o fundo desfoca enquanto o
# cartão sobe e volta ao foco enquanto ele sai. Precisa caber duas vezes dentro
# da menor janela de cartela (DUR_MINIMA = 2,2s) e não pode passar do respiro
# entre cartelas (GAP_CARTELAS = 1,2s), senão duas rampas se encavalariam.
CARTELA_BLUR_RAMPA = 0.45


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


def _filtros_desfoque(
    janelas: list[tuple[float, float]], entrada: str, saida: str
) -> list[str]:
    """Filtros gblur que desfocam o fundo em RAMPA nas janelas das cartelas.

    Um gblur por NÍVEL de sigma (CARTELA_BLUR_NIVEIS), cada um ligado só nas
    fatias de tempo em que aquele nível vale, somadas todas as janelas. Para
    uma janela (ini, fim) e uma rampa de duração R dividida em N fatias:

    - nível j (1..N-1) vale em [ini+(j-1)R/N, ini+jR/N) na subida e no espelho
      dela na descida — duas fatias curtas;
    - nível N (sigma cheio) vale de ini+(N-1)R/N até fim-(N-1)R/N, um intervalo
      contíguo que já engloba o platô.

    Devolve a lista de filtros encadeando `entrada` até `saida`; lista vazia
    quando não há janela nenhuma (o chamador segue com `entrada`).
    """
    if not janelas:
        return []

    fatias: dict[int, list[tuple[float, float]]] = {}
    n = CARTELA_BLUR_NIVEIS
    passo = CARTELA_BLUR_RAMPA / n
    for ini, fim in janelas:
        # Janela curta demais para as duas rampas: encolhe o passo em vez de
        # deixar a subida invadir a descida.
        p = min(passo, max((fim - ini) / (2 * n), 0.01))
        for j in range(1, n):
            fatias.setdefault(j, []).extend(
                [
                    (ini + (j - 1) * p, ini + j * p),
                    (fim - j * p, fim - (j - 1) * p),
                ]
            )
        fatias.setdefault(n, []).append((ini + (n - 1) * p, fim - (n - 1) * p))

    filtros = []
    corrente = entrada
    for j in sorted(fatias):
        sigma = CARTELA_BLUR_SIGMA * j / n
        enable = "+".join(
            f"between(t,{a:.3f},{b:.3f})" for a, b in sorted(fatias[j])
        )
        alvo = saida if j == max(fatias) else f"{saida}_n{j}"
        filtros.append(
            f"[{corrente}]gblur=sigma={sigma:.2f}:enable='{enable}'[{alvo}]"
        )
        corrente = alvo
    return filtros


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
    """Monta o vídeo final: clipes do X com fundo borrado do próprio clipe.

    `sobreposicoes`: [{"caminho": Path, "inicio_frac": float|None,
    "fim_frac": float|None, "conta": str, "representacao": bool}, ...] —
    frações (0 a 1) da narração em que o clipe entra; None usa distribuição
    uniforme. SOMENTE clipes de vídeo (imagem estática aborta). Os clipes
    cobrem 100% da narração (sem instante vazio) e fazem crossfade entre si;
    "conta" (@usuario do post de origem) alimenta o crédito de reprodução no
    canto superior direito. "representacao" marca o clipe de telejornal que a
    auditoria admitiu no formato longo: ele entra dessaturado e com a etiqueta
    "REPRESENTAÇÃO VISUAL" no rodapé, enquanto os outros clipes da mesma
    montagem seguem coloridos e sem etiqueta.

    `cartelas`: imagens emolduradas nos momentos-chave (cartelas.py) —
    [{"pattern": str, "inicio_s": float, "dur_s": float}, ...], sequências de
    PNGs RGBA sobrepostas ao vídeo. Ficam no miolo da tela e trazem o próprio
    crédito, então NÃO desligam o crédito de reprodução do topo.

    `figuras`: gráficos, tabelas e cartazes gerados pelo gpt-image-2
    (figuras.py), no mesmo formato das cartelas — sobem de baixo do quadro e
    saem por cima. São tratadas exatamente como cartelas na montagem (mesma
    camada, mesma rampa de desfoque do que está atrás); a diferença está na
    origem da imagem, não no ffmpeg.

    `publico`: "brasil" ou "usa" — define o idioma do crédito de reprodução.

    `formato`: "curto" (Shorts 9:16, com legendas queimadas) ou "longo"
    (--long-take: 16:9, 90-120s, sem legendas) — muda só a tolerância de
    tempo de cada clipe na tela; o resto da montagem é o mesmo.
    """
    _exigir_ffmpeg()
    if not FONTE_CREDITO.is_file():
        raise SystemExit(
            f"Fonte do crédito de reprodução ausente ({FONTE_CREDITO}) — sem "
            "ela o vídeo sairia sem creditar a conta de origem dos clipes; "
            "abortando."
        )

    duracao = duracao_audio(narracao) + RESPIRO_FINAL
    # Cartelas e figuras compartilham a camada: as duas são sequências de PNG
    # RGBA no miolo da tela, com o mesmo borrão por trás. Ordenadas pelo início
    # para o log e a pilha ficarem previsíveis.
    cartelas = sorted(
        (cartelas or []) + (figuras or []), key=lambda c: float(c["inicio_s"])
    )

    # Cenário de sala com TV: identidade visual do formato longo. O clipe passa
    # a ser escalado para o retângulo da TELA e o PNG da sala entra por cima,
    # opaco em tudo menos no buraco da tela. O Short segue em tela cheia.
    cenario = None
    tela_x, tela_y, tela_l, tela_a = 0, 0, largura, altura
    if formato == "longo":
        cenario, (tela_x, tela_y, tela_l, tela_a) = gerar_cenario_tv(
            largura, altura, destino.parent / "cenario_tv.png"
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

        # Fundo: o próprio clipe cobrindo a área útil, borrado e levemente
        # escuro. No formato longo a área útil é a TELA da TV, não o quadro —
        # é o que mantém a tela sempre preenchida quando o clipe é vertical.
        filtros.append(
            f"[in_bg{i}]scale={tela_l}:{tela_a}:force_original_aspect_ratio=increase,"
            f"crop={tela_l}:{tela_a},gblur=sigma={BLUR_SIGMA},"
            f"eq=brightness={ESCURECER},{dessat}"
            f"{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[bg{i}]"
        )

        # Frente: o clipe nítido no maior tamanho que CABE na tela, centrado
        # (no vertical isso é a largura total, como sempre foi; no 16:9 é a
        # altura, e o clipe vertical do X vira uma faixa central sobre o fundo
        # borrado em vez de estourar para fora do quadro). Sem zoom nem
        # deslize — o clipe já tem movimento próprio; a transição editorial é
        # um crossfade curto e limpo.
        filtros.append(
            f"[in_fg{i}]scale={tela_l}:{tela_a}:force_original_aspect_ratio=decrease,"
            f"format=rgba,{dessat}{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[fg{i}]"
        )

        # Sobrepõe fundo e depois a frente, ambos ativos na janela (+ crossfade),
        # ancorados no canto da área útil (a tela da TV, no formato longo).
        filtros.append(
            f"[{corrente}][bg{i}]overlay={tela_x}:{tela_y}:eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[b{i}]"
        )
        filtros.append(
            f"[b{i}][fg{i}]overlay={tela_x}+({tela_l}-w)/2:{tela_y}+({tela_a}-h)/2"
            f":eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[f{i}]"
        )
        corrente = f"f{i}"

    # A sala entra por cima dos clipes: opaca em tudo menos no buraco da tela,
    # ela é que recorta o clipe na moldura da TV. Vem ANTES do crédito, das
    # legendas e das sobreposições — esses ficam sobre a sala, não dentro dela.
    prox_entrada = 2 + n
    if cenario is not None:
        comando += [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{duracao:.2f}",
            "-i", str(cenario),
        ]
        filtros.append(f"[{prox_entrada}:v]format=rgba[sala]")
        filtros.append(
            f"[{corrente}][sala]overlay=0:0:eof_action=repeat[vsala]"
        )
        corrente = "vsala"
        prox_entrada += 1

    # Borrão sob as cartelas: enquanto a imagem do momento-chave está na tela,
    # o que está atrás dela sai de foco, para a cartela não disputar atenção
    # com o clipe em movimento. Entra e sai em RAMPA, acompanhando o movimento
    # do cartão; só o intervalo de cada cartela é afetado.
    janelas_cart = [
        (
            max(0.0, float(c["inicio_s"])),
            min(float(c["inicio_s"]) + float(c["dur_s"]), duracao),
        )
        for c in cartelas
    ]
    filtros_blur = _filtros_desfoque(
        [(a, b) for a, b in janelas_cart if b > a], corrente, "vcartblur"
    )
    if filtros_blur:
        filtros += filtros_blur
        corrente = "vcartblur"

    if legendas is not None:
        fontes = RAIZ / "fonts"
        filtro_ass = f"ass='{_caminho_filtro(legendas)}'"
        if fontes.is_dir():
            filtro_ass += f":fontsdir='{_caminho_filtro(fontes)}'"
        filtros.append(f"[{corrente}]{filtro_ass}[vleg]")
        corrente = "vleg"

    # Crédito de reprodução no canto superior direito (sobre as legendas):
    # linha 1 fixa e linha 2 com a conta do post de origem do clipe que está
    # na tela — cada clipe liga o seu crédito na sua janela. `prox_entrada` já
    # vem numerando as entradas extras do ffmpeg (cenário, cartelas, woosh)
    # desde a sobreposição da sala.
    #
    # O crédito não desliga mais em janela nenhuma: ele desligava sob os
    # infográficos animados, que ocupavam o terço superior e cobriam o canto
    # direito. Com eles removidos (2026-08-04), o que sobra na tela são as
    # cartelas e as figuras, que ficam no MIOLO e nunca encostaram no crédito.
    rotulo_fixo, rotulo_conta = CREDITO_TEXTOS.get(publico, CREDITO_TEXTOS["brasil"])
    fonte = round(min(largura, altura) * CREDITO_FONTE_FRAC)
    margem = round(largura * CREDITO_MARGEM_FRAC)
    pad = max(6, round(fonte * CREDITO_TARJA_PAD_FRAC))
    y1 = round(altura * CREDITO_Y_FRAC)
    y2 = y1 + round(fonte * CREDITO_ENTRELINHA) + 2 * pad
    base_credito = (
        f"drawtext=fontfile='{_caminho_filtro(FONTE_CREDITO)}'"
        f":fontcolor=white:fontsize={fonte}"
        f":box=1:boxcolor=black@{CREDITO_TARJA}:boxborderw={pad}"
    )
    seq = 0
    for s, (ini, fim) in pares:
        linhas = [rotulo_fixo]
        conta = (s.get("conta") or "").strip()
        if conta:
            linhas.append(rotulo_conta.format(conta=conta))
        enable = f":enable='between(t,{ini:.2f},{fim:.2f})'"
        for texto, y in zip(linhas, (y1, y2)):
            filtros.append(
                f"[{corrente}]{base_credito}"
                f":text='{_texto_drawtext(texto)}'"
                f":x=w-text_w-{margem}:y={y}"
                f"{enable}[vcred{seq}]"
            )
            corrente = f"vcred{seq}"
            seq += 1

    # Etiqueta de representação visual no rodapé esquerdo, só nas janelas dos
    # clipes marcados. Não some sob as cartelas (que ficam no miolo da tela): a
    # etiqueta precisa acompanhar o clipe de ponta a ponta, senão o material de
    # telejornal aparece um trecho sem aviso nenhum — que é justamente o que a
    # marcação existe para impedir.
    texto_repr = REPR_TEXTOS.get(publico, REPR_TEXTOS["brasil"])
    fonte_repr = round(min(largura, altura) * REPR_FONTE_FRAC)
    margem_repr = round(largura * REPR_MARGEM_FRAC)
    pad_repr = max(6, round(fonte_repr * CREDITO_TARJA_PAD_FRAC))
    y_repr = round(altura * REPR_Y_FRAC)
    for s, (ini, fim) in pares:
        if not s.get("representacao"):
            continue
        filtros.append(
            f"[{corrente}]drawtext=fontfile='{_caminho_filtro(FONTE_CREDITO)}'"
            f":fontcolor=white:fontsize={fonte_repr}"
            f":box=1:boxcolor=black@{CREDITO_TARJA}:boxborderw={pad_repr}"
            f":text='{_texto_drawtext(texto_repr)}'"
            f":x={margem_repr}:y={y_repr}"
            f":enable='between(t,{ini:.2f},{fim:.2f})'[vrepr{seq}]"
        )
        corrente = f"vrepr{seq}"
        seq += 1

    # Cartelas de imagem (cartelas.py) e figuras geradas (figuras.py): a
    # imagem emoldurada do momento-chave entra por cima do clipe, no miolo da
    # tela, com o próprio crédito. É a camada mais alta da montagem.
    for j, (c, (ini, fim)) in enumerate(zip(cartelas, janelas_cart)):
        idx_cart = prox_entrada
        prox_entrada += 1
        comando += [
            "-framerate", str(FPS), "-start_number", "1", "-i", c["pattern"],
        ]
        filtros.append(
            f"[{idx_cart}:v]format=rgba,setpts=PTS-STARTPTS+{ini:.2f}/TB[cart{j}]"
        )
        filtros.append(
            f"[{corrente}][cart{j}]overlay=0:0:eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim:.2f})'[vcart{j}]"
        )
        corrente = f"vcart{j}"

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
    if usar_woosh:
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
