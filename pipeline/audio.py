"""Narração do vídeo com o TTS da ElevenLabs (com timestamps por caractere)."""

import base64
import json
from pathlib import Path

import requests

from .config import Config

API_BASE = "https://api.elevenlabs.io/v1"


def gerar_narracao(cfg: Config, texto: str, destino: Path) -> tuple[Path, dict]:
    """Gera o MP3 da narração e devolve (caminho, alinhamento).

    O alinhamento traz characters / character_start_times_seconds /
    character_end_times_seconds, usados para sincronizar as legendas.
    """
    print(f"[audio] Gerando narração com a voz {cfg.voice_id}...")
    resp = requests.post(
        f"{API_BASE}/text-to-speech/{cfg.voice_id}/with-timestamps",
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
    (destino.parent / "alinhamento.json").write_text(
        json.dumps(alinhamento, ensure_ascii=False), encoding="utf-8"
    )

    print(f"[audio] Narração salva em {destino}")
    return destino, alinhamento
