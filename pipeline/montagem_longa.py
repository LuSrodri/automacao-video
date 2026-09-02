"""Montagem do vídeo LONGO: as partes renderizadas separadas e coladas.

POR QUE ESTE MÓDULO EXISTE (2026-08-25, pedido do usuário). O formato longo era
montado como o Short: UM grafo de filtros do ffmpeg com todos os clipes, todas
as cartelas e todas as manchetes empilhados sobre uma linha do tempo de 135
segundos, cada camada ligada e desligada por `enable`. O usuário assistiu ao
resultado e foi direto: "ainda ficou uma merda... acho melhor você produzir as 4
partes separadas, e juntar no ffmpeg. Se não vai continuar uma bosta, e não vai
seguir o que eu quero."

Ele está certo, e o motivo é estrutural. Naquele grafo NADA garantia a
estrutura: o painel de manchete era uma janela de 4,2s que sumia, o planejador
de cortes distribuía clipes por citação e o mesmo clipe podia atravessar duas
pautas, e a única coisa que separava as partes era um `enable` que ninguém
conferia. Quando a regra é "cada pauta tem o SEU clipe e a SUA manchete, do
começo ao fim dela", a maneira de garantir a regra é a parte ser um ARQUIVO —
não um intervalo dentro de um arquivo.

    +--------------+ +----------+ +----------+ +----------+
    |   3 clipes   | | clipe 1  | | clipe 2  | | clipe 3  |
    | [AINDA NESTE | | [MANCHETE| | [MANCHETE| | [MANCHETE|
    |    VÍDEO]    | |    1]    | |    2]    | |    3]    |
    +--------------+ +----------+ +----------+ +----------+
         ~10s       ^           ^            ^         fade
                  pausa       pausa        pausa       out 3s
                  0,7s        0,7s         0,7s

Três passos:

1. CADA PARTE É UM MP4 SEM ÁUDIO. A abertura mostra os clipes das pautas em
   sequência (é o "ainda neste vídeo" em imagem: o espectador vê o que foi
   prometido) e cada pauta mostra um clipe só, o dela. O painel de texto entra
   deslizando e FICA — a parte inteira tem manchete na tela.
2. CONCATENAÇÃO por demuxer, sem recodificar: as partes saem do mesmo
   encoder, com o mesmo tamanho, fps e pix_fmt, então colar é copiar.
3. ÁUDIO POR CIMA do vídeo colado: a narração INTEIRA, de uma vez, mais o woosh
   em cada virada. Cortar o áudio em quatro e recolar traria o priming do AAC
   em cada emenda; assim a narração nunca é tocada e não há como as partes
   dessincronizarem da fala — a soma das durações delas é, por construção, a
   duração da narração mais a cauda do fade.

TELA CHEIA, como no Short: o fundo é o próprio clipe ampliado e borrado, e por
cima o clipe nítido no maior tamanho que cabe. Sem cenário, sem moldura, sem
música de fundo.

O QUE SAIU DO FORMATO LONGO junto com esta mudança:
  - as CARTELAS (foto do post tomando a tela pelo carrossel). Elas tomavam o
    quadro inteiro no meio de uma pauta, o que é exatamente "um vídeo que não é
    o vídeo daquela pauta". O carrossel continua vivo no Short (edicao.py).
  - o PLANEJADOR DE CORTES por citação. Quem decide o clipe de cada pauta agora
    é `cortes.atribuir_clipes`, que devolve UM clipe por pauta e nunca repete.
"""

import json
import subprocess
import threading
import time
from pathlib import Path

from .edicao import (
    BLUR_SIGMA,
    CREDITO_ENTRELINHA,
    CREDITO_FONTE_FRAC,
    CREDITO_MARGEM_FRAC,
    CREDITO_TARJA,
    CREDITO_TARJA_PAD_FRAC,
    CREDITO_TEXTOS,
    CREDITO_Y_FRAC,
    ESCURECER,
    FONTE_CREDITO,
    FPS,
    REPR_FONTE_FRAC,
    REPR_MARGEM_FRAC,
    REPR_SATURACAO,
    REPR_TEXTOS,
    REPR_Y_FRAC,
    WOOSH,
    WOOSH_VOL,
    _caminho_filtro,
    _texto_drawtext,
    duracao_audio,
    marcar_memoria,
    versao_ffmpeg,
)

