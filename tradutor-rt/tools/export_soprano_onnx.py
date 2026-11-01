#!/usr/bin/env python3
"""
Exporta o Soprano-1.1-80M (ekwek/Soprano-1.1-80M, Apache-2.0) para ONNX:

  soprano_backbone_kv.onnx  - Qwen3 (17 camadas, 512 dim) com KV cache explicito.
      entradas : input_ids [1,S] int64, attention_mask [1,P+S] int64, position_ids [1,S] int64,
                 past_key_values.{i}.key / .value [1,1,P,128] float32  (i = 0..16)
      saidas   : logits [1,S,8192], present.{i}.key / .value [1,1,P+S,128],
                 last_hidden_state [1,S,512]   (depois do RMSNorm final, igual a hidden_states[-1] do HF)
  soprano_decoder.onnx      - Vocos (ConvNeXt + cabeca ISTFT), ISTFT feita com bases DFT
      entrada  : hidden_states [1,512,T]
      saida    : audio [1, 2048*T - 2048]  (32 kHz)

A interface de I/O e a mesma de KevinAHM/soprano-1.1-onnx, de modo que o app aceita as duas.

Uso:
  python export_soprano_onnx.py --src <dir com model.safetensors, decoder.pth, config.json> --out <dir> [--int8]
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.torch import load_file


# ----------------------------------------------------------------------------------------------
# Backbone (Qwen3) reescrito de forma "export-friendly"
# ----------------------------------------------------------------------------------------------
class RMSNorm(nn.Module):
    def __init__(self, dim, eps):
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, x):
        var = x.pow(2).mean(-1, keepdim=True)
        return self.weight * (x * torch.rsqrt(var + self.eps))


def rotate_half(x):
    x1, x2 = x.chunk(2, dim=-1)
    return torch.cat((-x2, x1), dim=-1)


class Layer(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        h, hd = cfg["hidden_size"], cfg["head_dim"]
        self.nh, self.nkv, self.hd = cfg["num_attention_heads"], cfg["num_key_value_heads"], hd
        eps = cfg["rms_norm_eps"]
        self.input_layernorm = RMSNorm(h, eps)
        self.post_attention_layernorm = RMSNorm(h, eps)
        self.q_proj = nn.Linear(h, self.nh * hd, bias=False)
        self.k_proj = nn.Linear(h, self.nkv * hd, bias=False)
        self.v_proj = nn.Linear(h, self.nkv * hd, bias=False)
        self.o_proj = nn.Linear(self.nh * hd, h, bias=False)
        self.q_norm = RMSNorm(hd, eps)
        self.k_norm = RMSNorm(hd, eps)
        self.gate_proj = nn.Linear(h, cfg["intermediate_size"], bias=False)
        self.up_proj = nn.Linear(h, cfg["intermediate_size"], bias=False)
        self.down_proj = nn.Linear(cfg["intermediate_size"], h, bias=False)

    def forward(self, x, cos, sin, mask, pk, pv):
        B, S, _ = x.shape
        r = x
        x = self.input_layernorm(x)
        q = self.q_norm(self.q_proj(x).view(B, S, self.nh, self.hd)).transpose(1, 2)
        k = self.k_norm(self.k_proj(x).view(B, S, self.nkv, self.hd)).transpose(1, 2)
        v = self.v_proj(x).view(B, S, self.nkv, self.hd).transpose(1, 2)
        q = q * cos + rotate_half(q) * sin
        k = k * cos + rotate_half(k) * sin
        k = torch.cat([pk, k], dim=2)
        v = torch.cat([pv, v], dim=2)
        rep = self.nh // self.nkv
        kk = k.repeat_interleave(rep, dim=1)
        vv = v.repeat_interleave(rep, dim=1)
        att = torch.matmul(q, kk.transpose(2, 3)) / math.sqrt(self.hd) + mask
        att = torch.softmax(att, dim=-1)
        o = torch.matmul(att, vv).transpose(1, 2).reshape(B, S, self.nh * self.hd)
        x = r + self.o_proj(o)
        r = x
        x = self.post_attention_layernorm(x)
        x = r + self.down_proj(F.silu(self.gate_proj(x)) * self.up_proj(x))
        return x, k, v


class Backbone(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.embed_tokens = nn.Embedding(cfg["vocab_size"], cfg["hidden_size"])
        self.layers = nn.ModuleList([Layer(cfg) for _ in range(cfg["num_hidden_layers"])])
        self.norm = RMSNorm(cfg["hidden_size"], cfg["rms_norm_eps"])
        self.lm_head = nn.Linear(cfg["hidden_size"], cfg["vocab_size"], bias=False)
        hd = cfg["head_dim"]
        inv = 1.0 / (cfg["rope_theta"] ** (torch.arange(0, hd, 2, dtype=torch.float32) / hd))
        self.register_buffer("inv_freq", inv, persistent=False)

    def forward(self, input_ids, attention_mask, position_ids, *past):
        x = self.embed_tokens(input_ids)
        S = input_ids.shape[1]
        T = attention_mask.shape[1]
        P = T - S
        freqs = position_ids.to(torch.float32)[:, :, None] * self.inv_freq[None, None, :]
        emb = torch.cat([freqs, freqs], dim=-1)
        cos = emb.cos()[:, None, :, :]
        sin = emb.sin()[:, None, :, :]
        # mascara causal + padding: query i (posicao absoluta P+i) ve chaves j <= P+i
        qi = torch.arange(S, device=x.device)[:, None] + P
        kj = torch.arange(T, device=x.device)[None, :]
        allowed = (kj <= qi)[None, None, :, :] & (attention_mask[:, None, None, :] > 0)
        mask = torch.where(allowed, torch.zeros((), dtype=x.dtype), torch.full((), -1e9, dtype=x.dtype))
        presents = []
        for i, layer in enumerate(self.layers):
            x, k, v = layer(x, cos, sin, mask, past[2 * i], past[2 * i + 1])
            presents += [k, v]
        h = self.norm(x)
        logits = self.lm_head(h)
        return (logits, *presents, h)


def load_backbone(src):
    cfg = json.load(open(os.path.join(src, "config.json")))
    m = Backbone(cfg)
    sd = load_file(os.path.join(src, "model.safetensors"))
    new = {}
    for k, v in sd.items():
        k2 = k.replace("model.", "", 1) if k.startswith("model.") else k
        k2 = k2.replace("self_attn.", "").replace("mlp.", "")
        new[k2] = v.float()
    missing, unexpected = m.load_state_dict(new, strict=False)
    assert not unexpected, unexpected
    assert all("inv_freq" in x for x in missing), missing
    return m.eval(), cfg


# ----------------------------------------------------------------------------------------------
# Decoder (Vocos) - reaproveita os modulos do repo soprano, troca a ISTFT por uma versao ONNX
# ----------------------------------------------------------------------------------------------
class OnnxISTFT(nn.Module):
    """ISTFT center=True (igual a torch.istft) com irfft como matmul e overlap-add via conv_transpose."""

    def __init__(self, n_fft=2048, hop=512):
        super().__init__()
        self.n_fft, self.hop = n_fft, hop
        nb = n_fft // 2 + 1
        n = torch.arange(n_fft, dtype=torch.float64)
        k = torch.arange(nb, dtype=torch.float64)
        ang = 2 * math.pi * k[:, None] * n[None, :] / n_fft  # [nb, n_fft]
        w = torch.ones(nb, dtype=torch.float64) * 2.0
        w[0] = 1.0
        w[-1] = 1.0
        window = torch.hann_window(n_fft, dtype=torch.float64)
        # irfft: x[n] = 1/N * sum_k w_k (Re cos - Im sin); multiplica pela janela de sintese
        self.register_buffer("cos_b", (w[:, None] * torch.cos(ang) / n_fft * window[None, :]).float())
        self.register_buffer("sin_b", (-w[:, None] * torch.sin(ang) / n_fft * window[None, :]).float())
        self.register_buffer("eye", torch.eye(n_fft, dtype=torch.float32)[:, None, :])  # [n_fft,1,n_fft]
        self.register_buffer("wsq", (window ** 2).float()[None, :, None])

    def forward(self, re, im):
        # re, im: [B, nb, T]; zera DC e Nyquist como no original
        re = re[:, 1:-1, :]
        im = im[:, 1:-1, :]
        frames = torch.einsum("bkt,kn->bnt", re, self.cos_b[1:-1]) + torch.einsum("bkt,kn->bnt", im, self.sin_b[1:-1])
        y = F.conv_transpose1d(frames, self.eye, stride=self.hop)  # [B,1,(T-1)*hop+n_fft]
        T = re.shape[2]
        env = F.conv_transpose1d(self.wsq.expand(1, -1, T), self.eye, stride=self.hop)
        pad = self.n_fft // 2
        L = y.shape[2]
        y = y[:, 0, pad:L - pad] / env[:, 0, pad:L - pad]
        return y


class DecoderOnnx(nn.Module):
    def __init__(self, dec):
        super().__init__()
        self.dec = dec
        self.istft = OnnxISTFT(dec.n_fft, dec.hop_length)

    def forward(self, hidden_states):
        T = hidden_states.shape[2]
        x = F.interpolate(hidden_states, size=self.dec.upscale * (T - 1) + 1, mode="linear", align_corners=True)
        x = self.dec.decoder(x)
        x = self.dec.head.out(x.transpose(1, 2)).transpose(1, 2)
        mag, p = x.chunk(2, dim=1)
        mag = torch.clip(torch.exp(mag), max=1e2)
        return self.istft(mag * torch.cos(p), mag * torch.sin(p))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--soprano-repo", default=os.path.join(os.path.dirname(__file__), "../../soprano"),
                    help="clone de github.com/ekwek1/soprano (para os modulos Vocos)")
    ap.add_argument("--int8", action="store_true", help="tambem gera versao int8 (quantizacao dinamica) do backbone")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    sys.path.insert(0, a.soprano_repo)
    from soprano.vocos.decoder import SopranoDecoder

    torch.manual_seed(0)
    bb, cfg = load_backbone(a.src)
    L, hd = cfg["num_hidden_layers"], cfg["head_dim"]
    S, P = 5, 3
    ids = torch.randint(0, 8000, (1, S))
    past = [torch.randn(1, 1, P, hd) for _ in range(2 * L)]
    am = torch.ones(1, P + S, dtype=torch.int64)
    pos = torch.arange(P, P + S)[None]
    in_names = ["input_ids", "attention_mask", "position_ids"]
    out_names = ["logits"]
    dyn = {"input_ids": {1: "S"}, "attention_mask": {1: "T"}, "position_ids": {1: "S"}, "logits": {1: "S"},
           "last_hidden_state": {1: "S"}}
    for i in range(L):
        for kv in ("key", "value"):
            in_names.append(f"past_key_values.{i}.{kv}")
            out_names.append(f"present.{i}.{kv}")
            dyn[f"past_key_values.{i}.{kv}"] = {2: "P"}
            dyn[f"present.{i}.{kv}"] = {2: "T"}
    out_names.append("last_hidden_state")
    bpath = os.path.join(a.out, "soprano_backbone_kv_fp32.onnx")
    torch.onnx.export(bb, (ids, am, pos, *past), bpath, input_names=in_names, output_names=out_names,
                      dynamic_axes=dyn, opset_version=17, dynamo=False)
    print("backbone ->", bpath)

    dec = SopranoDecoder()
    dec.load_state_dict(torch.load(os.path.join(a.src, "decoder.pth"), map_location="cpu"))
    dec.eval()
    dm = DecoderOnnx(dec).eval()
    dpath = os.path.join(a.out, "soprano_decoder_fp32.onnx")
    torch.onnx.export(dm, (torch.randn(1, 512, 12),), dpath, input_names=["hidden_states"], output_names=["audio"],
                      dynamic_axes={"hidden_states": {2: "T"}, "audio": {1: "N"}}, opset_version=17, dynamo=False)
    print("decoder  ->", dpath)

    if a.int8:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        qpath = os.path.join(a.out, "soprano_backbone_kv_int8.onnx")
        quantize_dynamic(bpath, qpath, weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul", "Gather"])
        print("int8     ->", qpath)


if __name__ == "__main__":
    main()
