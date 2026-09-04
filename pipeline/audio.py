"""Narração do vídeo com o TTS da ElevenLabs (com timestamps por caractere).

VOLTOU A SER O CAMINHO DOS DOIS FORMATOS em 2026-09-04. Por um dia (09-03 a
09-04) o Short foi narrado por dentro do modelo de vídeo, e o alinhamento dele
teve de ser reconstruído transcrevendo o áudio — ~90 linhas de casamento entre
roteiro e transcrição que saíram junto com o desenho que as pedia. Agora a voz
é daqui de novo e o Wan só faz o LIPSYNC em cima dela
(pipeline/influencer.py), então o `with-timestamps` volta a entregar de graça a
ponte entre o texto do roteiro e o instante em que cada caractere é falado — de
que legendas, cortes e cartelas dependem.

A VOZ NÃO É A MESMA NOS DOIS FORMATOS. O Short é falado pela INFLUENCER que
aparece na tela, e a voz dela é própria (ELEVENLABS_VOICE_ID_INFLUENCER); o
formato longo segue com a voz de narração do canal. Ver `_voz`.
"""

import base64
import json
import shutil
import subprocess
from pathlib import Path

import requests

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


def _voz(cfg: Config) -> str:
    """A voz deste vídeo: a da INFLUENCER no Short, a do canal no longo.

    Quem narra o Short é a mulher que aparece na tela desde 2026-09-03, e desde
    2026-09-04 é a ElevenLabs que dá a voz dela — as duas coisas juntas fazem da
    voz uma característica DELA, não do canal. O formato longo é voz em off
    sobre imagem, e continua com a voz de narração que sempre teve.

    Cada formato tem o par PT/EN, porque o idioma é regra de canal.
    """
    if getattr(cfg, "formato", "curto") == "curto":
        return cfg.voice_id_influencer_usa if cfg.publico == "usa" else cfg.voice_id_influencer
    return cfg.voice_id_usa if cfg.publico == "usa" else cfg.voice_id


def gerar_narracao(cfg: Config, texto: str, destino: Path) -> tuple[Path, dict]:
    """Gera o MP3 da narração e devolve (caminho, alinhamento).

    O alinhamento traz characters / character_start_times_seconds /
    character_end_times_seconds, usados para sincronizar as legendas.
    """
    voz = _voz(cfg)
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
