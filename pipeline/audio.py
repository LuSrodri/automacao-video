"""Narração do vídeo com o TTS da ElevenLabs (com timestamps por caractere).

DESDE 2026-09-03 ISTO É O CAMINHO DO FORMATO LONGO. O Short deixou de ser
narrado pela ElevenLabs: quem fala nele é a apresentadora que o Wan gera
(pipeline/apresentadora.py), e o áudio vem junto com a imagem dela. O que este
módulo ainda faz pelos dois formatos é o ALINHAMENTO — a ponte entre o texto do
roteiro e o instante em que cada caractere é falado, de que legendas, cortes e
cartelas dependem. Para o Short ele é reconstruído por transcrição
(`alinhar_por_transcricao`), já que não há mais `with-timestamps` de onde tirá-lo.
"""

import base64
import difflib
import json
import shutil
import subprocess
import unicodedata
from pathlib import Path

import requests
from openai import OpenAI

from .config import Config
from .edicao import duracao_audio

API_BASE = "https://api.elevenlabs.io/v1"

# Modelo de transcrição usado só para RECONSTRUIR o alinhamento do Short. É o
# mais barato que devolve timestamp por palavra (~US$ 0,006/min: um Short de
# 25s custa US$ 0,0025, três ordens de grandeza abaixo dos US$ 1,70 do vídeo
# dela). O texto certo já é conhecido — o roteiro —, então o que se pede à
# transcrição não é "o que ela disse", é "quando ela disse".
MODELO_TRANSCRICAO = "whisper-1"

# Quanto a duração final pode ficar longe do alvo sem que valha refazer o
# roteiro. 5% de um Short de 20s são 1 segundo — dentro da MATERIAL_MARGEM de
# 15% que a montagem guarda de folga de imagem, então um desvio deste tamanho
# não deixa a tela vazia nem desperdiça clipe de forma perceptível. Acima
# disso, refazer o texto sai mais barato que publicar um vídeo fora do desenho.
TOLERANCIA_ALVO = 0.05

# Velocidade da narração: quem manda é `cfg.velocidade` (VIDEO_VELOCIDADE para
# o Short, LONG_VELOCIDADE para o formato longo). O Short é ACELERADO — ritmo
# rápido é o que segura o feed — e o formato longo roda em 1.0, velocidade
# normal, porque análise em fala apressada não é acompanhável. Os timestamps do
# alinhamento são reescalados na mesma proporção, então cortes, legendas,
# infográficos e cartelas seguem sincronizados sem saber disso.


def _cadeia_atempo(fator: float) -> str:
    """Escreve `fator` como uma CADEIA de atempo, cada elo dentro de [0,5; 2].

    O atempo do ffmpeg só aceita um elo entre 0,5 e 2,0 e recusa o comando fora
    disso. Elos encadeados multiplicam, então qualquer valor é alcançável: 0,25
    é `atempo=0.5,atempo=0.5`.

    Existe para o ajuste ao alvo NÃO precisar de um teto artificial — o limite
    do atempo é técnico, e limite técnico não deve virar regra editorial. Na
    prática a cadeia quase sempre tem um elo só: o ajuste corrige o erro de
    ritmo do TTS (±11% medidos), não a metragem inteira.
    """
    elos: list[float] = []
    resto = fator
    while resto > 2.0:
        elos.append(2.0)
        resto /= 2.0
    while resto < 0.5:
        elos.append(0.5)
        resto /= 0.5
    elos.append(resto)
    return ",".join(f"atempo={e:.6f}" for e in elos)