# --- Tempos da troca de painel -----------------------------------------------
# A soma tem que caber DENTRO da pausa de silêncio da virada (0,7s por padrão):
# o espectador ouve o silêncio, vê a manchete velha sair e a nova entrar, e só
# então a narração recomeça. Se a pausa for menor, os dois tempos encolhem
# proporcionalmente (`_tempos_da_troca`) em vez de a animação vazar para cima
# da fala.
T_SAI = 0.30  # painel da parte anterior saindo pela esquerda
T_ENTRA = 0.40  # painel da parte nova entrando pela esquerda
# Na abertura não há painel saindo nem pausa: o índice entra sobre as primeiras
# palavras. O atraso curto existe para o primeiro quadro do vídeo ser o CLIPE,
# não um painel já posto — o painel entrando é o que chama o olho para ele.
ATRASO_ABERTURA = 0.25
T_ENTRA_ABERTURA = 0.45

# Crossfade entre os clipes da abertura. Só a abertura tem: nas pautas o
# clipe é um só, do começo ao fim.
CROSSFADE = 0.3

# Cauda do vídeo: o fecho continua na tela e o quadro escurece até o preto.
FADE_FINAL_S = 3.0

EXTENSOES_VIDEO = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def _suave(u: str) -> str:
    """smoothstep sobre uma expressão ffmpeg `u` já normalizada em [0,1].

    Aceleração e desaceleração nas pontas: um painel que parte e para na
    velocidade máxima lê como corte, não como deslize.
    """
    return f"({u})*({u})*(3-2*({u}))"


def _rampa_sobe(t0: float, dur: float) -> str:
    """Expressão ffmpeg: 0 antes de `t0`, sobe suave até 1, e FICA em 1.

    É a diferença central em relação à versão anterior desta camada: lá o
    progresso subia e voltava a zero, porque o painel saía da tela. Aqui ele
    sobe e não volta — o painel fica pelo resto da parte.
    """
    dur = max(dur, 0.001)
    return (
        f"(gte(t,{t0:.3f})*lt(t,{t0 + dur:.3f})*"
        f"{_suave(f'(t-{t0:.3f})/{dur:.3f}')}+gte(t,{t0 + dur:.3f}))"
    )


def _rampa_desce(t0: float, dur: float) -> str:
    """Expressão ffmpeg: 1 antes de `t0`, desce suave até 0, e fica em 0."""
    dur = max(dur, 0.001)
    return (
        f"(lt(t,{t0:.3f})+gte(t,{t0:.3f})*lt(t,{t0 + dur:.3f})*"
        f"(1-{_suave(f'(t-{t0:.3f})/{dur:.3f}')}))"
    )


def _tempos_da_troca(pausa: float) -> tuple[float, float]:
    """(saída, entrada) da troca de painel, encolhidos para caber na pausa."""
    total = T_SAI + T_ENTRA
    if pausa <= 0 or pausa >= total:
        return T_SAI, T_ENTRA
    escala = pausa / total
    return T_SAI * escala, T_ENTRA * escala


def _quadro(t: float) -> float:
    """Arredonda um instante para o quadro mais próximo.

    As partes são coladas por concatenação: se a duração de uma delas
    não for múltipla de 1/FPS, o ffmpeg arredonda por conta própria e a soma
    das partes deixa de bater com a narração — o vídeo inteiro desliza alguns
    quadros contra a fala, e o erro se acumula a cada emenda.
    """
    return round(t * FPS) / FPS


def _e_video(caminho: Path) -> bool:
    return Path(caminho).suffix.lower() in EXTENSOES_VIDEO


def _janelas_dos_clipes(n: int, dur: float) -> list[tuple[float, float]]:
    """Divide a parte em `n` janelas iguais e contíguas."""
    if n <= 1:
        return [(0.0, dur)]
    passo = dur / n
    return [(i * passo, (i + 1) * passo if i < n - 1 else dur) for i in range(n)]


