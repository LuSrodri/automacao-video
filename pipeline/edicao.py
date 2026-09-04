"""Montagem final do vídeo com ffmpeg.

O vídeo é montado SOMENTE com clipes de vídeo dos posts do X (imagem estática
é proibida — a montagem aborta se receber uma). O fundo de cada momento é o
PRÓPRIO clipe daquele trecho, ampliado para cobrir o quadro todo e BORRADO; por
cima entra o clipe nítido no maior tamanho que cabe, centrado. Os clipes cobrem
100% da narração — nunca há um instante sem imagem na tela — com um crossfade
curto e limpo entre si (corte editorial, sem deslizes). A narração TTS (sem
silêncios) é a única faixa contínua — o vídeo NÃO tem música de fundo (removida
em 2026-07-30) —, e o crédito de reprodução ("Reprodução Imagem: X" + "Conta
@usuario" do post de origem) fica no canto superior direito do quadro enquanto o
clipe daquela conta está na tela.

TELA CHEIA (2026-08-16, pedido do usuário). O conteúdo volta a ocupar o QUADRO
INTEIRO, com o preenchimento de fundo em desfoque do próprio clipe. Saíram os
CENÁRIOS que embrulhavam o vídeo: a moldura de smartphone sobre uma cama
(2026-08-09 a 2026-08-16) e, antes dela, a sala de estar com TV do formato
longo. O módulo `cenario.py` e a foto `fundo-cama.png` foram apagados junto, e
com eles a orientação do aparelho medida pelos clipes. Não reintroduzir cenário
nenhum sem pedido explícito.

RECORTE QUE ACOMPANHA O SUJEITO (2026-08-25, pedido do usuário). Até aqui o
clipe horizontal simplesmente ganhava a barra borrada em cima e embaixo do
quadro vertical: com fonte 1280x720 a faixa nítida era 1080x608 num quadro de
1920 de altura, 32% da tela, e os outros 68% eram desfoque. O clipe passou a ser
RECORTADO numa janela mais estreita que ANDA pelo quadro atrás de quem está em
cena. Quem decide o recorte e a trajetória é `enquadramento.py`; aqui entra o
filtro `crop` na frente do `scale` da camada nítida.

O CLIPE PREENCHE O QUADRO INTEIRO (2026-08-31, pedido explícito do usuário).
O recorte de 25/08 tinha teto de ampliação e parava antes do 9:16 cheio: a tela
saía preenchida na proporção `altura da fonte / 1200`, o que dava ~60% na fonte
720p que o X entrega na maioria dos clipes, e o resto seguia desfoque. O teto
saiu. A camada nítida agora escala por COBERTURA (`increase` + `crop=quadro`)
em vez de caber dentro dele (`decrease`), e é ISSO que garante o preenchimento
— não o plano de enquadramento. A diferença importa: sem plano (clipe já
vertical, sem folga, sem sujeito, OpenCV ausente, ffprobe mudo) a cobertura
recorta pelo CENTRO e o quadro fica cheio do mesmo jeito; com plano, a janela
já vem na proporção do quadro e a cobertura é um no-op que só absorve o
arredondamento par do `crop`. Vale nos dois sentidos: fonte mais DEITADA que o
quadro perde as laterais, fonte mais EM PÉ perde o topo e o pé.

O custo é nitidez, e foi aceito de olho aberto: 9:16 de uma fonte 720p é uma
janela de 404 px ampliada 2,67x. O fator sai no log de cada clipe justamente
para a conta não ficar implícita.

A camada borrada de fundo CONTINUA sendo montada, e não é sobra: ela é o que
aparece por baixo enquanto a camada nítida está em meio-fade no crossfade entre
dois clipes. O que ela deixou de ser é barra.

Isto NÃO é volta de cenário: o que está na tela continua sendo só o clipe.

CARROSSEL. As cartelas de imagem (cartelas.py) não são cartões sobrepostos ao
clipe: elas ocupam o quadro inteiro
e entram DESLIZANDO. No momento-chave o conteúdo corre PARA A ESQUERDA e a
imagem entra pela direita no lugar do vídeo; no fim da janela o movimento se
inverte e o vídeo volta. É um carrossel de duas posições: o clipe e a imagem do
momento, ambos deslocados pelo MESMO offset horizontal, de modo que a borda de
um encosta na do outro durante todo o deslize. O que sai do quadro é recortado
pela própria borda dele — não há máscara nenhuma no ffmpeg. O deslize sobreviveu
à volta da tela cheia porque o usuário pediu explicitamente para mantê-lo
(2026-08-10).

Com a imagem tomando o quadro inteiro, o DESFOQUE do que ficava atrás das
cartelas (CARTELA_BLUR_*) perdeu função e saiu em 2026-08-09: não há mais nada
atrás para tirar de foco. Os INFOGRÁFICOS ANIMADOS montados em ffmpeg
(grafico.py) já haviam sido REMOVIDOS em 2026-08-04, e as FIGURAS geradas pelo
gpt-image-2 (figuras.py) em 2026-08-24, por custo — a tela não tem mais "big
number" nenhum; não reintroduzir nem um nem outro sem pedido explícito.

ESTE MÓDULO É O DO SHORT desde 2026-08-25. O formato longo saiu daqui para
montagem_longa.py, onde ele é montado em partes separadas e coladas — a
mudança que o desenho do usuário pediu. O que ficou para trás junto: a camada
de MANCHETES, que só o longo usava, e o parâmetro `formato`, que agora só
escolhe a tolerância de tempo de cada clipe na tela. As constantes de crédito,
de representação visual e de desfoque continuam AQUI e são importadas de lá:
são as mesmas nos dois formatos, e duplicá-las era garantir que um dia
divergissem.

Clipe marcado como REPRESENTAÇÃO VISUAL (material de telejornal, que só o
formato longo admite — ver auditoria.py) entra dessaturado e com etiqueta no
rodapé esquerdo, para não se confundir com material próprio do canal. A marca é
por clipe: os demais da mesma montagem seguem coloridos e sem etiqueta.
"""