def _acelerar_audio(audio: Path, fator: float) -> bool:
    """Muda a velocidade do MP3 em `fator` (atempo) no lugar.

    Acima de 1 acelera, abaixo de 1 desacelera. Devolve True se mexeu.
    """
    if abs(fator - 1.0) < 0.01:
        return False
    if shutil.which("ffmpeg") is None:
        print("[audio] ffmpeg ausente; velocidade da narração não foi mexida.")
        return False
    tmp = audio.with_name(audio.stem + "_acel" + audio.suffix)
    resultado = subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-i", str(audio),
            "-filter:a", _cadeia_atempo(fator),
            str(tmp),
        ],
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(f"[audio] Falha ao mudar a velocidade; usando original.\n"
              f"{resultado.stderr[-300:]}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(audio)
    return True


def _reescalar_alinhamento(alinhamento: dict, fator: float) -> dict:
    """Divide os timestamps por `fator` (áudio mais rápido = tempos menores)."""
    for chave in ("character_start_times_seconds", "character_end_times_seconds"):
        tempos = alinhamento.get(chave)
        if tempos:
            alinhamento[chave] = [
                None if t is None else t / fator for t in tempos
            ]
    return alinhamento


def ajustar_ao_alvo(
    audio: Path,
    alinhamento: dict,
    alvo_s: float,
    dur_s: float,
    base: float = 1.0,
    minimo: float | None = None,
    maximo: float | None = None,
) -> tuple[dict, float, bool]:
    """Muda a velocidade da narração para ela durar `alvo_s`.

    Devolve (alinhamento, duração nova, coube); o MP3 é alterado no lugar.
    `coube` é False quando a faixa de velocidade não deu para fechar a conta e
    a duração ficou fora de TOLERANCIA_ALVO — o sinal de que quem tem que
    mudar é o TEXTO, não o ritmo (main.py refaz o roteiro e narra de novo).

    `base` é a velocidade que a narração JÁ tem (cfg.velocidade, aplicada em
    `gerar_narracao`), e `minimo`/`maximo` são os limites da velocidade FINAL —
    não do fator aplicado aqui. A distinção importa: com base 1,05 e teto 1,15
    o fator desta função pode ir no máximo a 1,095, e é isso que o clamp
    calcula.

    POR QUE EXISTE (2026-08-30, pedido do usuário). O roteiro é encomendado em
    PALAVRAS e o TTS entrega o segundo que entrega — o ritmo variou ±11% nas
    narrações medidas nos crons. Até aqui esse erro era só ABSORVIDO:
    MATERIAL_MARGEM pedia 15% a mais de imagem do que a conta dizia precisar,
    para o Short não acabar em tela preta quando a narração estourasse. O erro
    continuava lá; o vídeo é que não quebrava por causa dele.

    Agora ele é CORRIGIDO. Depois de narrar e cortar os silêncios a duração
    deixa de ser chute e vira medida, e a velocidade é o parâmetro que faz a
    medida bater com o alvo. Vale para os DOIS LADOS: narração comprida
    acelera, narração curta desacelera. O vídeo passa a durar o que foi pedido,
    e não o que o TTS resolveu entregar.

    O ALVO É `cfg.video_duracao` — o tamanho para o qual o roteiro foi escrito
    —, NÃO a metragem do clipe. A diferença importa: esticar a narração até
    encher o clipe consumiria a MATERIAL_MARGEM inteira e desaceleraria todo
    Short em 15%, mudando o ritmo do canal por tabela. Corrigindo só até o
    alvo, o que se absorve é o ERRO do TTS e a margem segue sendo o que sempre
    foi — folga de imagem no fim.

    GANHOU TETO E PISO em 2026-09-01 (pedido do usuário: a narração do Short
    fica em 1,05x, "com limite mínimo de 1x e máximo de 1,15x"). Não tinha
    nenhum, e o argumento era que a correção nasce pequena — o que continua
    verdade, mas deixou de bastar: a velocidade virou um número que o usuário
    escolheu ouvir, e não um parâmetro livre para o pipeline fechar contas. Se
    a faixa não fecha a conta, o erro está no TAMANHO DO TEXTO, e é o texto que
    é refeito.

    Custa um segundo encode do MP3 (o primeiro é a aceleração do formato). A
    montagem reencoda o áudio depois, então não é este passo que decide a
    qualidade final.
    """
    if alvo_s <= 0 or dur_s <= 0:
        return alinhamento, dur_s, True

    fator = dur_s / alvo_s
    # O clamp é sobre a velocidade FINAL (base * fator), que é o que o
    # espectador ouve; o fator é só como se chega lá.
    if minimo is not None:
        fator = max(fator, minimo / base)
    if maximo is not None:
        fator = min(fator, maximo / base)

    if not _acelerar_audio(audio, fator):
        # Fator dentro do ruído (ou ffmpeg ausente): nada a fazer, e a duração
        # que já está aí é a resposta.
        coube = abs(dur_s - alvo_s) <= alvo_s * TOLERANCIA_ALVO
        return alinhamento, dur_s, coube

    alinhamento = _reescalar_alinhamento(alinhamento, fator)
    nova = duracao_audio(audio)
    verbo = "acelerada" if fator > 1 else "desacelerada"
    print(
        f"[audio] Narração {verbo} em {fator:.3f}x para bater o alvo "
        f"(velocidade final {base * fator:.3f}x): "
        f"{dur_s:.1f}s -> {nova:.1f}s (alvo {alvo_s:.1f}s)."
    )
    coube = abs(nova - alvo_s) <= alvo_s * TOLERANCIA_ALVO
    if not coube:
        print(
            f"[audio] A faixa de velocidade ({minimo}x a {maximo}x) não fechou "
            f"o alvo: sobraram {nova - alvo_s:+.1f}s. Quem tem que mudar é o "
            "texto."
        )
    return alinhamento, nova, coube


def gerar_narracao(cfg: Config, texto: str, destino: Path) -> tuple[Path, dict]:
    """Gera o MP3 da narração e devolve (caminho, alinhamento).

    O alinhamento traz characters / character_start_times_seconds /
    character_end_times_seconds, usados para sincronizar as legendas.
    """
    voz = cfg.voice_id_usa if cfg.publico == "usa" else cfg.voice_id
    print(f"[audio] Gerando narração com a voz {voz}...")
    resp = requests.post(
        f"{API_BASE}/text-to-speech/{voz}/with-timestamps",
        params={"output_format": "mp3_44100_128"},
        headers={
            "xi-api-key": cfg.elevenlabs_api_key,
            "Content-Type": "application/json",
        },
        json={
            "text": texto,
            "model_id": cfg.tts_model,
        },
        timeout=300,
    )
    if resp.status_code == 401:
        raise SystemExit("ELEVENLABS_API_KEY inválida (HTTP 401). Verifique o .env.")
    if resp.status_code == 422:
        raise SystemExit(f"ElevenLabs rejeitou a requisição (422): {resp.text[:300]}")
    resp.raise_for_status()

    dados = resp.json()
    destino.write_bytes(base64.b64decode(dados["audio_base64"]))

    alinhamento = dados.get("alignment") or {}
    if not alinhamento:
        print("[aviso] ElevenLabs não retornou alinhamento; legendas serão estimadas.")

    velocidade = getattr(cfg, "velocidade", 1.0) or 1.0
    if _acelerar_audio(destino, velocidade):
        alinhamento = _reescalar_alinhamento(alinhamento, velocidade)
        print(f"[audio] Narração acelerada em {velocidade}x.")
    else:
        print("[audio] Narração em velocidade normal (1.0x).")

    (destino.parent / "alinhamento.json").write_text(
        json.dumps(alinhamento, ensure_ascii=False), encoding="utf-8"
    )

    print(f"[audio] Narração salva em {destino}")
    return destino, alinhamento


# --- Alinhamento do Short, reconstruído por transcrição -----------------------
#
# O Short deixou de ter narração da ElevenLabs em 2026-09-03, e com ela foi
# embora o `with-timestamps` — a fonte de onde saíam os instantes de cada
# caractere. Quem fala agora é a apresentadora do Wan, e o áudio dela vem sem
# marcação nenhuma.
#
# O alinhamento NÃO É OPCIONAL: `legendas._palavras_com_tempos` sincroniza a
# legenda por ele, `cortes._tempo_do_char` decide em que segundo cada clipe
# entra, e `cartelas` posiciona a foto do post pelo mesmo caminho. Sem ele os
# três caem no plano B — repartir o texto proporcionalmente pela duração —, que
# é aceitável para um empurrão e péssimo como regime: fala tem pausa, e "metade
# dos caracteres" nunca cai na metade dos segundos.
#
# A reconstrução aproveita uma coisa que a ElevenLabs não dava e aqui existe: o
# TEXTO CERTO JÁ É CONHECIDO. Não se está transcrevendo para descobrir o que foi
# dito — o roteiro diz. Transcreve-se para descobrir QUANDO. Por isso a
# transcrição não vira legenda: ela é casada com o roteiro palavra a palavra, e
# o que ela empresta são só os carimbos de tempo. Palavra que o transcritor
# ouviu errado (ou não ouviu) não estraga o texto; ela apenas deixa de ancorar
# aquele trecho, que passa a ser interpolado entre os vizinhos.


def _sem_acento(palavra: str) -> str:
    decomposta = unicodedata.normalize("NFD", palavra.lower())
    return "".join(c for c in decomposta if unicodedata.category(c) != "Mn")


def _chave(palavra: str) -> str:
    """A palavra reduzida ao que dá para comparar entre roteiro e transcrição.

    Sem acento, sem caixa e sem pontuação: o transcritor devolve "código" e
    "Código," como coisas diferentes, e para casar as duas listas isso é ruído.
    """
    return "".join(c for c in _sem_acento(palavra) if c.isalnum())


def _palavras_faladas_com_posicao(texto: str) -> list[dict]:
    """As palavras FALADAS do texto, com onde cada uma começa e acaba nele.

    O conteúdo entre colchetes (audio tags) fica de fora: ele não é falado, e
    levá-lo para a comparação com a transcrição só produziria par errado. As
    posições são índices do texto CRU, porque é nele que `cortes.py` procura.
    """
    palavras: list[dict] = []
    profundidade, inicio = 0, None

    def fechar(fim: int) -> None:
        nonlocal inicio
        if inicio is None:
            return
        chave = _chave(texto[inicio:fim])
        if chave:
            palavras.append({"ini": inicio, "fim": fim, "chave": chave})
        inicio = None

    for i, c in enumerate(texto):
        if c == "[":
            profundidade += 1
            fechar(i)
            continue
        if c == "]":
            profundidade = max(0, profundidade - 1)
            fechar(i)
            continue
        if profundidade or c.isspace():
            fechar(i)
            continue
        if inicio is None:
            inicio = i
    fechar(len(texto))
    return palavras


def _transcrever(cfg: Config, audio: Path) -> list[dict]:
    """Palavras ouvidas no áudio, com início e fim em segundos."""
    cliente = OpenAI(api_key=cfg.openai_api_key)
    with open(audio, "rb") as arquivo:
        resposta = cliente.audio.transcriptions.create(
            model=MODELO_TRANSCRICAO,
            file=arquivo,
            response_format="verbose_json",
            timestamp_granularities=["word"],
        )
    ouvidas = []
    for palavra in getattr(resposta, "words", None) or []:
        chave = _chave(getattr(palavra, "word", ""))
        if chave:
            ouvidas.append(
                {
                    "chave": chave,
                    "ini": float(palavra.start),
                    "fim": float(palavra.end),
                }
            )
    return ouvidas


def _ancorar(roteiro: list[dict], ouvidas: list[dict]) -> int:
    """Carimba nas palavras do roteiro o tempo das que o transcritor casou.

    Compara as duas listas por `difflib`, que acha os trechos IGUAIS mesmo com
    palavra sobrando, faltando ou trocada no meio — que é exatamente o que uma
    transcrição produz. Devolve quantas palavras ficaram ancoradas.
    """
    casador = difflib.SequenceMatcher(
        a=[p["chave"] for p in roteiro],
        b=[p["chave"] for p in ouvidas],
        autojunk=False,
    )
    ancoradas = 0
    for a, b, tamanho in casador.get_matching_blocks():
        for k in range(tamanho):
            roteiro[a + k]["t_ini"] = ouvidas[b + k]["ini"]
            roteiro[a + k]["t_fim"] = ouvidas[b + k]["fim"]
            ancoradas += 1
    return ancoradas


def _ancoras_de_caractere(
    texto: str, roteiro: list[dict], duracao: float
) -> list[tuple[int, float]]:
    """Pares (índice de caractere, instante) crescentes, para interpolar entre eles.

    Só entram as palavras ANCORADAS. Tudo que ficou sem carimbo — palavra que o
    transcritor não ouviu, espaço, pontuação, audio tag — cai no meio de dois
    pares e recebe o tempo por interpolação linear, proporcional ao número de
    caracteres. As pontas são fixas: o caractere 0 começa em 0s e o fim do
    texto cai na duração do áudio.
    """
    ancoras = [(0, 0.0)]
    for palavra in roteiro:
        if "t_ini" not in palavra:
            continue
        ancoras.append((palavra["ini"], float(palavra["t_ini"])))
        ancoras.append((palavra["fim"], float(palavra["t_fim"])))
    ancoras.append((len(texto), float(duracao)))

    # Monotonia nos dois eixos. Um carimbo fora de ordem (o transcritor às
    # vezes devolve fim < início em palavra colada) faria a interpolação andar
    # para trás e a legenda piscar; o par que não avança é simplesmente
    # descartado.
    limpas: list[tuple[int, float]] = []
    for indice, tempo in ancoras:
        if limpas and (indice <= limpas[-1][0] or tempo < limpas[-1][1]):
            continue
        limpas.append((indice, tempo))
    return limpas


def alinhar_por_transcricao(cfg: Config, audio: Path, texto: str) -> dict:
    """Alinhamento por caractere do `texto` sobre `audio`, no formato do pipeline.

    Devolve o mesmo dicionário que a ElevenLabs devolvia — characters /
    character_start_times_seconds / character_end_times_seconds —, com
    `"".join(characters) == texto` exatamente, que é a conferência que
    `cortes._tempo_do_char` faz antes de confiar nele.
    """
    duracao = duracao_audio(audio)
    palavras = _palavras_faladas_com_posicao(texto)
    ouvidas: list[dict] = []
    if palavras:
        try:
            ouvidas = _transcrever(cfg, audio)
        except Exception as e:  # noqa: BLE001 — ver o comentário abaixo
            # AQUI NÃO SE ABORTA, e é a única exceção à diretriz de fail-fast
            # de 2026-07-15 neste caminho. A esta altura o vídeo da
            # apresentadora já foi gerado e PAGO (US$ 1,70), o áudio existe e o
            # Short sai inteiro sem isto — só com a legenda repartida por
            # proporção, como era o plano B de sempre. Jogar a execução fora
            # por causa do carimbo de tempo custaria mais do que o defeito.
            print(f"[audio] aviso: transcrição para o alinhamento falhou ({e}).")

    ancoradas = _ancorar(palavras, ouvidas) if ouvidas else 0
    ancoras = _ancoras_de_caractere(texto, palavras, duracao)
    print(
        f"[audio] Alinhamento reconstruído: {ancoradas}/{len(palavras)} "
        f"palavras ancoradas na transcrição ({duracao:.1f}s)."
    )

    inicios: list[float] = []
    tramo = 0
    for indice in range(len(texto) + 1):
        while tramo + 1 < len(ancoras) - 1 and ancoras[tramo + 1][0] <= indice:
            tramo += 1
        i0, t0 = ancoras[tramo]
        i1, t1 = ancoras[min(tramo + 1, len(ancoras) - 1)]
        fracao = (indice - i0) / (i1 - i0) if i1 > i0 else 0.0
        inicios.append(round(t0 + (t1 - t0) * min(max(fracao, 0.0), 1.0), 4))

    alinhamento = {
        "characters": list(texto),
        "character_start_times_seconds": inicios[:-1],
        "character_end_times_seconds": inicios[1:],
    }
    (audio.parent / "alinhamento.json").write_text(
        json.dumps(alinhamento, ensure_ascii=False), encoding="utf-8"
    )
    return alinhamento
