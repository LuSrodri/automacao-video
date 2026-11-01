# Tradutor RT — tradução de voz em tempo real, 100% no aparelho (Android)

App Android em Kotlin/Jetpack Compose que escuta o microfone, detecta o fim de cada fala,
reconhece o idioma automaticamente, traduz e fala a tradução. Nada sai do celular depois que os
modelos são baixados.

```
Microfone 16 kHz ─► Silero VAD ─► Smart Turn v3.2 ─► Whisper (LID + ASR) ─► Hy-MT2-1.8B ─► Soprano / TTS do Android ─► alto-falante
   (AudioRecord)    (ONNX, 32 ms)  (ONNX, fim de turno)  (whisper.cpp, JNI)    (llama.cpp, JNI)  (ONNX Runtime)
```

## Como compilar

Requisitos: JDK 17+ (testado com 21), Android SDK com `platforms;android-36`, NDK `28.2.13676358`
e CMake `3.31.6` (o Gradle baixa o que faltar se a licença estiver aceita).

```bash
git submodule update --init --recursive    # llama.cpp e whisper.cpp (commits fixados)
cd tradutor-rt
echo "sdk.dir=$ANDROID_HOME" > local.properties
./gradlew assembleDebug                     # APK em app/build/outputs/apk/debug/app-debug.apk
./gradlew :app:testDebugUnitTest            # testes JVM (mel, tokenizer, máquina de turnos, prompt)
```

O APK é debug, assinado com a chave de debug do SDK, só `arm64-v8a`, minSdk 26, targetSdk 36.
A cópia pronta fica em `../tradutor-rt.apk` (raiz do repositório).

Mesmo no build debug, as bibliotecas nativas são compiladas em `Release` (`-O3`) — o `CMakeLists.txt`
força isso, porque o ggml com `-O0` fica dezenas de vezes mais lento. Os kernels usam
`armv8.2-a+dotprod+fp16` (qualquer celular com Cortex-A55/A75 ou mais novo).

## Estrutura

| Caminho | O quê |
|---|---|
| `app/` | App (Compose, serviço, pipeline, ONNX Runtime) |
| `app/.../pipeline/TranslationPipeline.kt` | Orquestração: uma thread por modelo, ligadas por canais |
| `app/.../audio/TurnDetector.kt` | Máquina de estados VAD + Smart Turn |
| `app/.../audio/WhisperFeatures.kt` | Port do pré-processamento do Smart Turn (mel do Whisper) |
| `app/.../tts/SopranoTts.kt`, `SopranoText.kt` | Soprano em ONNX: KV cache, tokenizer BPE e normalizador portados |
| `whisper-jni/` | JNI do whisper.cpp (ggml estático e com símbolos ocultos) |
| `llama-jni/` | JNI do llama.cpp (idem; o KV cache é reaproveitado entre traduções) |
| `third_party/` | Submódulos `llama.cpp` e `whisper.cpp` |
| `tools/export_soprano_onnx.py` | Exporta o Soprano para ONNX (backbone com KV cache + decoder Vocos com ISTFT) |
| `tools/validate_soprano_onnx.py` | Compara a exportação com o PyTorch e grava WAVs |
| `hosttest/`, `tools/build_host_jni.sh` | Teste de ponta a ponta no host (ver abaixo) |
| `tools/make_test_fixtures.py` | Gera as fixtures dos testes JVM a partir das implementações de referência em Python |

## Pipeline em detalhe

1. **VAD** — Silero VAD v5 (ONNX), blocos de 512 amostras + 64 de contexto. Abre um turno após
   ~96 ms de fala (com 320 ms de pré-roll).
2. **Fim de turno** — depois de ~190 ms de silêncio roda o `smart-turn-v3.2-cpu.onnx` sobre o turno
   atual (últimos 8 s). O pré-processamento segue exatamente o `inference.py` do
   `pipecat-ai/smart-turn`: zeros à esquerda até 8 s, normalização média 0/variância 1, STFT Hann 400/160
   com padding reflect, banco mel slaney de 80 filtros (a mesma matriz do `transformers`, empacotada como
   asset), `log10`, clamp `max-8`, `(x+4)/4`. O teste `WhisperFeaturesTest` compara com o
   `WhisperFeatureExtractor` do `transformers` (erro máx. < 2e-3). Probabilidade > limiar (0,5 por
   padrão, ajustável) fecha o turno. Se a pessoa volta a falar, o resultado pendente é descartado e na
   próxima pausa o Smart Turn roda de novo sobre o turno inteiro. Rede de segurança: 2,5 s de silêncio.