import shutil
import subprocess
import threading
import time
from pathlib import Path

from . import enquadramento
from . import influencer as inf
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

# --- Carrossel (deslize) -----------------------------------------------------
# Tempo de cada deslize, de uma ponta à outra da tela. 0,42s é a faixa em que o
# movimento lê como deslize e não como corte: abaixo de ~0,3 vira piscada, acima
# de ~0,6 o espectador espera o conteúdo que ainda está entrando. Os DOIS
# deslizes (o de ida, que traz a imagem, e o de volta, que devolve o vídeo)
# cabem DENTRO da janela da cartela, então DUR_MINIMA lá precisa continuar bem
# acima de 2 * T_ARRASTO.
T_ARRASTO = 0.42
# Tempo mínimo com a imagem PARADA na tela, entre os dois deslizes: sem ele a
# imagem entraria e já sairia, e ninguém leria o que ela mostra.
LEITURA_MINIMA = 1.0
# Janela mínima de uma imagem no carrossel: os dois deslizes mais a leitura.
MIN_JANELA_CARROSSEL = 2 * T_ARRASTO + LEITURA_MINIMA

# Crédito de reprodução no canto superior direito DO QUADRO, por clipe: linha 1
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
CREDITO_FONTE_FRAC = 0.030  # tamanho da fonte como fração do lado menor do quadro
CREDITO_MARGEM_FRAC = 0.035  # distância da borda direita (fração da largura)
CREDITO_Y_FRAC = 0.045  # distância do topo como fração da altura
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
REPR_FONTE_FRAC = 0.028  # fração do lado menor do quadro (mesma lógica do crédito)
REPR_MARGEM_FRAC = 0.035  # distância da borda esquerda
REPR_Y_FRAC = 0.912  # distância do topo como fração da altura


def versao_ffmpeg() -> str:
    """Primeira linha do `ffmpeg -version`, para o log.

    Existe por causa de 2026-08-24: os painéis de manchete sumiram do vídeo
    publicado sem erro nenhum, e a mesma montagem rendida aqui (ffmpeg 5.1.2 e
    8.1.1) os desenhava. Sem saber qual ffmpeg roda no container, a diferença
    entre o que se testa e o que se publica fica invisível. Usada pelos dois
    formatos (montagem_longa.py importa daqui).
    """
    try:
        saida = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, check=True
        )
        return (saida.stdout or "").splitlines()[0][:120]
    except (subprocess.CalledProcessError, OSError, IndexError):
        return "desconhecida"


