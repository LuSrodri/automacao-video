// JNI para llama.cpp focado em traducao com Hy-MT2.
// - O modelo e o contexto sao criados UMA vez e reaproveitados entre as chamadas.
// - O KV cache e mantido entre traducoes: so os tokens depois do maior prefixo comum com o
//   prompt anterior sao recalculados (o cabecalho da instrucao de traducao fica em cache).
// - Uma instancia so pode ser usada por uma thread por vez.
#include <jni.h>
#include <android/log.h>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <string>
#include <vector>

#include "llama.h"

#define TAG "llama_jni"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

struct Engine {
    llama_model *model = nullptr;
    llama_context *ctx = nullptr;
    llama_sampler *smpl = nullptr;
    const llama_vocab *vocab = nullptr;
    std::vector<llama_token> cached;  // tokens atualmente no KV cache (seq 0)
    int n_batch = 512;
};

static void log_cb(ggml_log_level level, const char *text, void *) {
    if (level >= GGML_LOG_LEVEL_WARN) __android_log_print(ANDROID_LOG_WARN, TAG, "%s", text);
}

static jbyteArray to_bytes(JNIEnv *env, const std::string &s) {
    jbyteArray arr = env->NewByteArray((jsize) s.size());
    env->SetByteArrayRegion(arr, 0, (jsize) s.size(), reinterpret_cast<const jbyte *>(s.data()));
    return arr;
}

static std::string from_bytes(JNIEnv *env, jbyteArray arr) {
    jsize n = env->GetArrayLength(arr);
    std::string s(n, '\0');
    env->GetByteArrayRegion(arr, 0, n, reinterpret_cast<jbyte *>(&s[0]));
    return s;
}

static llama_sampler *make_sampler(const llama_vocab *vocab, float temp, int top_k, float top_p, float rep) {
    auto sp = llama_sampler_chain_default_params();
    sp.no_perf = true;
    llama_sampler *s = llama_sampler_chain_init(sp);
    llama_sampler_chain_add(s, llama_sampler_init_penalties(llama_vocab_n_tokens(vocab), 64, rep, 0.0f, 0.0f));
    if (temp <= 0.0f) {
        llama_sampler_chain_add(s, llama_sampler_init_greedy());
    } else {
        llama_sampler_chain_add(s, llama_sampler_init_top_k(top_k));
        llama_sampler_chain_add(s, llama_sampler_init_top_p(top_p, 1));
        llama_sampler_chain_add(s, llama_sampler_init_temp(temp));
        llama_sampler_chain_add(s, llama_sampler_init_dist(1234));
    }
    return s;
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_tradutorrt_llama_LlamaNative_nativeLoad(JNIEnv *env, jobject, jstring jpath, jint threads, jint nCtx) {
    llama_log_set(log_cb, nullptr);
    llama_backend_init();
    const char *path = env->GetStringUTFChars(jpath, nullptr);
    llama_model_params mp = llama_model_default_params();
    mp.n_gpu_layers = 0;
    llama_model *model = llama_model_load_from_file(path, mp);
    env->ReleaseStringUTFChars(jpath, path);
    if (!model) {
        LOGE("failed to load model");
        return 0;
    }
    llama_context_params cp = llama_context_default_params();
    cp.n_ctx = nCtx;
    cp.n_batch = 512;
    cp.n_ubatch = 512;
    cp.n_threads = threads;
    cp.n_threads_batch = threads;
    cp.no_perf = true;
    llama_context *ctx = llama_init_from_model(model, cp);
    if (!ctx) {
        LOGE("failed to create context");
        llama_model_free(model);
        return 0;
    }
    auto *e = new Engine();
    e->model = model;
    e->ctx = ctx;
    e->vocab = llama_model_get_vocab(model);
    e->n_batch = (int) cp.n_batch;
    // Parametros recomendados no model card do Hy-MT2 1.8B
    e->smpl = make_sampler(e->vocab, 0.7f, 20, 0.6f, 1.05f);
    LOGI("model loaded, n_ctx=%d threads=%d", nCtx, threads);
    return reinterpret_cast<jlong>(e);
}

extern "C" JNIEXPORT void JNICALL
Java_com_tradutorrt_llama_LlamaNative_nativeSetSampling(JNIEnv *, jobject, jlong h, jfloat temp, jint topK,
                                                        jfloat topP, jfloat rep) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (e->smpl) llama_sampler_free(e->smpl);
    e->smpl = make_sampler(e->vocab, temp, topK, topP, rep);
}