def _filtros_do_clipe(
    i: int,
    entrada: int,
    clipe: dict,
    janela: tuple[float, float],
    largura: int,
    altura: int,
    ultimo: bool,
    corrente: str,
) -> tuple[list[str], str]:
    """Fundo borrado + clipe nítido centrado, na janela dele dentro da parte."""
    ini, fim = janela
    filtros: list[str] = []
    # Clipe marcado como representação visual perde a cor — convenção de
    # material ilustrativo. Fundo e frente juntos: dessaturar só a frente
    # deixaria um halo colorido em volta do clipe em P&B.
    dessat = (
        f"eq=saturation={REPR_SATURACAO}," if clipe.get("representacao") else ""
    )
    # O clipe é renderizado até `fim + CROSSFADE` e some nesse último trecho,
    # que é exatamente onde o próximo já está entrando: os dois se cruzam. Fazer
    # o fade acabar em `fim` daria fade-out seguido de fade-in, com um piscar de
    # preto no meio.
    dur_render = (fim - ini) + (0.0 if ultimo else CROSSFADE)
    fade_in = f"fade=t=in:st=0:d={CROSSFADE}:alpha=1," if i > 0 else ""
    fade_out = (
        f"fade=t=out:st={max(0.0, dur_render - CROSSFADE):.3f}:"
        f"d={CROSSFADE}:alpha=1,"
        if not ultimo
        else ""
    )
    filtros.append(f"[{entrada}:v]fps={FPS},format=rgba,split[in_bg{i}][in_fg{i}]")
    # Fundo: o próprio clipe cobrindo o QUADRO, borrado e levemente escuro. É
    # ele que mantém a tela preenchida quando o clipe não tem a proporção do
    # quadro — clipe vertical no 16:9 ganha a faixa borrada nos lados.
    filtros.append(
        f"[in_bg{i}]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
        f"crop={largura}:{altura},gblur=sigma={BLUR_SIGMA},"
        f"eq=brightness={ESCURECER},{dessat}{fade_in}{fade_out}"
        f"setpts=PTS-STARTPTS+{ini:.3f}/TB[bg{i}]"
    )
    # Frente: o clipe nítido no maior tamanho que CABE no quadro, centrado.
    filtros.append(
        f"[in_fg{i}]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
        f"format=rgba,{dessat}{fade_in}{fade_out}"
        f"setpts=PTS-STARTPTS+{ini:.3f}/TB[fg{i}]"
    )
    fim_render = ini + dur_render
    filtros.append(
        f"[{corrente}][bg{i}]overlay=x=0:y=0:eof_action=pass"
        f":enable='between(t,{ini:.3f},{fim_render:.3f})'[cb{i}]"
    )
    filtros.append(
        f"[cb{i}][fg{i}]overlay=x='({largura}-w)/2':y='({altura}-h)/2'"
        f":eof_action=pass"
        f":enable='between(t,{ini:.3f},{fim_render:.3f})'[cf{i}]"
    )
    return filtros, f"cf{i}"


def _filtros_dos_rotulos(
    clipes: list[dict],
    janelas: list[tuple[float, float]],
    largura: int,
    altura: int,
    publico: str,
    corrente: str,
) -> tuple[list[str], str]:
    """Crédito de reprodução (topo direito) e etiqueta de representação visual.

    O crédito é obrigação de atribuição: cada clipe leva a @ da conta do post de
    origem enquanto está na tela. A etiqueta de representação visual marca o
    material de telejornal que só o formato longo admite, e acompanha o clipe
    marcado de ponta a ponta.
    """
    filtros: list[str] = []
    rotulo_fixo, rotulo_conta = CREDITO_TEXTOS.get(publico, CREDITO_TEXTOS["brasil"])
    menor = min(largura, altura)
    fonte = round(menor * CREDITO_FONTE_FRAC)
    margem = round(largura * CREDITO_MARGEM_FRAC)
    pad = max(6, round(fonte * CREDITO_TARJA_PAD_FRAC))
    y1 = round(altura * CREDITO_Y_FRAC)
    y2 = y1 + round(fonte * CREDITO_ENTRELINHA) + 2 * pad
    base = (
        f"drawtext=fontfile='{_caminho_filtro(FONTE_CREDITO)}'"
        f":fontcolor=white:fontsize={fonte}"
        f":box=1:boxcolor=black@{CREDITO_TARJA}:boxborderw={pad}"
    )
    borda_direita = largura - margem

    fonte_repr = round(menor * REPR_FONTE_FRAC)
    margem_repr = round(largura * REPR_MARGEM_FRAC)
    pad_repr = max(6, round(fonte_repr * CREDITO_TARJA_PAD_FRAC))
    y_repr = round(altura * REPR_Y_FRAC)
    texto_repr = REPR_TEXTOS.get(publico, REPR_TEXTOS["brasil"])

    seq = 0
    for clipe, (ini, fim) in zip(clipes, janelas):
        enable = f":enable='between(t,{ini:.3f},{fim:.3f})'"
        linhas = [rotulo_fixo]
        conta = (clipe.get("conta") or "").strip()
        if conta:
            linhas.append(rotulo_conta.format(conta=conta))
        for texto, y in zip(linhas, (y1, y2)):
            filtros.append(
                f"[{corrente}]{base}:text='{_texto_drawtext(texto)}'"
                f":x={borda_direita}-text_w:y={y}{enable}[rot{seq}]"
            )
            corrente = f"rot{seq}"
            seq += 1
        if clipe.get("representacao"):
            filtros.append(
                f"[{corrente}]drawtext=fontfile='{_caminho_filtro(FONTE_CREDITO)}'"
                f":fontcolor=white:fontsize={fonte_repr}"
                f":box=1:boxcolor=black@{CREDITO_TARJA}:boxborderw={pad_repr}"
                f":text='{_texto_drawtext(texto_repr)}'"
                f":x={margem_repr}:y={y_repr}{enable}[rot{seq}]"
            )
            corrente = f"rot{seq}"
            seq += 1
    return filtros, corrente


