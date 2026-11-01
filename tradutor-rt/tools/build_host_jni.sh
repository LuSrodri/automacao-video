#!/usr/bin/env bash
# Compila libllama_jni.so e libwhisper_jni.so para o host em build/hostjni (usado por :hosttest).
set -euo pipefail
cd "$(dirname "$0")/.."
cmake -S tools/hostjni -B build/hostjni -DCMAKE_BUILD_TYPE=Release > /dev/null
cmake --build build/hostjni -j"$(nproc)"
ls -la build/hostjni/*.so
