package com.tradutorrt.app.tts

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.CompletableDeferred

/** Fallback: TextToSpeech nativo do Android (para idiomas que o Soprano nao fala). */
class SystemTts(context: Context) : AutoCloseable {
    private val ready = CompletableDeferred<Boolean>()
    private val active = AtomicInteger(0)
    @Volatile var onIdle: (() -> Unit)? = null
    @Volatile var onStart: (() -> Unit)? = null

    private val tts = TextToSpeech(context.applicationContext) { status -> ready.complete(status == TextToSpeech.SUCCESS) }

    init {
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(utteranceId: String?) {
                onStart?.invoke()
            }

            override fun onDone(utteranceId: String?) = finished()

            @Deprecated("Deprecated in Java")
            override fun onError(utteranceId: String?) = finished()

            override fun onError(utteranceId: String?, errorCode: Int) = finished()
        })
    }

    private fun finished() {
        if (active.decrementAndGet() <= 0) {
            active.set(0)
            onIdle?.invoke()
        }
    }

    val isBusy: Boolean get() = active.get() > 0

    /** Retorna false se o idioma nao estiver disponivel no motor de TTS do aparelho. */
    suspend fun speak(text: String, lang: String): Boolean {
        if (!ready.await()) return false
        val locale = Locale.forLanguageTag(if (lang == "yue") "zh-HK" else lang)
        val avail = tts.isLanguageAvailable(locale)
        if (avail < TextToSpeech.LANG_AVAILABLE) return false
        tts.language = locale
        active.incrementAndGet()
        val r = tts.speak(text, TextToSpeech.QUEUE_ADD, null, "u" + System.nanoTime())
        if (r != TextToSpeech.SUCCESS) {
            finished()
            return false
        }
        return true
    }

    fun stop() {
        tts.stop()
        active.set(0)
        onIdle?.invoke()
    }

    override fun close() {
        tts.shutdown()
    }
}