def _montar_parte(
    parte: dict,
    clipes: list[dict],
    destino: Path,
    largura: int,
    altura: int,
    publico: str,
    cauda: float = 0.0,
) -> Path:
    """Renderiza UMA parte do vídeo (sem áudio) e devolve o arquivo.

    `cauda` são os segundos de fade final acrescentados à última parte: o
    quadro continua rodando e escurece até o preto depois da última palavra.
    """
    dur = _quadro(parte["fim_s"] - parte["inicio_s"] + cauda)
    janelas = _janelas_dos_clipes(len(clipes), dur)

    comando = [
        "ffmpeg", "-y", "-hide_banner",
        "-f", "lavfi",
        "-i", f"color=c=black:s={largura}x{altura}:r={FPS}:d={dur:.3f}",
    ]
    filtros = [f"[0:v]fps={FPS},format=rgba[base]"]
    corrente = "base"

    for i, (clipe, (ini, fim)) in enumerate(zip(clipes, janelas)):
        ultimo = i == len(clipes) - 1
        dur_render = fim - ini + (CROSSFADE if not ultimo else 0.0)
        # ENTRADA PELO MIOLO: sem `-ss` o clipe começa no segundo zero, que num
        # vídeo de veículo é a abertura com o apresentador. `inicio_util_s` é o
        # começo da maior sequência de frames sem busto falante
        # (midia_x._medir_frames); sem a medida, entra do zero.
        inicio_util = clipe.get("inicio_util_s")
        seek = (
            ["-ss", f"{float(inicio_util):.2f}"]
            if inicio_util is not None and float(inicio_util) > 0
            else []
        )
        # `-stream_loop -1` DEIXOU DE SER O MECANISMO E VIROU A REDE
        # (2026-09-01). Enquanto as pautas somavam 120-150s fixos, era ele que
        # cobria a diferença entre uma parte de 40s e o clipe de 15s dela — o
        # loop que o usuário mandou tirar. Agora cada capítulo é encomendado do
        # tamanho do clipe dele (`config.alvos_das_pautas`), então a repetição
        # não deveria ser alcançada. Fica aqui mesmo assim porque a alternativa
        # é pior: sem loop, o clipe que acaba antes do fim da parte vira TELA
        # PRETA (foi o que `eof_action=pass` fez no Short em 28/08). Rede que
        # não é usada não custa nada; tela preta custa o vídeo.
        comando += [
            "-stream_loop", "-1", *seek, "-t", f"{dur_render:.3f}",
            "-i", str(clipe["caminho"]),
        ]
        novos, corrente = _filtros_do_clipe(
            i, i + 1, clipe, (ini, fim), largura, altura, ultimo, corrente
        )
        filtros += novos

    novos, corrente = _filtros_dos_rotulos(
        clipes, janelas, largura, altura, publico, corrente
    )
    filtros += novos

    # --- Painéis --------------------------------------------------------------
    # A ordem importa: o painel que SAI é desenhado antes do que ENTRA, e as
    # duas janelas não se cruzam (uma acaba onde a outra começa), então nunca há
    # dois painéis na tela ao mesmo tempo.
    prox = len(clipes) + 1
    t_sai, t_entra = _tempos_da_troca(float(parte.get("pausa_s") or 0.0))
    saindo = parte.get("painel_saindo")
    if saindo:
        comando += [
            "-loop", "1", "-framerate", str(FPS), "-t", f"{t_sai:.3f}",
            "-i", str(saindo["imagem"]),
        ]
        x, larg = int(saindo["x"]), int(saindo["largura"])
        recuo = _rampa_desce(0.0, t_sai)
        filtros.append(f"[{prox}:v]format=rgba,setpts=PTS-STARTPTS[psai]")
        filtros.append(
            f"[{corrente}][psai]overlay="
            f"x='{x}-{x + larg}*(1-({recuo}))':y={int(saindo['y'])}"
            f":eof_action=repeat:enable='lt(t,{t_sai:.3f})'[vsai]"
        )
        corrente = "vsai"
        prox += 1
        entrada_em = t_sai
        duracao_entrada = t_entra
    else:
        entrada_em = ATRASO_ABERTURA
        duracao_entrada = T_ENTRA_ABERTURA

    painel = parte["painel"]
    comando += [
        "-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}",
        "-i", str(painel["imagem"]),
    ]
    x, larg = int(painel["x"]), int(painel["largura"])
    avanco = _rampa_sobe(entrada_em, duracao_entrada)
    filtros.append(f"[{prox}:v]format=rgba,setpts=PTS-STARTPTS[pent]")
    filtros.append(
        f"[{corrente}][pent]overlay="
        f"x='{x}-{x + larg}*(1-({avanco}))':y={int(painel['y'])}"
        f":eof_action=repeat:enable='gte(t,{entrada_em:.3f})'[vent]"
    )
    corrente = "vent"

    if cauda > 0:
        filtros.append(
            f"[{corrente}]fade=t=out:st={max(0.0, dur - cauda):.3f}:"
            f"d={cauda:.3f}:color=black[vfim]"
        )
        corrente = "vfim"

    comando += [
        "-filter_complex", ";".join(filtros),
        "-map", f"[{corrente}]",
        "-an",
        "-t", f"{dur:.3f}",
        "-r", str(FPS),
        "-c:v", "libx264",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        str(destino),
    ]

    print(
        f"[montagem] Parte {parte['indice'] + 1} ({parte['rotulo']}): "
        f"{dur:.1f}s, {len(clipes)} clipe(s)"
        + (f", cauda de {cauda:.0f}s" if cauda else "")
    )
    _rodar(comando, f"parte {parte['indice'] + 1} ({parte['rotulo']})")
    return destino


