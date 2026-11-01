// JNI minimo para whisper.cpp: carregar modelo, detectar idioma e transcrever.
// Cada contexto deve ser usado por uma unica thread por vez (o app usa um dispatcher dedicado).
#include <jni.h>
#include <android/log.h>

#include <string>
#include <vector>

#include "whisper.h"

#define TAG "whisper_jni"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO, TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, TAG, __VA_ARGS__)

static jbyteArray to_bytes(JNIEnv *env, const std::string &s) {
    jbyteArray arr = env->NewByteArray((jsize) s.size());
    env->SetByteArrayRegion(arr, 0, (jsize) s.size(), reinterpret_cast<const jbyte *>(s.data()));
    return arr;
}

static void log_cb(ggml_log_level level, const char *text, void *) {
    if (level >= GGML_LOG_LEVEL_WARN) __android_log_print(ANDROID_LOG_WARN, TAG, "%s", text);
}

extern "C" JNIEXPORT jlong JNICALL
Java_com_tradutorrt_whisper_WhisperNative_nativeInit(JNIEnv *env, jobject, jstring jpath) {
    whisper_log_set(log_cb, nullptr);
    const char *path = env->GetStringUTFChars(jpath, nullptr);
    whisper_context_params cp = whisper_context_default_params();
    cp.use_gpu = false;
    cp.flash_attn = true;
    whisper_context *ctx = whisper_init_from_file_with_params(path, cp);
    LOGI("init %s -> %p", path, ctx);
    env->ReleaseStringUTFChars(jpath, path);
    return reinterpret_cast<jlong>(ctx);
}

extern "C" JNIEXPORT void JNICALL
Java_com_tradutorrt_whisper_WhisperNative_nativeFree(JNIEnv *, jobject, jlong handle) {
    if (handle) whisper_free(reinterpret_cast<whisper_context *>(handle));
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_tradutorrt_whisper_WhisperNative_nativeSystemInfo(JNIEnv *env, jobject) {
    return env->NewStringUTF(whisper_print_system_info());
}

extern "C" JNIEXPORT jint JNICALL
Java_com_tradutorrt_whisper_WhisperNative_nativeLangMaxId(JNIEnv *, jobject) {
    return whisper_lang_max_id();
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_tradutorrt_whisper_WhisperNative_nativeLangStr(JNIEnv *env, jobject, jint id) {
    const char *s = whisper_lang_str(id);
    return env->NewStringUTF(s ? s : "");
}

// Retorna as probabilidades de todos os idiomas (indice = id do whisper) ou null em erro.
extern "C" JNIEXPORT jfloatArray JNICALL
Java_com_tradutorrt_whisper_WhisperNative_nativeDetectLanguage(JNIEnv *env, jobject, jlong handle,
                                                               jfloatArray jpcm, jint threads) {
    auto *ctx = reinterpret_cast<whisper_context *>(handle);
    jsize n = env->GetArrayLength(jpcm);
    std::vector<float> pcm(n);
    env->GetFloatArrayRegion(jpcm, 0, n, pcm.data());
    if (whisper_pcm_to_mel(ctx, pcm.data(), n, threads) != 0) {
        LOGE("pcm_to_mel failed");
        return nullptr;
    }
    std::vector<float> probs(whisper_lang_max_id() + 1, 0.0f);
    if (whisper_lang_auto_detect(ctx, 0, threads, probs.data()) < 0) {
        LOGE("lang_auto_detect failed");
        return nullptr;
    }
    jfloatArray out = env->NewFloatArray((jsize) probs.size());
    env->SetFloatArrayRegion(out, 0, (jsize) probs.size(), probs.data());
    return out;
}

// Transcreve. lang = codigo ISO ("pt", "en") ou "auto".
// Obs.: no modo "auto" a deteccao de idioma interna do whisper.cpp usa o audio_ctx da chamada ANTERIOR
// (state->exp_n_audio_ctx e atribuido depois dela); o mesmo vale para nativeDetectLanguage. Depois de uma
// parcial com contexto reduzido, a LID do turno final roda sobre esse contexto, que ja cobre quase todo o turno. audioCtx = 0 usa os 1500 frames padrao;
// valores menores aceleram o encoder para audio curto (usado nas transcricoes parciais).
// Retorna UTF-8 bruto: "<lang>\n<texto>".
extern "C" JNIEXPORT jbyteArray JNICALL
Java_com_tradutorrt_whisper_WhisperNative_nativeTranscribe(JNIEnv *env, jobject, jlong handle,
                                                           jfloatArray jpcm, jint threads, jstring jlang,
                                                           jint audioCtx, jboolean partial, jint maxTokens) {
    auto *ctx = reinterpret_cast<whisper_context *>(handle);
    jsize n = env->GetArrayLength(jpcm);
    std::vector<float> pcm(n);
    env->GetFloatArrayRegion(jpcm, 0, n, pcm.data());
    const char *lang_c = env->GetStringUTFChars(jlang, nullptr);
    std::string lang(lang_c);
    env->ReleaseStringUTFChars(jlang, lang_c);

    whisper_full_params p = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    p.n_threads = threads;
    p.language = lang.c_str();
    p.detect_language = false;
    p.translate = false;
    p.no_context = true;
    p.no_timestamps = true;
    p.single_segment = partial;
    p.print_special = false;
    p.print_progress = false;
    p.print_realtime = false;
    p.print_timestamps = false;
    p.suppress_blank = true;
    p.suppress_nst = true;
    p.audio_ctx = audioCtx;
    p.max_tokens = maxTokens;  // limita alucinacoes por repeticao (sobretudo com audio_ctx reduzido)
    if (partial) p.temperature_inc = 0.0f;  // sem fallback de temperatura nas parciais

    std::string text;
    if (whisper_full(ctx, p, pcm.data(), n) != 0) {
        LOGE("whisper_full failed");
        return nullptr;
    }
    int ns = whisper_full_n_segments(ctx);
    for (int i = 0; i < ns; ++i) text += whisper_full_get_segment_text(ctx, i);
    const char *detected = whisper_lang_str(whisper_full_lang_id(ctx));
    std::string out = std::string(detected ? detected : lang.c_str()) + "\n" + text;
    return to_bytes(env, out);
}
