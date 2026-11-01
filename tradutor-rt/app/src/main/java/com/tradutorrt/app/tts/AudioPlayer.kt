package com.tradutorrt.app.tts

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * Reproducao em streaming (PCM float mono). Os blocos sao enfileirados e tocados numa thread propria,
 * de modo que a sintese da frase seguinte acontece enquanto a anterior toca.
 */
class AudioPlayer(private val sampleRate: Int) : AutoCloseable {
    private val queue = LinkedBlockingQueue<FloatArray>()
    private val pending = AtomicInteger(0)
    @Volatile private var running = true
    @Volatile var onIdle: (() -> Unit)? = null

    private val track = AudioTrack.Builder()
        .setAudioAttributes(
            AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build(),
        )
        .setAudioFormat(
            AudioFormat.Builder().setEncoding(AudioFormat.ENCODING_PCM_FLOAT).setSampleRate(sampleRate)
                .setChannelMask(AudioFormat.CHANNEL_OUT_MONO).build(),
        )
        .setBufferSizeInBytes(
            maxOf(AudioTrack.getMinBufferSize(sampleRate, AudioFormat.CHANNEL_OUT_MONO, AudioFormat.ENCODING_PCM_FLOAT), sampleRate),
        )
        .setTransferMode(AudioTrack.MODE_STREAM)
        .build()

    private val worker = thread(name = "audio-player", isDaemon = true) {
        track.play()
        val silence = FloatArray(sampleRate / 10)
        while (running) {
            val buf = try {
                queue.take()
            } catch (_: InterruptedException) {
                break
            }
            if (buf.isEmpty()) continue
            track.write(buf, 0, buf.size, AudioTrack.WRITE_BLOCKING)
            if (pending.decrementAndGet() == 0) {
                // empurra o fim do audio pelo buffer do AudioTrack antes de sinalizar "ocioso"
                track.write(silence, 0, silence.size, AudioTrack.WRITE_BLOCKING)
                if (pending.get() == 0) onIdle?.invoke()
            }
        }
    }

    val isBusy: Boolean get() = pending.get() > 0

    fun enqueue(samples: FloatArray) {
        if (samples.isEmpty()) return
        pending.incrementAndGet()
        queue.put(samples)
    }

    fun stop() {
        queue.clear()
        pending.set(0)
        track.pause()
        track.flush()
        track.play()
        onIdle?.invoke()
    }

    override fun close() {
        running = false
        worker.interrupt()
        track.release()
    }
}
