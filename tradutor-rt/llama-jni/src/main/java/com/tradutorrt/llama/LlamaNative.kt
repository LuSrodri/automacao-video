package com.tradutorrt.llama

/** Ponte JNI para llama.cpp. */
object LlamaNative {
    init {
        System.loadLibrary("llama_jni")
    }

    external fun nativeLoad(path: String, threads: Int, nCtx: Int): Long
    external fun nativeFree(handle: Long)
    external fun nativeSystemInfo(): String
    external fun nativeSetSampling(handle: Long, temp: Float, topK: Int, topP: Float, repeatPenalty: Float)
    external fun nativeGenerate(handle: Long, prompt: ByteArray, maxTokens: Int, stats: LongArray?): ByteArray?
}

data class GenerationStats(
    val reusedPromptTokens: Long,
    val evaluatedPromptTokens: Long,
    val generatedTokens: Long,
    val prefillMs: Long,
    val decodeMs: Long,
)

/**
 * Um modelo + contexto carregados uma vez. O KV cache e reaproveitado entre chamadas
 * (prefixo comum do prompt nao e recalculado). Nao e thread-safe: use um dispatcher dedicado.
 */
class LlamaEngine private constructor(private var handle: Long) : AutoCloseable {
    companion object {
        fun load(path: String, threads: Int, nCtx: Int = 2048): LlamaEngine {
            val h = LlamaNative.nativeLoad(path, threads, nCtx)
            require(h != 0L) { "Falha ao carregar o modelo GGUF: $path" }
            return LlamaEngine(h)
        }
    }

    var lastStats: GenerationStats? = null
        private set

    fun setSampling(temp: Float, topK: Int, topP: Float, repeatPenalty: Float) =
        LlamaNative.nativeSetSampling(handle, temp, topK, topP, repeatPenalty)

    fun generate(prompt: String, maxTokens: Int): String? {
        val st = LongArray(5)
        val out = LlamaNative.nativeGenerate(handle, prompt.toByteArray(Charsets.UTF_8), maxTokens, st) ?: return null
        lastStats = GenerationStats(st[0], st[1], st[2], st[3], st[4])
        return String(out, Charsets.UTF_8)
    }

    override fun close() {
        if (handle != 0L) LlamaNative.nativeFree(handle)
        handle = 0L
    }
}
