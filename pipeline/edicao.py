"""Montagem final do vídeo com ffmpeg.

O vídeo é montado SOMENTE com clipes de vídeo dos posts do X (imagem estática
é proibida — a montagem aborta se receber uma). O fundo de cada momento é o
PRÓPRIO clipe daquele trecho, ampliado para cobrir a tela toda e BORRADO; por
cima entra o clipe nítido em largura total, centrado. Os clipes cobrem 100% da
narração — nunca há um instante sem imagem na tela — com um crossfade curto e
limpo entre si (corte editorial, sem deslizes). A narração TTS (sem silêncios)
é a trilha, e o crédito de reprodução ("Reprodução Imagem: X" + "Conta
@usuario" do post de origem) fica no canto superior direito enquanto o clipe
daquela conta está na tela.
"""

import subprocess
import shutil
from pathlib import Path

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

# Trilha musical de fundo: assets/trilha.mp3 entra em loop sob a narração em
# volume baixo — alavanca de retenção clássica de Shorts. A faixa padrão é
# "Tension Documentary" (AtlasAudio, Pixabay — licença Pixabay: uso comercial
# livre, sem atribuição), normalizada para -16 LUFS; qualquer .mp3 no mesmo
# caminho a substitui. Sem o arquivo, o vídeo sai só com narração + wooshes.
TRILHA = RAIZ / "assets" / "trilha.mp3"
TRILHA_VOL = 0.12  # ~-18 dB sob a narração (a trilha já vem normalizada)

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


def montar_video(
    narracao: Path,
    sobreposicoes: list[dict],
    destino: Path,
    largura: int,
    altura: int,
    legendas: Path | None = None,
    graficos: list[dict] | None = None,
    publico: str = "brasil",
    formato: str = "curto",
) -> Path:
    """Monta o vídeo final: clipes do X com fundo borrado do próprio clipe.

    `sobreposicoes`: [{"caminho": Path, "inicio_frac": float|None,
    "fim_frac": float|None, "conta": str}, ...] — frações (0 a 1) da narração
    em que o clipe entra; None usa distribuição uniforme. SOMENTE clipes de
    vídeo (imagem estática aborta). Os clipes cobrem 100% da narração (sem
    instante vazio) e fazem crossfade entre si; "conta" (@usuario do post de
    origem) alimenta o crédito de reprodução no canto superior direito.

    `graficos`: infográficos animados (grafico.py) — [{"pattern": str,
    "inicio_s": float, "dur_s": float}, ...], sequências de PNGs RGBA
    sobrepostas ao vídeo. Enquanto um infográfico está na tela, o crédito
    some: o infográfico ocupa o terço superior.

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
    graficos = graficos or []

    # Janelas dos infográficos: o crédito desliga nelas (enable do ffmpeg).
    janelas_gfx = [
        (g["inicio_s"], min(g["inicio_s"] + g["dur_s"], duracao)) for g in graficos
    ]
    oculta_gfx = "".join(
        f"*(1-between(t,{a:.2f},{b:.2f}))" for a, b in janelas_gfx
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

        # Fundo: o próprio clipe cobrindo a tela toda, borrado e levemente escuro.
        filtros.append(
            f"[in_bg{i}]scale={largura}:{altura}:force_original_aspect_ratio=increase,"
            f"crop={largura}:{altura},gblur=sigma={BLUR_SIGMA},"
            f"eq=brightness={ESCURECER},"
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
            f"[in_fg{i}]scale={largura}:{altura}:force_original_aspect_ratio=decrease,"
            f"format=rgba,{fade_in}{fade_out}"
            f"setpts=PTS-STARTPTS+{ini:.2f}/TB[fg{i}]"
        )

        # Sobrepõe fundo e depois a frente, ambos ativos na janela (+ crossfade).
        filtros.append(
            f"[{corrente}][bg{i}]overlay=0:0:eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[b{i}]"
        )
        filtros.append(
            f"[b{i}][fg{i}]overlay=(W-w)/2:(H-h)/2:eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim_render:.2f})'[f{i}]"
        )
        corrente = f"f{i}"

    if legendas is not None:
        fontes = RAIZ / "fonts"
        filtro_ass = f"ass='{_caminho_filtro(legendas)}'"
        if fontes.is_dir():
            filtro_ass += f":fontsdir='{_caminho_filtro(fontes)}'"
        filtros.append(f"[{corrente}]{filtro_ass}[vleg]")
        corrente = "vleg"

    # Crédito de reprodução no canto superior direito (sobre as legendas):
    # linha 1 fixa e linha 2 com a conta do post de origem do clipe que está
    # na tela — cada clipe liga o seu crédito na sua janela. `prox_entrada`
    # numera as entradas extras do ffmpeg daqui em diante (infográficos,
    # woosh, trilha).
    prox_entrada = 2 + n
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
        enable = f":enable='between(t,{ini:.2f},{fim:.2f}){oculta_gfx}'"
        for texto, y in zip(linhas, (y1, y2)):
            filtros.append(
                f"[{corrente}]{base_credito}"
                f":text='{_texto_drawtext(texto)}'"
                f":x=w-text_w-{margem}:y={y}"
                f"{enable}[vcred{seq}]"
            )
            corrente = f"vcred{seq}"
            seq += 1

    # Infográficos animados (sequências de PNG RGBA do grafico.py) por cima de
    # tudo — o crédito já foi desligado nas janelas deles.
    for j, g in enumerate(graficos):
        idx_gfx = prox_entrada
        prox_entrada += 1
        ini, fim = janelas_gfx[j]
        comando += [
            "-framerate", str(FPS), "-start_number", "1", "-i", g["pattern"],
        ]
        filtros.append(
            f"[{idx_gfx}:v]format=rgba,setpts=PTS-STARTPTS+{ini:.2f}/TB[gfx{j}]"
        )
        filtros.append(
            f"[{corrente}][gfx{j}]overlay=0:0:eof_action=pass"
            f":enable='between(t,{ini:.2f},{fim:.2f})'[vgfx{j}]"
        )
        corrente = f"vgfx{j}"

    # Áudio: narração + woosh em cada transição de clipe + trilha de fundo
    # opcional. O primeiro clipe não tem transição de entrada.
    mapa_audio = "1:a"
    transicoes = [ini for _, (ini, _) in pares[1:]]
    usar_woosh = WOOSH.is_file() and bool(transicoes)
    usar_trilha = TRILHA.is_file()
    entradas_mix: list[str] = []
    if usar_woosh or usar_trilha:
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
    if usar_trilha:
        idx_trilha = prox_entrada
        prox_entrada += 1
        comando += ["-stream_loop", "-1", "-t", f"{duracao:.2f}", "-i", str(TRILHA)]
        filtros.append(
            f"[{idx_trilha}:a]aformat=channel_layouts=stereo:sample_rates=44100,"
            f"volume={TRILHA_VOL},"
            f"afade=t=out:st={max(0.0, duracao - 0.5):.2f}:d=0.5[trilha]"
        )
        entradas_mix.append("[trilha]")
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
