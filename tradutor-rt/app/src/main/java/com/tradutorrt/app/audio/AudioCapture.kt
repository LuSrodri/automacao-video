package com.tradutorrt.app.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.isActive

/** Captura do microfone em 16 kHz mono, entregando blocos de 512 amostras (32 ms) em float [-1, 1]. */
class AudioCapture {
    companion object {
        const val SAMPLE_RATE = 16000
        const val CHUNK = 512
    }

    @SuppressLint("MissingPermission")
    suspend fun run(onChunk: suspend (FloatArray, Long) -> Unit) {
        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val rec = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION, SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, SAMPLE_RATE * 2),
        )
        check(rec.state == AudioRecord.STATE_INITIALIZED) { "AudioRecord nao inicializou" }
        val aec = if (AcousticEchoCanceler.isAvailable()) AcousticEchoCanceler.create(rec.audioSessionId) else null
        aec?.enabled = true
        val ns = if (NoiseSuppressor.isAvailable()) NoiseSuppressor.create(rec.audioSessionId) else null
        ns?.enabled = false // o Silero e o Whisper preferem audio sem supressao agressiva
        val buf = ShortArray(CHUNK)
        try {
            rec.startRecording()
            while (coroutineContext.isActive) {
                var read = 0
                while (read < CHUNK) {
                    val n = rec.read(buf, read, CHUNK - read)
                    if (n <= 0) throw IllegalStateException("AudioRecord.read = $n")
                    read += n
                }
                val f = FloatArray(CHUNK) { buf[it] / 32768f }
                onChunk(f, System.nanoTime())
            }
        } finally {
            runCatching { rec.stop() }
            rec.release()
            aec?.release()
            ns?.release()
        }
    }
}