extern "C" JNIEXPORT void JNICALL
Java_com_tradutorrt_llama_LlamaNative_nativeFree(JNIEnv *, jobject, jlong h) {
    auto *e = reinterpret_cast<Engine *>(h);
    if (!e) return;
    if (e->smpl) llama_sampler_free(e->smpl);
    if (e->ctx) llama_free(e->ctx);
    if (e->model) llama_model_free(e->model);
    delete e;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_tradutorrt_llama_LlamaNative_nativeSystemInfo(JNIEnv *env, jobject) {
    return env->NewStringUTF(llama_print_system_info());
}

static std::vector<llama_token> tokenize(const llama_vocab *vocab, const std::string &text) {
    int n = -llama_tokenize(vocab, text.c_str(), (int32_t) text.size(), nullptr, 0, false, true);
    std::vector<llama_token> toks(n);
    llama_tokenize(vocab, text.c_str(), (int32_t) text.size(), toks.data(), n, false, true);
    return toks;
}

// Gera a continuacao do prompt (ja formatado com o chat template, tokens especiais inclusos).
// Retorna UTF-8 bruto; stats[0]=tokens do prompt reaproveitados, [1]=tokens do prompt avaliados,
// [2]=tokens gerados, [3]=ms prefill, [4]=ms geracao.
extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_tradutorrt_llama_LlamaNative_nativeGenerate(JNIEnv *env, jobject, jlong h, jbyteArray jprompt,
                                                     jint maxTokens, jlongArray jstats) {
    auto *e = reinterpret_cast<Engine *>(h);
    std::string prompt = from_bytes(env, jprompt);
    std::vector<llama_token> toks = tokenize(e->vocab, prompt);
    const int n_ctx = (int) llama_n_ctx(e->ctx);
    if ((int) toks.size() + maxTokens >= n_ctx) {
        maxTokens = std::max(16, n_ctx - (int) toks.size() - 1);
        if ((int) toks.size() >= n_ctx - 16) {
            LOGE("prompt too long: %d", (int) toks.size());
            return nullptr;
        }
    }

    // maior prefixo comum com o que esta no cache (deixa pelo menos 1 token para avaliar)
    size_t common = 0;
    static const bool no_reuse = getenv("LLAMA_JNI_NO_PREFIX_CACHE") != nullptr;  // depuracao
    while (!no_reuse && common < e->cached.size() && common < toks.size() - 1 && e->cached[common] == toks[common]) ++common;
    llama_memory_t mem = llama_get_memory(e->ctx);
    if (!llama_memory_seq_rm(mem, 0, (llama_pos) common, -1)) {
        llama_memory_clear(mem, true);
        common = 0;
    }
    e->cached.resize(common);

    auto t0 = std::chrono::steady_clock::now();
    for (size_t i = common; i < toks.size(); i += e->n_batch) {
        int n = (int) std::min<size_t>(e->n_batch, toks.size() - i);
        llama_batch b = llama_batch_get_one(toks.data() + i, n);
        if (llama_decode(e->ctx, b) != 0) {
            LOGE("decode prompt failed");
            llama_memory_clear(mem, true);
            e->cached.clear();
            return nullptr;
        }
        e->cached.insert(e->cached.end(), toks.begin() + i, toks.begin() + i + n);
    }
    auto t1 = std::chrono::steady_clock::now();

    llama_sampler_reset(e->smpl);
    std::string out;
    int generated = 0;
    char buf[256];
    for (; generated < maxTokens; ++generated) {
        llama_token tok = llama_sampler_sample(e->smpl, e->ctx, -1);
        if (llama_vocab_is_eog(e->vocab, tok)) break;
        int n = llama_token_to_piece(e->vocab, tok, buf, sizeof(buf), 0, false);
        if (n > 0) out.append(buf, n);
        llama_batch b = llama_batch_get_one(&tok, 1);
        if (llama_decode(e->ctx, b) != 0) {
            LOGE("decode failed");
            break;
        }
        e->cached.push_back(tok);
    }
    auto t2 = std::chrono::steady_clock::now();
    if (jstats && env->GetArrayLength(jstats) >= 5) {
        jlong st[5] = {(jlong) common, (jlong) (toks.size() - common), (jlong) generated,
                       (jlong) std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count(),
                       (jlong) std::chrono::duration_cast<std::chrono::milliseconds>(t2 - t1).count()};
        env->SetLongArrayRegion(jstats, 0, 5, st);
    }
    return to_bytes(env, out);
}
