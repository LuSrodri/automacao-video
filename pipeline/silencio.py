"""Edição da linha do tempo da narração, mantendo o alinhamento sincronizado.

Duas operações opostas vivem aqui, e as duas têm o mesmo ponto crítico: mexer
no áudio SEM mexer no alinhamento da ElevenLabs deixaria todas as camadas
ancoradas em citação (cortes, cartelas, manchetes, capítulos) apontando
para o segundo errado.

1. `aparar_silencios` — a narração não pode ter trechos parados: o ffmpeg
   detecta os silêncios (`silencedetect`), o pipeline os corta (`aselect`) e
   remapeia os timestamps para o novo áudio.
2. `inserir_pausas` — o oposto, e só no formato longo (2026-08-24, pedido do
   usuário): abre uma PAUSA de silêncio em cada troca de pauta. É a "separação
   temporal" que o usuário pediu junto com a visual — sem ela, quem está
   ouvindo o vídeo sem olhar para a tela não percebe que a pauta virou, e o
   painel na tela vira enfeite. Dentro dessa pausa o painel de manchete velho
   sai e o novo entra: o espectador ouve o silêncio, lê o título novo e só
   então a narração recomeça.

   Desde 2026-08-25 essa pausa é MAIS que um respiro: ela é o ponto em que o
   vídeo é CORTADO em partes (montagem_longa.py). Por isso a função
   passou a devolver ONDE cada silêncio ficou no áudio novo — a montagem corta
   exatamente ali, em vez de recalcular a borda pela citação e errar por
   frações de segundo.

A ordem importa: as pausas são inseridas DEPOIS do corte de silêncios, senão o
`silencedetect` comeria exatamente o silêncio que acabou de ser criado.
"""

import re
import subprocess
from pathlib import Path

from .edicao import duracao_audio

RUIDO_DB = "-34dB"  # abaixo disso é considerado silêncio
SILENCIO_MIN = 0.35  # s; só detecta silêncios a partir desta duração
FOLGA = 0.12  # s; respiro que se mantém em cada silêncio (não corta tudo)
CORTE_MIN = 0.08  # s; ignora cortes minúsculos (não compensam re-encodar)
CORTE_TOTAL_MIN = 0.30  # s; se o total a cortar for menor que isso, não mexe


def _detectar_silencios(audio: Path) -> list[tuple[float, float]]:
    """Devolve [(inicio, fim), ...] dos silêncios detectados pelo ffmpeg."""
    resultado = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-i", str(audio),
            "-af", f"silencedetect=noise={RUIDO_DB}:d={SILENCIO_MIN}",
            "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
    )
    saida = resultado.stderr
    inicios = [float(m) for m in re.findall(r"silence_start:\s*([0-9.]+)", saida)]
    fins = [float(m) for m in re.findall(r"silence_end:\s*([0-9.]+)", saida)]
    return list(zip(inicios, fins))