3. **ASR + idioma** — whisper.cpp, `ggml-base-q5_1` (padrão) ou `ggml-small-q5_1`. O app chama
   `whisper_lang_auto_detect` (o mesmo que `language="auto"` faz internamente) e:
   * modo **Conversa**: escolhe o mais provável entre os dois idiomas configurados;
   * modo **Ouvir**: o mais provável entre todos.
   Depois transcreve com esse idioma (custo igual ao de `auto`). O idioma e a probabilidade aparecem
   em cada mensagem. Enquanto a pessoa fala, a cada ~0,9 s sai uma **transcrição parcial**
   (`single_segment`, `audio_ctx` reduzido, limite de tokens proporcional à duração para evitar o
   loop de repetição); o segmento final é transcrito e traduzido quando o Smart Turn fecha o turno.
   Parciais nunca atrasam finais (a thread de ASR prioriza finais).
   **ASR rápido** (configuração, ligado por padrão): o turno final usa `audio_ctx` = duração + ~5 s em
   vez da janela de 30 s. No teste abaixo a transcrição saiu idêntica à de contexto cheio e o ASR caiu
   de ~1,3 s para ~0,5 s.
4. **Tradução** — Hy-MT2-1.8B via llama.cpp, carregado uma vez. Usa o prompt oficial do model card
   ("Translate the following text into {target_lang}. Note that you should only output the translated
   result without any additional explanation:\n\n{source_text}", versão chinesa quando o par envolve
   chinês) dentro do chat template do GGUF, sem system prompt, com os parâmetros recomendados
   (temp 0,7, top-p 0,6, top-k 20, repetição 1,05). O KV cache do prefixo comum é mantido entre
   chamadas. Threads limitadas aos núcleos grandes.
5. **Voz** — Soprano-1.1-80M quando o destino é inglês; TTS nativo do Android nos demais idiomas.
   A reprodução é por frase (a frase seguinte é sintetizada enquanto a anterior toca). Durante a
   reprodução o microfone é ignorado (half-duplex), para o app não traduzir a própria voz.

Cada modelo tem a sua thread (`vad`, `smart-turn`, `asr-whisper`, `mt-llama`, `tts`,
`audio-capture`, `audio-player`); a UI só observa um `StateFlow`. Isso é obrigatório, não só
organização: no teste de host, rodar o Soprano (ONNX Runtime) e em seguida o llama.cpp **na mesma
thread** fez o Hy-MT2 gerar lixo; em threads separadas, não (estado por thread deixado pelo ORT,
provavelmente flags de FPU/denormais). Um `ForegroundService` do tipo
`microphone` com `PARTIAL_WAKE_LOCK` mantém tudo funcionando com a tela apagada.

## Teste de ponta a ponta no host

Não havia aparelho nem KVM para um emulador neste ambiente, então o pipeline foi exercitado num Linux
x86-64 com **o mesmo código**: o módulo `:hosttest` compila os arquivos Kotlin do app que não dependem
do Android (VAD, Smart Turn + mel, `TurnDetector`, wrappers JNI, prompt, Soprano) e os mesmos
`whisper_jni.cpp`/`llama_jni.cpp` para x86-64 (`tools/build_host_jni.sh`, com um stub de
`android/log.h`), e alimenta um WAV bloco a bloco como se fosse o microfone.

```bash
./tools/build_host_jni.sh
./gradlew :hosttest:run --args="<dir com os modelos> conversa.wav pt en build/out.wav"
./gradlew :hosttest:run --args="<dir com os modelos> --mt"     # só traduções em sequência
```

Resultado com uma conversa sintética (PT gerado com Piper, pausa de 0,6 s no meio, depois EN), CPU x86
de 4 núcleos, Whisper base, Hy-MT2 Q4_K_M, Soprano int8:

| Turno | Fim de turno¹ | ASR | MT | TTS (1º áudio) | Total² |
|---|---|---|---|---|---|
| "Eu acho que a gente devia sair mais cedo amanhã." → "I think we should leave earlier tomorrow." | 358 ms (ST p=0,97) | 485 ms | 902 ms | 669 ms (Soprano) | 2,4 s |
| "Porque o trânsito … é terrível às segundas-feiras." → "Because the … traffic … is terrible on Mondays." | 361 ms (ST p=0,99) | 590 ms | 1084 ms | 782 ms (Soprano) | 2,8 s |
| "Sure, that sounds good to me." → "Claro, isso soa bom para mim." | 239 ms (ST p=0,78) | 392 ms | 805 ms | TTS do Android³ | — |
| "What time do you want to leave?" → "Que hora você quer sair?" | 242 ms (ST p=0,98) | 459 ms | 632 ms | TTS do Android³ | — |

¹ do último bloco com voz até a decisão: ~190 ms de silêncio + mel/ONNX do Smart Turn (45–150 ms).
² fim da fala → primeiro áudio da tradução pronto. ³ não existe no host.
VAD: ~0,4 ms por bloco de 32 ms. Parciais: ~0,2 s depois da primeira (a primeira do turno faz a LID
completa, ~1,1 s). Cache de prefixo do Hy-MT2: 23 tokens reaproveitados, prefill de ~320 ms → ~110 ms.
O áudio do Soprano gerado pelo código Kotlin foi transcrito de volta pelo Whisper small corretamente
(os erros de nome próprio vêm do ASR da voz sintética de entrada).