def _rodar(comando: list[str], rotulo: str) -> None:
    """Executa o ffmpeg acompanhando o pico de memória; aborta se falhar."""
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

    processo = subprocess.Popen(
        comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    vigia = threading.Thread(target=_acompanhar, args=(processo,), daemon=True)
    vigia.start()
    _, erro = processo.communicate()
    if pico["mb"]:
        print(f"[memoria] pico do ffmpeg ({rotulo}): {pico['mb']:.0f} MB")
    if processo.returncode != 0:
        raise SystemExit(f"ffmpeg falhou na {rotulo}:\n{(erro or '')[-2000:]}")


def _colar(partes: list[Path], destino: Path) -> Path:
    """Cola as partes sem recodificar (concat demuxer + `-c copy`).

    Copiar só funciona porque as quatro saíram do MESMO encoder com os mesmos
    parâmetros (tamanho, fps, pix_fmt, perfil): é a razão de `_montar_parte` não
    aceitar variação nenhuma nesses valores.
    """
    lista = destino.with_name("_partes.txt")
    lista.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in partes), encoding="utf-8"
    )
    _rodar(
        [
            "ffmpeg", "-y", "-hide_banner",
            "-f", "concat", "-safe", "0", "-i", str(lista),
            "-c", "copy", str(destino),
        ],
        "colagem das partes",
    )
    lista.unlink(missing_ok=True)
    return destino