def _regioes_a_cortar(
    silencios: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Para cada silêncio, calcula o trecho removido (preservando a FOLGA)."""
    regioes = []
    for ini, fim in silencios:
        corte_ini = ini + FOLGA
        if fim - corte_ini >= CORTE_MIN:
            regioes.append((corte_ini, fim))
    return regioes


def _faixas_mantidas(
    regioes: list[tuple[float, float]], duracao: float
) -> list[tuple[float, float]]:
    """Complemento das regiões cortadas dentro de [0, duracao]."""
    faixas, cursor = [], 0.0
    for ini, fim in regioes:
        if ini > cursor:
            faixas.append((cursor, ini))
        cursor = max(cursor, fim)
    if cursor < duracao:
        faixas.append((cursor, duracao))
    return faixas


def _remapear(t: float | None, regioes: list[tuple[float, float]]) -> float | None:
    """Converte um instante do áudio original para o áudio sem silêncios."""
    if t is None:
        return None
    deslocamento = 0.0
    for ini, fim in regioes:
        if t <= ini:
            break
        deslocamento += min(t, fim) - ini
    return max(0.0, t - deslocamento)


def _remapear_alinhamento(
    alinhamento: dict, regioes: list[tuple[float, float]]
) -> dict:
    inicios = alinhamento.get("character_start_times_seconds") or []
    fins = alinhamento.get("character_end_times_seconds") or []
    if not inicios or not fins:
        return alinhamento
    novo = dict(alinhamento)
    novo["character_start_times_seconds"] = [_remapear(t, regioes) for t in inicios]
    novo["character_end_times_seconds"] = [_remapear(t, regioes) for t in fins]
    return novo


def aparar_silencios(
    audio: Path, alinhamento: dict
) -> tuple[Path, dict, float]:
    """Corta os silêncios do áudio e remapeia o alinhamento.

    Devolve (caminho_do_audio, alinhamento, duracao). Se não houver silêncio
    relevante (ou faltar ffmpeg), devolve o áudio original sem mexer.
    """
    duracao = duracao_audio(audio)
    silencios = _detectar_silencios(audio)
    regioes = _regioes_a_cortar(silencios)
    total_corte = sum(fim - ini for ini, fim in regioes)

    if total_corte < CORTE_TOTAL_MIN:
        print("[silencio] Nenhum silêncio relevante para cortar.")
        return audio, alinhamento, duracao

    faixas = _faixas_mantidas(regioes, duracao)
    expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in faixas)
    destino = audio.with_name(audio.stem + "_sem_silencio" + audio.suffix)

    print(
        f"[silencio] Cortando {total_corte:.1f}s de silêncio "
        f"({len(regioes)} trecho(s))..."
    )
    resultado = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-i", str(audio),
            "-af", f"aselect='{expr}',asetpts=N/SR/TB",
            str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(f"[aviso] Falha ao cortar silêncios; usando áudio original.\n"
              f"{resultado.stderr[-500:]}")
        return audio, alinhamento, duracao

    novo_alinhamento = _remapear_alinhamento(alinhamento, regioes)
    nova_duracao = duracao_audio(destino)
    print(f"[silencio] Narração reduzida para {nova_duracao:.1f}s")
    return destino, novo_alinhamento, nova_duracao


# ---- Pausas nas trocas de pauta (formato longo) ------------------------------

# Formato comum imposto a todos os pedaços antes do `concat`: sem isso, um
# silêncio mono a 44,1 kHz contra uma narração estéreo faz o filtro recusar a
# junção.
FORMATO_CONCAT = "aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=stereo"
# Duas viradas coladas viram uma pausa só: abrir dois silêncios com menos disto
# entre eles deixaria a narração gaguejando em vez de respirando.
DISTANCIA_MINIMA = 3.0


def _deslocar_alinhamento(
    alinhamento: dict, instantes: list[float], dur: float
) -> dict:
    """Soma `dur` a cada instante do alinhamento por pausa aberta antes dele.

    O caractere que cai EXATAMENTE no ponto da pausa é o primeiro da frase de
    virada — ele fica DEPOIS do silêncio, e por isso a comparação é `<=`.
    """
    def novo(t: float | None) -> float | None:
        if t is None:
            return None
        return t + dur * sum(1 for i in instantes if i <= t)

    inicios = alinhamento.get("character_start_times_seconds") or []
    fins = alinhamento.get("character_end_times_seconds") or []
    if not inicios or not fins:
        return alinhamento
    deslocado = dict(alinhamento)
    deslocado["character_start_times_seconds"] = [novo(t) for t in inicios]
    deslocado["character_end_times_seconds"] = [novo(t) for t in fins]
    return deslocado


def _sanear_instantes(
    instantes: list[float], duracao: float
) -> list[float]:
    """Ordena, tira os que caem fora do áudio e junta os colados demais."""
    limpos: list[float] = []
    for t in sorted(float(i) for i in instantes):
        if not 0.5 < t < duracao - 0.5:
            continue
        if limpos and t - limpos[-1] < DISTANCIA_MINIMA:
            continue
        limpos.append(t)
    return limpos


def inserir_pausas(
    audio: Path, alinhamento: dict, instantes: list[float], dur: float
) -> tuple[Path, dict, list[tuple[float, float]]]:
    """Abre `dur` segundos de silêncio em cada instante; devolve tudo remapeado.

    `instantes` são os pontos da narração (no áudio ATUAL) em que uma pauta
    começa — na prática, o primeiro caractere da frase de virada. O silêncio
    entra IMEDIATAMENTE ANTES desse ponto, de modo que a frase de virada seja a
    primeira coisa que se ouve depois da pausa.

    Devolve (caminho, alinhamento, PAUSAS), onde `pausas` é [(início, fim), ...]
    de cada silêncio JÁ EM COORDENADAS DO ÁUDIO NOVO. Devolver isso — e não a
    duração, que quem chama recalcula — é o que deixa a montagem cortar o vídeo
    exatamente onde o silêncio está (2026-08-25): a k-ésima pausa começa no
    ponto k somado às k pausas que entraram antes dele. Recalcular a borda pela
    citação daria quase o mesmo número, e "quase" é o que faria o painel trocar
    meio segundo depois do silêncio.

    Falha aqui devolve pausas VAZIAS — e no formato longo isso derruba a
    montagem logo em seguida (manchetes.planejar_partes), porque as quatro
    partes do vídeo são cortadas nesses silêncios.
    """
    duracao = duracao_audio(audio)
    pontos = _sanear_instantes(instantes, duracao)
    if not pontos or dur <= 0:
        print("[silencio] Nenhuma pausa de pauta a inserir.")
        return audio, alinhamento, []

    # Segmentos da narração entre as pausas; o silêncio entra entre eles.
    bordas = [0.0, *pontos, duracao]
    segmentos = list(zip(bordas, bordas[1:]))
    n = len(segmentos)

    filtros = ["[0:a]asplit=%d%s" % (n, "".join(f"[b{i}]" for i in range(n)))]
    for i, (ini, fim) in enumerate(segmentos):
        filtros.append(
            f"[b{i}]atrim=start={ini:.3f}:end={fim:.3f},"
            f"asetpts=PTS-STARTPTS,{FORMATO_CONCAT}[p{i}]"
        )
    for k in range(len(pontos)):
        filtros.append(
            f"anullsrc=r=44100:cl=stereo,atrim=duration={dur:.3f},"
            f"asetpts=PTS-STARTPTS,{FORMATO_CONCAT}[q{k}]"
        )
    ordem = "".join(
        f"[p{i}]" + (f"[q{i}]" if i < len(pontos) else "") for i in range(n)
    )
    filtros.append(f"{ordem}concat=n={n + len(pontos)}:v=0:a=1[saida]")

    destino = audio.with_name(audio.stem + "_com_pausas" + audio.suffix)
    print(
        f"[silencio] Abrindo {len(pontos)} pausa(s) de {dur:.1f}s nas trocas "
        f"de pauta ({', '.join(f'{t:.1f}s' for t in pontos)})..."
    )
    resultado = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-i", str(audio),
            "-filter_complex", ";".join(filtros),
            "-map", "[saida]", str(destino),
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0 or not destino.is_file():
        print(
            "[aviso] Falha ao inserir as pausas de pauta; narração segue "
            f"corrida.\n{resultado.stderr[-500:]}"
        )
        return audio, alinhamento, []

    nova_duracao = duracao_audio(destino)
    # Onde cada silêncio ficou no áudio NOVO: o ponto k andou `dur` para a
    # frente uma vez por pausa aberta ANTES dele.
    pausas = [(t + k * dur, t + (k + 1) * dur) for k, t in enumerate(pontos)]
    print(
        f"[silencio] Narração com pausas: {nova_duracao:.1f}s "
        f"(silêncios em {', '.join(f'{a:.1f}s' for a, _ in pausas)})"
    )
    return destino, _deslocar_alinhamento(alinhamento, pontos, dur), pausas