def memoria_mb() -> float | None:
    """Memória residente do processo, em MB; None fora do Linux.

    Existe para achar onde o formato longo estoura os 8 GB do container. A
    métrica do Render mostra o container inteiro subindo de 95 MB para 8,3 GB em
    cinco minutos, sem dizer QUEM subiu — e medições de bancada descartaram os
    dois suspeitos óbvios (o `setpts` dos clipes e os PNGs loopados: 0,5 GB e
    0,46 GB de pico, longe do estouro). Sem marcar etapa por etapa, o resto é
    chute.
    """
    try:
        with open("/proc/self/status", encoding="utf-8") as arquivo:
            for linha in arquivo:
                if linha.startswith("VmRSS:"):
                    return int(linha.split()[1]) / 1024
    except OSError:
        pass
    return None


def marcar_memoria(etapa: str) -> None:
    """Imprime a memória do processo numa etapa; silencioso fora do Linux."""
    mb = memoria_mb()
    if mb is not None:
        print(f"[memoria] {etapa}: {mb:.0f} MB")


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


def dimensoes_video(video: Path) -> tuple[int, int] | None:
    """(largura, altura) do vídeo, ou None se o ffprobe não souber dizer.

    O arquivo local é a fonte de verdade da resolução, não a API do X: ela
    anuncia `width`/`height` do original, e `midia_x` baixa a maior VARIANTE
    MP4 que cabe no teto de bytes — que costuma ser menor.
    """
    try:
        saida = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0",
                str(video),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        larg, alt = saida.stdout.strip().split(",")[:2]
        return int(larg), int(alt)
    except (subprocess.CalledProcessError, OSError, ValueError):
        return None


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


def _material_util(sobreposicao: dict) -> float | None:
    """Segundos que a montagem consegue tirar de um clipe; None se não der para medir.

    Conta do `inicio_util_s` (por onde a montagem entra) até o fim do arquivo.
    Falha de ffprobe devolve None, e quem chama trata isso como "não sei" — o
    ajuste de janelas é acabamento e não pode derrubar a montagem.
    """
    try:
        dur = duracao_audio(Path(sobreposicao["caminho"]))
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None
    inicio = float(sobreposicao.get("inicio_util_s") or 0.0)
    return max(0.0, float(dur) - inicio)


def _tetos_do_material(
    sobreposicoes: list[dict], duracao: float
) -> list[float]:
    """Quanto tempo de tela cada clipe aguenta sem se repetir, em segundos.

    Desconta o CROSSFADE, que a montagem renderiza ALÉM do fim da janela (ver
    `dur_render`). Clipe que não deu para medir recebe a narração inteira como
    teto — sem medida ele não limita nada, que é o comportamento seguro aqui.
    """
    tetos = []
    for s in sobreposicoes:
        util = _material_util(s)
        tetos.append(duracao if util is None else max(0.0, util - CROSSFADE))
    return tetos