def _somar_audio(
    video: Path, narracao: Path, viradas: list[float], total: float, destino: Path
) -> Path:
    """Põe a narração inteira sobre o vídeo colado, com o woosh nas viradas.

    A narração NUNCA é cortada: ela entra de uma vez sobre os quatro pedaços já
    colados. O vídeo é copiado (`-c:v copy`) — recodificar aqui seria a segunda
    passada de x264 sobre o mesmo material, sem nada a ganhar.
    """
    comando = ["ffmpeg", "-y", "-hide_banner", "-i", str(video), "-i", str(narracao)]
    filtros = [
        "[1:a]aformat=channel_layouts=stereo:sample_rates=44100,"
        f"apad,atrim=duration={total:.3f},asetpts=PTS-STARTPTS[narr]"
    ]
    mistura: list[str] = []
    if WOOSH.is_file() and viradas:
        comando += ["-i", str(WOOSH)]
        n = len(viradas)
        filtros.append("[2:a]asplit=%d%s" % (n, "".join(f"[ws{k}]" for k in range(n))))
        for k, t in enumerate(viradas):
            filtros.append(
                f"[ws{k}]adelay={max(0, round(t * 1000))}:all=1,"
                "aformat=channel_layouts=stereo:sample_rates=44100,"
                f"volume={WOOSH_VOL}[wd{k}]"
            )
            mistura.append(f"[wd{k}]")
    if mistura:
        filtros.append(
            f"[narr]{''.join(mistura)}amix=inputs={len(mistura) + 1}"
            ":normalize=0:duration=first,alimiter=limit=0.97[somado]"
        )
        corrente = "somado"
    else:
        corrente = "narr"
    # A cauda do vídeo é o fade para o preto; o áudio some junto, senão o vídeo
    # escurece com a narração ainda tocando.
    filtros.append(
        f"[{corrente}]afade=t=out:st={max(0.0, total - FADE_FINAL_S):.3f}"
        f":d={FADE_FINAL_S:.3f}[aout]"
    )
    comando += [
        "-filter_complex", ";".join(filtros),
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac",
        "-t", f"{total:.3f}",
        str(destino),
    ]
    _rodar(comando, "soma da narração")
    return destino


def conferir_paineis(video: Path, partes: list[dict]) -> None:
    """Confere no VÍDEO PRONTO se o painel de cada parte foi mesmo desenhado.

    Por que isto existe: em 2026-08-23 o pipeline montou seis manchetes, logou
    as seis, o ffmpeg saiu com código 0 — e nenhuma apareceu no vídeo
    publicado. Uma camada que falha em silêncio custa um vídeo inteiro e só é
    descoberta quando alguém assiste.

    O teste é direto: extrai um quadro do meio de cada parte e conta, DENTRO da
    caixa onde o painel deveria estar, os pixels próximos da cor de destaque da
    etiqueta. Nenhum pixel = o overlay não desenhou.

    Só diagnostica: nunca aborta, nunca altera o vídeo.
    """
    from PIL import Image

    from . import identidade as ident

    alvo = ident.DESTAQUES[0]
    quadro = video.with_name("_conferencia_painel.png")
    faltando: list[str] = []
    for parte in partes:
        painel = parte["painel"]
        instante = (float(parte["inicio_s"]) + float(parte["fim_s"])) / 2
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", f"{instante:.2f}",
                 "-i", str(video), "-vframes", "1", str(quadro)],
                check=True, capture_output=True,
            )
            with Image.open(quadro) as bruto:
                img = bruto.convert("RGB")
            x0, y0 = int(painel["x"]), int(painel["y"])
            x1 = min(img.width, x0 + int(painel["largura"]))
            y1 = min(img.height, y0 + int(painel["altura"]))
            recorte = img.crop((x0, y0, x1, y1))
            # Tolerância larga: o x264 desloca a cor, e o que importa é "tem um
            # bloco da cor da etiqueta aqui?", não a fidelidade dela.
            perto = sum(
                1
                for r, g, b in recorte.getdata()
                if abs(r - alvo[0]) < 60
                and abs(g - alvo[1]) < 60
                and abs(b - alvo[2]) < 60
            )
        except Exception as erro:  # noqa: BLE001 — conferência nunca derruba nada
            print(f"[montagem] aviso: não deu para conferir '{parte['rotulo']}' ({erro}).")
            continue
        finally:
            quadro.unlink(missing_ok=True)
        if perto < 50:
            faltando.append(f"{parte['rotulo']} (@{instante:.0f}s)")
        else:
            print(
                f"[montagem] Painel de '{parte['rotulo']}' conferido no vídeo "
                f"({perto} pixels da etiqueta em {instante:.0f}s)."
            )
    if faltando:
        print(
            "[montagem] ALERTA: o painel NÃO aparece no vídeo montado em: "
            + ", ".join(faltando)
            + ". O ffmpeg não acusou erro, então o overlay foi montado e não "
            "desenhou — vídeo publicado sem a divisão de pauta."
        )


