package com.tradutorrt.whisper

/** Ponte JNI para whisper.cpp. Use um [WhisperContext] por thread. */
object WhisperNative {
    init {
        System.loadLibrary("whisper_jni")
    }

    external fun nativeInit(path: String): Long
    external fun nativeFree(handle: Long)
    external fun nativeSystemInfo(): String
    external fun nativeLangMaxId(): Int
    external fun nativeLangStr(id: Int): String
    external fun nativeDetectLanguage(handle: Long, pcm: FloatArray, threads: Int): FloatArray?
    external fun nativeTranscribe(
        handle: Long, pcm: FloatArray, threads: Int, lang: String, audioCtx: Int, partial: Boolean, maxTokens: Int,
    ): ByteArray?
}

data class Transcript(val language: String, val text: String)

/** Parametros de uma transcricao parcial para [samples] amostras de 16 kHz. */
object PartialParams {
    /** ~50 frames do encoder por segundo + margem. */
    fun audioCtx(samples: Int) = minOf(1500, samples / 320 + 128)

    /** ~4 tokens por segundo de fala + folga: corta o "loop" de repeticao tipico de contexto reduzido. */
    fun maxTokens(samples: Int) = 8 + samples * 5 / 16000

    /**
     * Contexto do encoder para o turno final no modo rapido: duracao + ~5 s de margem. No teste de host
     * deu a mesma transcricao que o contexto cheio (30 s) com ~1/3 do tempo.
     */
    fun finalAudioCtx(samples: Int) = minOf(1500, samples / 320 + 256)
}

class WhisperContext private constructor(private var handle: Long) : AutoCloseable {
    companion object {
        fun load(path: String): WhisperContext {
            val h = WhisperNative.nativeInit(path)
            require(h != 0L) { "Falha ao carregar o modelo Whisper: $path" }
            return WhisperContext(h)
        }

        /** Codigos ISO de todos os idiomas do Whisper, na ordem dos ids. */
        val languages: List<String> by lazy {
            (0..WhisperNative.nativeLangMaxId()).map { WhisperNative.nativeLangStr(it) }
        }
    }

    /** Probabilidade por codigo de idioma. */
    fun detectLanguage(pcm: FloatArray, threads: Int): Map<String, Float> {
        val probs = WhisperNative.nativeDetectLanguage(handle, pcm, threads) ?: return emptyMap()
        return probs.indices.associate { languages[it] to probs[it] }
    }

    /**
     * @param audioCtx 0 = 1500 frames (30 s); menor acelera o encoder para audio curto (parciais).
     * @param maxTokens 0 = sem limite.
     */
    fun transcribe(
        pcm: FloatArray, threads: Int, lang: String, audioCtx: Int = 0, partial: Boolean = false, maxTokens: Int = 0,
    ): Transcript? {
        val raw = WhisperNative.nativeTranscribe(handle, pcm, threads, lang, audioCtx, partial, maxTokens) ?: return null
        val s = String(raw, Charsets.UTF_8)
        val nl = s.indexOf('\n')
        return Transcript(s.substring(0, nl), s.substring(nl + 1).trim())
    }

    override fun close() {
        if (handle != 0L) WhisperNative.nativeFree(handle)
        handle = 0L
    }
}
