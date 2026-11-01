#!/usr/bin/env python3
"""Gera fixtures para os testes JVM (app/src/test/resources) e o vocabulario do Soprano (assets).

  python make_test_fixtures.py --soprano-src <dir HF Soprano> --soprano-repo <clone soprano>
         --smart-turn <smart-turn-v3.2-cpu.onnx> --speech-wav <wav 16k> --out <app dir>
"""
import argparse, json, os, sys
import numpy as np
import onnxruntime as ort
import soundfile as sf
from transformers import WhisperFeatureExtractor
from tokenizers import Tokenizer

ap = argparse.ArgumentParser()
ap.add_argument("--soprano-src", required=True)
ap.add_argument("--soprano-repo", required=True)
ap.add_argument("--smart-turn", required=True)
ap.add_argument("--speech-wav", required=True)
ap.add_argument("--out", required=True)
a = ap.parse_args()
res = os.path.join(a.out, "src/test/resources")
assets = os.path.join(a.out, "src/main/assets")
os.makedirs(res, exist_ok=True); os.makedirs(assets, exist_ok=True)

# ---------------- Smart Turn: pipeline exatamente como pipecat-ai/smart-turn/inference.py
fe = WhisperFeatureExtractor(chunk_length=8)
sess = ort.InferenceSession(a.smart_turn)

def smart_turn(audio):
    audio = audio[-8 * 16000:]
    if len(audio) < 8 * 16000:
        audio = np.pad(audio, (8 * 16000 - len(audio), 0))
    f = fe(audio, sampling_rate=16000, return_tensors="np", padding="max_length", max_length=8 * 16000,
           truncation=True, do_normalize=True).input_features.astype(np.float32)
    return f, float(sess.run(None, {"input_features": f})[0][0, 0])

t = np.arange(int(2.7 * 16000)) / 16000
rng = np.random.default_rng(1)
synth = (0.3 * np.sin(2 * np.pi * (200 + 300 * t) * t) + 0.05 * rng.standard_normal(len(t))).astype(np.float32)
feat, p = smart_turn(synth)
synth.tofile(os.path.join(res, "st_audio.f32"))
feat[0].tofile(os.path.join(res, "st_features.f32"))
speech, sr = sf.read(a.speech_wav, dtype="float32")
assert sr == 16000
speech.tofile(os.path.join(res, "st_speech.f32"))
_, p_full = smart_turn(speech)
_, p_cut = smart_turn(speech[: int(len(speech) * 0.45)])
meta = {"synth_prob": p, "speech_full_prob": p_full, "speech_cut_prob": p_cut}
json.dump(meta, open(os.path.join(res, "st_meta.json"), "w"), indent=1)
print("smart turn", meta)

# ---------------- Soprano tokenizer + normalizacao
sys.path.insert(0, a.soprano_repo)
from soprano.utils.text_normalizer import clean_text
tok = Tokenizer.from_file(os.path.join(a.soprano_src, "tokenizer.json"))
cases = ["Hello, how are you doing today?", "I think we should leave early tomorrow.",
         "It costs $2.47 and I have 3 cats.", "The meeting is at 8:15 on Jan 5th.",
         "Dr. Smith said: \"That's great!\"", "We sold 1,234 units in 2024.",
         "Thank you very much... really!", "Hmm, okay -- let's go.", "Is it 100% sure?",
         "café naïve résumé", "I'm 25 years old and I live at 42 Wallaby Way."]
out = []
for c in cases:
    cl = clean_text(c)
    ids = tok.encode(f"[STOP][TEXT]{cl}[START]").ids
    out.append({"text": c, "clean": cl, "ids": ids})
json.dump(out, open(os.path.join(res, "soprano_tok.json"), "w"), indent=1, ensure_ascii=False)
for o in out: print(o["clean"])

# vocabulario compacto para o app: tokens de texto (id>=8004) + merges
d = json.load(open(os.path.join(a.soprano_src, "tokenizer.json")))
with open(os.path.join(assets, "soprano_tokenizer.txt"), "w") as f:
    f.write("# Soprano-1.1-80M tokenizer (BPE, extraido de tokenizer.json, Apache-2.0)\n")
    for k, i in sorted(d["model"]["vocab"].items(), key=lambda x: x[1]):
        if not (k.startswith("[") and k.endswith("]") and len(k) > 1):
            f.write(f"v\t{i}\t{json.dumps(k)}\n")
    for m in d["model"]["merges"]:
        a_, b_ = m if isinstance(m, list) else m.split(" ")
        f.write(f"m\t{json.dumps(a_)}\t{json.dumps(b_)}\n")
print("ok")