def montar_video_longo(
    narracao: Path,
    partes: list[dict],
    clipes_por_parte: list[list[dict]],
    destino: Path,
    largura: int,
    altura: int,
    publico: str = "brasil",
) -> Path:
    """Monta o vídeo longo inteiro: renderiza as partes, cola e soma a narração.

    `partes` vem de `manchetes.planejar_partes`; `clipes_por_parte` traz os
    clipes de cada uma, na mesma ordem — todos na abertura (a prévia do que vem)
    e um em cada pauta. A regra que o usuário pediu — "para cada pauta é
    obrigatório o vídeo, e um mesmo vídeo não pode servir para duas pautas" —
    é garantida aqui: parte sem clipe aborta, e clipe repetido entre duas
    pautas aborta.
    """
    if len(partes) != len(clipes_por_parte):
        raise SystemExit(
            f"{len(partes)} parte(s) e {len(clipes_por_parte)} conjunto(s) de "
            "clipe(s): a montagem do formato longo não fecha."
        )
    if not FONTE_CREDITO.is_file():
        raise SystemExit(
            f"Fonte do crédito de reprodução ausente ({FONTE_CREDITO}) — sem "
            "ela o vídeo sairia sem creditar a conta de origem dos clipes; "
            "abortando."
        )

    usados: dict[str, str] = {}
    for parte, clipes in zip(partes, clipes_por_parte):
        if not clipes:
            raise SystemExit(
                f"A parte '{parte['rotulo']}' ficou sem clipe de vídeo, e cada "
                "pauta do formato longo é obrigada a ter o seu; abortando."
            )
        estaticas = [c for c in clipes if not _e_video(c["caminho"])]
        if estaticas:
            raise SystemExit(
                "Imagem estática na montagem é proibida (o formato usa só "
                "clipes de vídeo do X): "
                + ", ".join(Path(c["caminho"]).name for c in estaticas)
            )
        # A abertura é a PRÉVIA das pautas: ela mostra de propósito os mesmos
        # clipes, então só as pautas entram no controle de repetição.
        if parte["indice"] == 0:
            continue
        for clipe in clipes:
            chave = str(clipe["caminho"])
            if chave in usados:
                raise SystemExit(
                    f"O clipe {Path(chave).name} serviria a '{usados[chave]}' e "
                    f"a '{parte['rotulo']}' — cada pauta precisa do seu próprio "
                    "vídeo; abortando."
                )
            usados[chave] = parte["rotulo"]

    print(f"[montagem] ffmpeg: {versao_ffmpeg()}")
    marcar_memoria("antes das partes")
    pasta = destino.parent
    arquivos: list[Path] = []
    for i, (parte, clipes) in enumerate(zip(partes, clipes_por_parte)):
        arquivos.append(
            _montar_parte(
                parte,
                clipes,
                pasta / f"parte_{i + 1}.mp4",
                largura,
                altura,
                publico,
                cauda=FADE_FINAL_S if i == len(partes) - 1 else 0.0,
            )
        )
    marcar_memoria("depois das partes")

    colado = _colar(arquivos, pasta / "_partes_coladas.mp4")
    total = _quadro(duracao_audio(colado))
    viradas = [float(p["inicio_s"]) for p in partes[1:]]
    final = _somar_audio(colado, narracao, viradas, total, destino)
    marcar_memoria("depois da montagem")

    colado.unlink(missing_ok=True)
    for arquivo in arquivos:
        arquivo.unlink(missing_ok=True)

    (pasta / "montagem.json").write_text(
        json.dumps(
            {
                "duracao_s": total,
                "fade_final_s": FADE_FINAL_S,
                "partes": [
                    {
                        "rotulo": parte["rotulo"],
                        "titulo": parte["titulo"],
                        "inicio_s": parte["inicio_s"],
                        "fim_s": parte["fim_s"],
                        "clipes": [Path(c["caminho"]).name for c in clipes],
                    }
                    for parte, clipes in zip(partes, clipes_por_parte)
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[montagem] Vídeo final salvo em {destino} ({total:.1f}s)")
    conferir_paineis(final, partes)
    return final
