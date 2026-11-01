#!/usr/bin/env python3
"""
Compara a geracao do Soprano em PyTorch (transformers + SopranoDecoder original) com os ONNX exportados.
Usa decodificacao gulosa com repetition_penalty=1.2 (o padrao do Soprano e temperature=0 -> 0.001, ~guloso),
exatamente como o app Android faz. Grava WAVs para checagem com ASR.

  python validate_soprano_onnx.py --src <dir HF> --soprano-repo <clone> --onnx-dir <dir> --out <dir>
"""
import argparse
import os
import sys

import numpy as np
import onnxruntime as ort
import soundfile as sf
import torch

TEXTS = [
    "I think we should leave early tomorrow because the traffic near the airport is terrible on Mondays.",
    "Hello, how are you doing today?",
]


def prompt_of(text, tok):
    return tok(f"[STOP][TEXT]{text}[START]")["input_ids"]


def penalize(logits, seen, pen=1.2):
    l = logits.copy()
    idx = np.array(sorted(seen))
    v = l[idx]
    l[idx] = np.where(v < 0, v * pen, v / pen)
    return l


def gen_torch(model, ids, eos=3, max_new=512):
    seen = set(ids)
    x = torch.tensor([ids])
    hs = []
    past = None
    with torch.no_grad():
        for _ in range(max_new):
            out = model(input_ids=x, past_key_values=past, use_cache=True, output_hidden_states=True)
            past = out.past_key_values
            h = out.hidden_states[-1][0, -1].numpy()
            nxt = int(np.argmax(penalize(out.logits[0, -1].numpy(), seen)))
            if nxt == eos:
                break
            hs.append(h)
            seen.add(nxt)
            x = torch.tensor([[nxt]])
    return np.stack(hs)


def gen_onnx(sess, ids, eos=3, max_new=512, layers=17):
    seen = set(ids)
    past = {f"past_key_values.{i}.{kv}": np.zeros((1, 1, 0, 128), np.float32) for i in range(layers) for kv in ("key", "value")}
    cur = np.array([ids], np.int64)
    P = 0
    hs = []
    outs = [o.name for o in sess.get_outputs()]
    for _ in range(max_new):
        S = cur.shape[1]
        feed = {"input_ids": cur, "attention_mask": np.ones((1, P + S), np.int64),
                "position_ids": np.arange(P, P + S, dtype=np.int64)[None], **past}
        res = dict(zip(outs, sess.run(None, feed)))
        for i in range(layers):
            for kv in ("key", "value"):
                past[f"past_key_values.{i}.{kv}"] = res[f"present.{i}.{kv}"]
        P += S
        nxt = int(np.argmax(penalize(res["logits"][0, -1], seen)))
        if nxt == eos:
            break
        hs.append(res["last_hidden_state"][0, -1])
        seen.add(nxt)
        cur = np.array([[nxt]], np.int64)
    return np.stack(hs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--soprano-repo", required=True)
    ap.add_argument("--onnx-dir", required=True)
    ap.add_argument("--extra-onnx-dir", default=None)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.path.insert(0, a.soprano_repo)
    from soprano.vocos.decoder import SopranoDecoder
    from transformers import AutoModelForCausalLM, AutoTokenizer

    os.makedirs(a.out, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(a.src)
    model = AutoModelForCausalLM.from_pretrained(a.src, dtype=torch.float32).eval()
    dec = SopranoDecoder()
    dec.load_state_dict(torch.load(os.path.join(a.src, "decoder.pth"), map_location="cpu"))
    dec.eval()

    variants = {
        "mine_fp32": (os.path.join(a.onnx_dir, "soprano_backbone_kv_fp32.onnx"), os.path.join(a.onnx_dir, "soprano_decoder_fp32.onnx")),
        "mine_int8": (os.path.join(a.onnx_dir, "soprano_backbone_kv_int8.onnx"), os.path.join(a.onnx_dir, "soprano_decoder_fp32.onnx")),
    }
    if a.extra_onnx_dir:
        variants["kevin_int8"] = (os.path.join(a.extra_onnx_dir, "soprano_backbone_kv_int8.onnx"),
                                  os.path.join(a.extra_onnx_dir, "soprano_decoder_int8.onnx"))
    sessions = {k: (ort.InferenceSession(b), ort.InferenceSession(d)) for k, (b, d) in variants.items()}

    for ti, text in enumerate(TEXTS):
        ids = prompt_of(text, tok)
        print(f"\n[{ti}] {text}\n  tokens: {ids}")
        ref_h = gen_torch(model, ids)
        with torch.no_grad():
            ref_audio = dec(torch.from_numpy(ref_h.T[None]).float())[0].numpy()
        ref_audio = ref_audio[-(len(ref_h) * 2048 - 2048):]
        sf.write(os.path.join(a.out, f"t{ti}_torch.wav"), ref_audio, 32000)
        print(f"  torch: {len(ref_h)} tokens, {len(ref_audio)/32000:.2f}s")
        for name, (sb, sd) in sessions.items():
            h = gen_onnx(sb, ids)
            n = min(len(h), len(ref_h))
            hd = np.abs(h[:n] - ref_h[:n]).max()
            audio = sd.run(None, {"hidden_states": h.T[None].astype(np.float32)})[0][0]
            msg = f"  {name}: {len(h)} tokens, max|dh|={hd:.4f}"
            if len(h) == len(ref_h):
                # mesmo hidden de entrada -> compara o decoder isolado tambem
                a_same = sd.run(None, {"hidden_states": ref_h.T[None].astype(np.float32)})[0][0]
                msg += f", decoder max|da|={np.abs(a_same - ref_audio).max():.5f} (ref peak {np.abs(ref_audio).max():.3f})"
            print(msg)
            sf.write(os.path.join(a.out, f"t{ti}_{name}.wav"), audio, 32000)


if __name__ == "__main__":
    main()