def _encaixar_no_material(
    sobreposicoes: list[dict],
    janelas: list[tuple[float, float]],
    duracao: float,
    tetos: list[float],
) -> list[tuple[float, float]]:
    """Reparte a narração de modo que nenhum clipe fique mais tempo do que tem.

    SÓ O SHORT passa por aqui, e só desde 2026-08-28 — é a metade de montagem
    do pedido "não coloque o vídeo em loop várias vezes, em vez disso, adeque o
    roteiro dentro do que cabe naquele vídeo selecionado da pauta". A outra
    metade (o roteiro nascer do tamanho do material) está em main.py e
    config.py; esta aqui é a garantia de que, mesmo assim, nenhuma janela
    ultrapasse o clipe que a preenche.

    As duas camadas são necessárias porque o planejador de cortes (cortes.py) é
    um LLM lendo a narração: ele decide ONDE cada clipe entra pelo sentido do
    texto, não pela metragem, e nada o impede de dar 18 segundos ao clipe de 9.
    Antes isso era invisível — `-stream_loop -1` repetia o clipe e o espectador
    via o mesmo pedaço duas vezes. Sem o loop, seria tela congelada no último
    quadro, que é pior. Então a janela cede.

    O ajuste é uma REPARTIÇÃO COM TETO, não um corte: o que sobra de uma janela
    estourada é redistribuído proporcionalmente entre as que ainda têm folga, e
    a soma continua sendo a narração inteira. Ele só roda quando alguma janela
    de fato estoura; no caso normal (clipe mais longo que a janela) devolve as
    janelas como vieram, e a decisão do planejador fica de pé.

    Quando o material não dá para a narração inteira nem redistribuindo, as
    janelas voltam como vieram, o aviso sai no log e a montagem RELIGA O LOOP
    nos clipes que estouram — não por preferência, mas porque os overlays usam
    `eof_action=pass` e clipe que acaba vira tela PRETA, não quadro congelado.
    Quem deveria ter evitado esse desfecho é a conferência de metragem em
    main.py, ANTES do TTS; aqui é fim de linha, e derrubar a execução com a
    narração já paga seria pior que repetir um clipe.
    """
    n = len(sobreposicoes)
    if n < 1:
        return janelas

    larguras = [fim - ini for ini, fim in janelas]
    if all(larg <= teto + 0.01 for larg, teto in zip(larguras, tetos)):
        return janelas

    if sum(tetos) < duracao - 0.01:
        print(
            f"[edicao] aviso: os {n} clipe(s) somam {sum(tetos):.1f}s de "
            f"material para {duracao:.1f}s de narração — a tela não fecha sem "
            "repetir clipe. As janelas ficam como vieram; a conferência de "
            "metragem (main.py) é que deveria ter barrado esta pauta."
        )
        return janelas

    # Repartição com teto: quem estourou é fixado no seu teto e o excedente vai
    # para quem tem folga, na proporção da janela que o planejador desenhou.
    # Repete porque redistribuir pode estourar um segundo clipe.
    alocado = list(larguras)
    for _ in range(n):
        excedente = sum(
            max(0.0, larg - teto) for larg, teto in zip(alocado, tetos)
        )
        if excedente <= 0.01:
            break
        alocado = [min(larg, teto) for larg, teto in zip(alocado, tetos)]
        folgas = [max(0.0, teto - larg) for larg, teto in zip(alocado, tetos)]
        total_folga = sum(folgas)
        if total_folga <= 0.01:
            break
        for i, folga in enumerate(folgas):
            alocado[i] += excedente * (folga / total_folga)

    ajustadas: list[tuple[float, float]] = []
    t = 0.0
    for i, larg in enumerate(alocado):
        fim = duracao if i == n - 1 else min(t + larg, duracao)
        ajustadas.append((t, fim))
        t = fim
    mudou = [
        f"{Path(s['caminho']).name}: {b - a:.1f}s -> {d - c:.1f}s"
        for s, (a, b), (c, d) in zip(sobreposicoes, janelas, ajustadas)
        if abs((b - a) - (d - c)) > 0.2
    ]
    if mudou:
        print("[edicao] janelas encaixadas no material — " + "; ".join(mudou))
    return ajustadas


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

    Aceleração e desaceleração nas pontas: conteúdo que parte e para na
    velocidade máxima lê como corte, não como deslize. Escrito como expressão
    porque `overlay` avalia x/y por quadro — não há como pré-calcular a curva em
    Python.
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
    publico: str = "brasil",
    formato: str = "curto",
    influencer: Path | None = None,
) -> Path:
    """Monta o vídeo final em TELA CHEIA: clipe do X sobre o fundo borrado dele.

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

    `cartelas`: imagens dos momentos-chave (cartelas.py) — [{"imagem": str,
    "inicio_s": float, "dur_s": float}, ...], cada uma um PNG do TAMANHO EXATO
    do quadro. Entram deslizando, ocupando a tela toda no lugar do clipe, e
    saem pelo deslize de volta.

    `publico`: "brasil" ou "usa" — define o idioma do crédito de reprodução.

    `formato`: "curto" (Shorts 9:16, com legendas queimadas) ou "longo"
    (--long-take: 16:9, sem legendas) — muda a tolerância de tempo de cada
    clipe na tela.

    `influencer`: o MP4 quadrado que o Wan gerou (pipeline/influencer.py),
    fundo verde de chroma key. Recortada e encaixada no RODAPÉ, ela comenta o
    clipe que está passando — e, no Short, a voz do vídeo é a dela. SÓ NO
    FORMATO CURTO: no longo a narração é da ElevenLabs e não há ninguém em
    cena para sincronizar. None mantém a montagem como era antes de 2026-09-03.
    """
    _exigir_ffmpeg()
    if not FONTE_CREDITO.is_file():
        raise SystemExit(
            f"Fonte do crédito de reprodução ausente ({FONTE_CREDITO}) — sem "
            "ela o vídeo sairia sem creditar a conta de origem dos clipes; "
            "abortando."
        )

    duracao = duracao_audio(narracao) + RESPIRO_FINAL
    # A camada do carrossel é só das cartelas desde 2026-08-24, quando as
    # figuras do gpt-image-2 saíram (custo). Ordenadas pelo início para o log e
    # a pilha ficarem previsíveis.
    cartelas = sorted(cartelas or [], key=lambda c: float(c["inicio_s"]))

    # TELA CHEIA: a área útil de tudo é o quadro inteiro. Estes quatro nomes
    # sobrevivem à remoção dos cenários porque são o retângulo contra o qual
    # todo o resto (clipe, carrossel, crédito, etiqueta) é medido — só que
    # agora ele é o próprio quadro, sem moldura descontando nada.
    tela_x, tela_y, tela_l, tela_a = 0, 0, largura, altura

    sobreposicoes = _ordenar(sobreposicoes)
    estaticas = [s for s in sobreposicoes if not _e_video(s["caminho"])]
    if estaticas:
        raise SystemExit(
            "Imagem estática na montagem é proibida (o formato usa só clipes "
            "de vídeo do X): "
            + ", ".join(Path(s["caminho"]).name for s in estaticas)
        )
    janelas = _calcular_janelas(sobreposicoes, duracao)
    # O SHORT NÃO REPETE MAIS CLIPE (2026-08-28, pedido do usuário): as janelas
    # são encaixadas no material antes de virar comando de ffmpeg. O formato
    # longo segue como estava — lá cada pauta ocupa uma parte inteira do vídeo
    # e o loop é o que permite um clipe de 12s sustentar 30 segundos de análise.
    tetos_material: list[float] = []
    if formato != "longo":
        tetos_material = _tetos_do_material(sobreposicoes, duracao)
        janelas = _encaixar_no_material(
            sobreposicoes, janelas, duracao, tetos_material
        )
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
    # Janela curta demais não comporta os dois deslizes mais o tempo de leitura
    # entre eles: a imagem entraria e já sairia, sem ninguém ler o que ela
    # mostra. Quem chama já respeita DUR_MINIMA (2,2s nas cartelas, 2,6s nas
    # cartelas); isto é a guarda.
    pares_cart = [
        (c, (a, b))
        for c, (a, b) in zip(cartelas, janelas_cart)
        if b - a >= MIN_JANELA_CARROSSEL
    ]
    for c, (a, b) in zip(cartelas, janelas_cart):
        if b - a < MIN_JANELA_CARROSSEL:
            print(
                f"[edicao] aviso: janela de {b - a:.1f}s em {a:.1f}s é curta "
                f"demais para o deslize (mínimo {MIN_JANELA_CARROSSEL:.1f}s); "
                "imagem descartada."
            )
    cartelas = [c for c, _ in pares_cart]
    janelas_cart = [j for _, j in pares_cart]
    # Deslocamento do carrossel, de 0 (vídeo na tela) a 1 (imagem na tela). O
    # MESMO valor move o clipe para fora e a imagem para dentro — é isso que
    # mantém as duas coladas durante o deslize.
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
        # ENTRADA PELO MIOLO (2026-08-17): sem `-ss` o clipe começava sempre no
        # segundo zero, que num vídeo de veículo é a abertura com o apresentador
        # — o pedaço que o canal não usa ia ao ar mesmo no clipe aprovado.
        # `inicio_util_s` é o começo da maior sequência de frames sem busto
        # falante (midia_x._medir_frames); sem a medida, entra do zero como antes.
        inicio_util = s.get("inicio_util_s")
        seek = (
            ["-ss", f"{float(inicio_util):.2f}"]
            if inicio_util is not None and float(inicio_util) > 0
            else []
        )
        # LOOP SÓ NO FORMATO LONGO (2026-08-28). No Short ele foi removido a
        # pedido: repetir o clipe era o que deixava o mesmo pedaço de 4s passar
        # seis vezes na tela. Agora o material manda — o roteiro é escrito para
        # o tempo de clipe que a pauta tem (main.py), a auditoria confere se
        # sobrou material para a narração inteira, e `_encaixar_no_material`
        # reparte as janelas dentro do que existe.
        #
        # SOBRA UMA REDE, e ela precisa ser o loop mesmo: os overlays deste
        # grafo usam `eof_action=pass`, então clipe que ACABA no meio da janela
        # não congela o último quadro — ele some, e o que aparece embaixo é a
        # base PRETA. Tela preta é pior que repetição. Por isso o loop volta
        # CLIPE A CLIPE, e só naquele cuja janela o material não cobre — o caso
        # que `_encaixar_no_material` já denunciou no log por não ter conseguido
        # encaixar. No caminho normal nenhum clipe se repete, que é o pedido.
        estoura = (
            formato != "longo"
            and i < len(tetos_material)
            and dur_render > tetos_material[i] + CROSSFADE + 0.01
        )
        laco = ["-stream_loop", "-1"] if formato == "longo" or estoura else []
        if estoura:
            print(
                f"[edicao] aviso: {Path(s['caminho']).name} tem material para "
                f"{tetos_material[i]:.1f}s e a janela pede {dur_render:.1f}s; "
                "ele volta a repetir em loop para a tela não ficar preta."
            )
        comando += [*laco, *seek, "-t", f"{dur_render:.2f}",
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

        # Fundo: o próprio clipe cobrindo o QUADRO, borrado e levemente escuro.
        # É ele que mantém a tela sempre preenchida quando o clipe não tem a
        # proporção do quadro — o clipe 16:9 num Short 9:16, por exemplo, ganha
        # a faixa borrada em cima e embaixo em vez de barra preta.
        filtros.append(
            f"[in_bg{i}]scale={tela_l}:{tela_a}:force_original_aspect_ratio=increase,"
            f"crop={tela_l}:{tela_a},gblur=sigma={BLUR_SIGMA},"
            f"eq=brightness={ESCURECER},{dessat}"
            f"{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[bg{i}]"
        )

        # Frente: o clipe nítido COBRINDO o quadro inteiro (2026-08-31). Sem
        # zoom nem deslize — o clipe já tem movimento próprio; a transição
        # editorial é um crossfade curto e limpo.
        #
        # RECORTE QUE ACOMPANHA (2026-08-25): antes de escalar, o clipe
        # horizontal é RECORTADO numa janela que anda pelo quadro atrás de quem
        # está em cena (enquadramento.py). Só o `x` do crop varia — a largura é
        # fixa por clipe, senão o `w` que o overlay abaixo usa para centralizar
        # mudaria a cada quadro e o clipe tremeria.
        #
        # O `increase`+`crop` depois dele é a garantia de tela cheia, e vale
        # com plano ou sem: sem plano ele recorta pelo centro, com plano a
        # janela já está na proporção do quadro e ele só apara o pixel do
        # arredondamento par. Por isso o preenchimento não depende de OpenCV,
        # de detecção nem do ffprobe.
        dimensoes = dimensoes_video(s["caminho"])
        plano = (
            enquadramento.planejar(
                s["caminho"], float(inicio_util or 0.0), dur_render,
                *dimensoes, tela_l, tela_a,
            )
            if dimensoes
            else None
        )
        recorte = ""
        if plano:
            recorte = (
                f"crop={plano['crop_l']}:{plano['crop_a']}"
                f":x='{plano['expr_x']}':y=0,"
            )
            print(
                f"[edicao] Clipe {i + 1}: recorte {plano['crop_l']}x"
                f"{plano['crop_a']} de {dimensoes[0]}x{dimensoes[1]} "
                f"({tela_l / plano['crop_l']:.2f}x de ampliação), "
                f"{plano['movimentos']} movimento(s) de câmera."
            )
        elif dimensoes:
            print(
                f"[edicao] Clipe {i + 1}: sem plano de câmera, cobertura de "
                f"centro fixo de {dimensoes[0]}x{dimensoes[1]}."
            )
        filtros.append(
            f"[in_fg{i}]{recorte}"
            f"scale={tela_l}:{tela_a}:force_original_aspect_ratio=increase,"
            f"crop={tela_l}:{tela_a},"
            f"format=rgba,{dessat}{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[fg{i}]"
        )

        # Sobrepõe fundo e depois a frente, ambos ativos na janela (+ crossfade),
        # ancorados no canto do quadro e DESLOCADOS para a esquerda pelo
        # carrossel.
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

    # Imagens do carrossel (cartelas.py): cada uma é um PNG do
    # tamanho do quadro, que espera FORA dele, à direita, e entra empurrada pelo
    # mesmo deslocamento que tira o clipe. O que sobra fora do quadro é
    # recortado pela borda dele.
    prox_entrada = 2 + n
    for j, (c, (ini, fim)) in enumerate(zip(cartelas, janelas_cart)):
        idx_cart = prox_entrada
        prox_entrada += 1
        # A imagem existe SÓ NA JANELA em que aparece (2026-08-18). Antes cada
        # PNG era loopado pela duração inteira do vídeo: num longo de 150s a
        # 30fps são 4500 frames em rgba (8 MB cada, em 1080p) por cartela, e o
        # overlay consome todos, inclusive os milhares em que ela está
        # desabilitada. Medido em bancada, com 4 PNGs sobre 150s: 0,46 GB e 77s
        # do jeito antigo contra 0,32 GB e 38s assim — menos memória e metade do
        # tempo. O `tpad` recoloca a imagem no instante certo preenchendo o
        # começo com frames transparentes.
        dur_janela = max(fim - ini + T_ARRASTO * 2, 0.1)
        comando += [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{dur_janela:.2f}",
            "-i", str(c["imagem"]),
        ]
        atraso = max(ini - T_ARRASTO, 0.0)
        # Deslocamento só desta janela: duas cartelas nunca andam juntas.
        d_j = _expr_progresso([(ini, fim)], T_ARRASTO, T_ARRASTO)
        filtros.append(
            f"[{idx_cart}:v]format=rgba,setpts=PTS-STARTPTS,"
            f"tpad=start_duration={atraso:.2f}:start_mode=add"
            ":color=0x00000000[cart{j}]".replace("{j}", str(j))
        )
        filtros.append(
            f"[{corrente}][cart{j}]"
            f"overlay=x='{tela_x}+{tela_l}*(1-({d_j}))':y={tela_y}"
            f":eof_action=repeat"
            f":enable='between(t,{ini:.3f},{fim:.3f})'[vcart{j}]"
        )
        corrente = f"vcart{j}"

    # A INFLUENCER no rodapé (2026-09-03). Entra DEPOIS do clipe e do
    # carrossel e ANTES da legenda, do crédito e da etiqueta: ela é parte da
    # cena, e os três textos são camada de informação por cima da cena — se ela
    # passasse na frente, uma legenda comprida poderia sumir atrás do ombro
    # dela.
    #
    # O chroma key é MEDIDO NESTE vídeo, não constante (2026-09-04): desde que
    # o lipsync passou a ser feito no modo referência do Wan, o modelo repinta
    # o fundo a cada geração, e o verde muda de um Short para o outro (0x489850
    # num, 0x4E9656 no seguinte, medidos). `influencer.filtro_chroma` lê a
    # borda do arquivo e monta o filtro com a cor de agora. O lado do quadrado
    # é par de propósito: o libx264 em yuv420p rejeita dimensão ímpar, e um
    # arredondamento aqui derrubaria a montagem inteira no fim.
    #
    # `eof_action=repeat` segura o último quadro dela nos RESPIRO_FINAL (0,15s)
    # em que o vídeo dura mais que a fala — tempo curto demais para o congelado
    # aparecer, e melhor que ela sumir do quadro de um frame para o outro.
    if influencer is not None:
        if not Path(influencer).is_file():
            raise SystemExit(
                f"Vídeo da influencer ausente ({influencer}) — é ele que "
                "põe na tela quem narra o Short; abortando."
            )
        idx_inf = prox_entrada
        prox_entrada += 1
        comando += ["-t", f"{duracao:.2f}", "-i", str(influencer)]
        lado = max(2, round(tela_l * inf.LARGURA_FRAC / 2) * 2)
        filtros.append(
            f"[{idx_inf}:v]{inf.filtro_chroma(Path(influencer))},"
            f"scale={lado}:{lado},format=rgba,setpts=PTS-STARTPTS[inf]"
        )
        filtros.append(
            f"[{corrente}][inf]overlay="
            f"x={tela_x + round((tela_l - lado) / 2)}"
            f":y={tela_y + tela_a - lado}"
            f":eof_action=repeat[vinf]"
        )
        corrente = "vinf"
        print(
            f"[edicao] Influencer no rodapé: {lado}x{lado} "
            f"({inf.LARGURA_FRAC:.0%} da largura)."
        )

    if legendas is not None:
        fontes = RAIZ / "fonts"
        filtro_ass = f"ass='{_caminho_filtro(legendas)}'"
        if fontes.is_dir():
            filtro_ass += f":fontsdir='{_caminho_filtro(fontes)}'"
        filtros.append(f"[{corrente}]{filtro_ass}[vleg]")
        corrente = "vleg"

    # Crédito de reprodução no canto superior direito: linha 1 fixa e linha 2
    # com a conta do post de origem do clipe que está na tela — cada clipe liga
    # o seu crédito na sua janela, DESCONTADAS as janelas do carrossel:
    # enquanto a imagem do momento ocupa a tela, o clipe não está visível e o
    # crédito dele creditaria a coisa errada (a imagem traz o seu).
    rotulo_fixo, rotulo_conta = CREDITO_TEXTOS.get(publico, CREDITO_TEXTOS["brasil"])
    menor_quadro = min(tela_l, tela_a)
    fonte = round(menor_quadro * CREDITO_FONTE_FRAC)
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

    # Etiqueta de representação visual no rodapé esquerdo, só nas janelas dos
    # clipes marcados (também descontado o carrossel: com a imagem na tela não
    # há material de telejornal a sinalizar). A etiqueta acompanha o clipe de
    # ponta a ponta enquanto ele está visível, senão o material de emissora
    # aparece um trecho sem aviso nenhum — que é justamente o que a marcação
    # existe para impedir.
    texto_repr = REPR_TEXTOS.get(publico, REPR_TEXTOS["brasil"])
    fonte_repr = round(menor_quadro * REPR_FONTE_FRAC)
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

    print(
        f"[edicao] Montando vídeo final com ffmpeg "
        f"({len(pares)} clipe(s), {len(cartelas)} cartela(s), "
        f"{duracao:.0f}s em {largura}x{altura})..."
    )
    print(f"[edicao] ffmpeg: {versao_ffmpeg()}")
    marcar_memoria("antes do ffmpeg")
    # ACOMPANHA O PICO do ffmpeg (2026-08-18): o container morre com 8 GhB no
    # formato longo, e a métrica do Render mostra só o total subindo — sem
    # separar Python de ffmpeg não há como saber quem come a memória. A amostra
    # roda numa thread porque o `communicate` abaixo bloqueia até o fim.
    pico = {"mb": 0.0}

    def _acompanhar(processo: subprocess.Popen) -> None:
        while processo.poll() is None:
            try:
                with open(f"/proc/{processo.pid}/status", encoding="utf-8") as arq:
                    for linha in arq:
                        if linha.startswith("VmRSS:"):
                            pico["mb"] = max(pico["mb"], int(linha.split()[1]) / 1024)
                            break
            except OSError:
                return
            time.sleep(2)

    processo = subprocess.Popen(comando, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    vigia = threading.Thread(target=_acompanhar, args=(processo,), daemon=True)
    vigia.start()
    _, erro = processo.communicate()
    if pico["mb"]:
        print(f"[memoria] pico do ffmpeg: {pico['mb']:.0f} MB")
    marcar_memoria("depois do ffmpeg")
    if processo.returncode != 0:
        raise SystemExit(f"ffmpeg falhou:\n{(erro or '')[-2000:]}")

    print(f"[edicao] Vídeo final salvo em {destino}")
    return destino