**Esses números são do host, não de celular.** Num aparelho de 6–8 GB com 4 núcleos grandes o
esperado é a mesma ordem de grandeza, mas não foi medido; a tela principal do app mostra as latências
reais de cada etapa.

## Modelos (baixados no primeiro uso, não vão no APK)

A tela inicial baixa do Hugging Face, com barra de progresso, retomada (`Range` sobre `.part`) e
verificação de tamanho + SHA-256 (o `oid` LFS). As revisões são fixadas por commit em
`ModelCatalog.kt`.

| Modelo | Repositório HF | Arquivo | Tamanho | Licença |
|---|---|---|---|---|
| Silero VAD v5 | `onnx-community/silero-vad` | `onnx/model.onnx` | 2,2 MB | MIT |
| Smart Turn v3.2 | `pipecat-ai/smart-turn-v3` | `smart-turn-v3.2-cpu.onnx` | 8,7 MB | BSD-2-Clause |
| Whisper base | `ggerganov/whisper.cpp` | `ggml-base-q5_1.bin` | 60 MB | MIT |
| Whisper small (opcional) | `ggerganov/whisper.cpp` | `ggml-small-q5_1.bin` | 190 MB | MIT |
| Hy-MT2-1.8B | `tencent/Hy-MT2-1.8B-GGUF` | `Hy-MT2-1.8B-Q4_K_M.gguf` | 1,13 GB | ver abaixo |
| Soprano-1.1-80M backbone | `KevinAHM/soprano-1.1-onnx` | `onnx/soprano_backbone_kv_int8.onnx` | 81 MB | Apache-2.0 |
| Soprano decoder (Vocos) | `KevinAHM/soprano-1.1-onnx` | `onnx/soprano_decoder_fp32.onnx(.data)` | 122 MB | Apache-2.0 |

Total da configuração padrão: ~1,4 GB.

### Por que Q4_K_M e não o 1,25 bit

O `tencent/Hy-MT2-1.8B-1.25Bit-GGUF` (e o equivalente do AngelSlim) declara no model card que depende
do kernel STQ da PR #22836 do llama.cpp. Testado no llama.cpp upstream de 01/11/2026 (`dde879bc`), o
arquivo usa o id de tipo 42, que no upstream é `Q2_0` com outro layout, e o carregamento falha com
`gguf_init_from_reader: failed to read tensor data`. Como pedido, o app usa o Q4_K_M oficial.

### Soprano em ONNX

O Soprano não tem runtime Android oficial e **só fala inglês** (o model card diz "Soprano is currently
English-only"). `tools/export_soprano_onnx.py` exporta:

* `soprano_backbone_kv_*.onnx` — o Qwen3 de 17 camadas reescrito de forma "export-friendly", com KV
  cache explícito (`past_key_values.{i}.key/value`) e as saídas `logits` + `last_hidden_state`;
* `soprano_decoder_*.onnx` — Vocos (ConvNeXt + cabeça ISTFT). A ISTFT (`torch.istft`, que não tem
  equivalente ONNX) foi reescrita como bases DFT + overlap-add com `ConvTranspose`.

Validação (`tools/validate_soprano_onnx.py`): a exportação fp32 reproduz o PyTorch exatamente
(diferença máxima de estado oculto 0,0000; áudio 1e-5) e os WAVs das versões fp32 e int8 foram
transcritos corretamente pelo Whisper small. Para o app baixar do Hugging Face sem eu precisar
hospedar arquivos, o catálogo aponta para `KevinAHM/soprano-1.1-onnx`, que tem **a mesma interface de
I/O** (verificada) — qualquer uma das duas exportações funciona no app.

## Licenças

* **Este app**: código próprio deste repositório.
* **Smart Turn v3** (pipecat-ai) — BSD-2-Clause.
* **Whisper** (OpenAI) e **whisper.cpp** / **llama.cpp** / **ggml** — MIT.
* **Hy-MT2** (Tencent) — os repositórios `tencent/Hy-MT2-*` no Hugging Face declaram `license: apache-2.0`
  no model card e trazem um `LICENSE.txt`; consulte esse arquivo para os termos exatos da Tencent
  antes de redistribuir o modelo.
* **Soprano-1.1-80M** (ekwek) e a exportação ONNX `KevinAHM/soprano-1.1-onnx` — Apache-2.0.
* **Silero VAD** — MIT.
* **ONNX Runtime** — MIT. **Jetpack Compose / AndroidX** — Apache-2.0.

Os pesos não são redistribuídos pelo APK; o app os baixa diretamente das fontes originais.
