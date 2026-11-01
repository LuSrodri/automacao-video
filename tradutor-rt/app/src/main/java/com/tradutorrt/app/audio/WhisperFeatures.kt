package com.tradutorrt.app.audio

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Port fiel do pre-processamento do Smart Turn (pipecat-ai/smart-turn, inference.py):
 *   1. mantem os ultimos 8 s; se for mais curto, completa com zeros NO INICIO;
 *   2. WhisperFeatureExtractor(chunk_length=8) com do_normalize=True:
 *      normalizacao media 0 / variancia 1 sobre os 128000 amostras (eps 1e-7);
 *   3. STFT center=True com padding "reflect", janela Hann periodica de 400, hop 160, potencia 2;
 *   4. banco mel slaney de 80 filtros (mesma matriz do transformers, carregada de asset),
 *      log10(max(1e-10, .)), descarta o ultimo frame, clamp em (max - 8), (x + 4) / 4.
 * Saida: [80 x 800] em ordem row-major (mel, frame).
 *
 * A DFT de 400 pontos e feita direto com tabelas; os frames inteiramente dentro do preenchimento
 * inicial (constante apos a normalizacao) sao calculados uma vez so, o que torna turnos curtos baratos.
 */
class WhisperFeatures(private val melFilters: FloatArray /* [201 * 80], row-major (freq, mel) */) {
    companion object {
        const val SAMPLE_RATE = 16000
        const val N_SAMPLES = 8 * SAMPLE_RATE
        const val N_FFT = 400
        const val HOP = 160
        const val N_FREQ = N_FFT / 2 + 1
        const val N_MELS = 80
        const val N_FRAMES = N_SAMPLES / HOP // 800 (801 - 1)
    }

    init {
        require(melFilters.size == N_FREQ * N_MELS)
    }

    private val window = FloatArray(N_FFT) { (0.5 - 0.5 * cos(2.0 * PI * it / N_FFT)).toFloat() }
    private val cosT = FloatArray(N_FREQ * N_FFT)
    private val sinT = FloatArray(N_FREQ * N_FFT)

    init {
        for (k in 0 until N_FREQ) for (n in 0 until N_FFT) {
            val a = 2.0 * PI * ((k.toLong() * n) % N_FFT) / N_FFT
            cosT[k * N_FFT + n] = cos(a).toFloat()
            sinT[k * N_FFT + n] = sin(a).toFloat()
        }
    }

    /** Aplica o passo 1 (ultimos 8 s, zeros a esquerda). Retorna o vetor e quantos zeros entraram. */
    fun padOrTruncate(audio: FloatArray): Pair<FloatArray, Int> {
        if (audio.size >= N_SAMPLES) return audio.copyOfRange(audio.size - N_SAMPLES, audio.size) to 0
        val out = FloatArray(N_SAMPLES)
        val pad = N_SAMPLES - audio.size
        System.arraycopy(audio, 0, out, pad, audio.size)
        return out to pad
    }

    fun compute(audio: FloatArray): FloatArray {
        val (x, padLen) = padOrTruncate(audio)
        // normalizacao (em double para bater com o numpy)
        var mean = 0.0
        for (v in x) mean += v
        mean /= x.size
        var varSum = 0.0
        for (v in x) {
            val d = v - mean
            varSum += d * d
        }
        val std = sqrt(varSum / x.size + 1e-7)
        val xn = FloatArray(x.size) { ((x[it] - mean) / std).toFloat() }

        val half = N_FFT / 2
        val mel = FloatArray(N_MELS * N_FRAMES)
        val frame = FloatArray(N_FFT)
        val power = FloatArray(N_FREQ)
        val melFrame = FloatArray(N_MELS)
        var constFrame: FloatArray? = null
        // frames cujas amostras (incluindo o reflexo do inicio) estao todas dentro do preenchimento
        val constLimit = if (padLen > half + 1) (padLen - half) / HOP else -1

        for (f in 0 until N_FRAMES) {
            if (f <= constLimit && constFrame != null) {
                for (m in 0 until N_MELS) mel[m * N_FRAMES + f] = constFrame[m]
                continue
            }
            val start = f * HOP - half
            for (n in 0 until N_FFT) {
                var idx = start + n
                if (idx < 0) idx = -idx
                if (idx >= N_SAMPLES) idx = 2 * (N_SAMPLES - 1) - idx
                frame[n] = xn[idx] * window[n]
            }
            for (k in 0 until N_FREQ) {
                var re = 0f
                var im = 0f
                val base = k * N_FFT
                for (n in 0 until N_FFT) {
                    val v = frame[n]
                    re += v * cosT[base + n]
                    im += v * sinT[base + n]
                }
                power[k] = re * re + im * im
            }
            for (m in 0 until N_MELS) {
                var s = 0f
                for (k in 0 until N_FREQ) s += melFilters[k * N_MELS + m] * power[k]
                melFrame[m] = log10(max(s, 1e-10f))
                mel[m * N_FRAMES + f] = melFrame[m]
            }
            if (f <= constLimit && constFrame == null) constFrame = melFrame.copyOf()
        }
        var mx = Float.NEGATIVE_INFINITY
        for (v in mel) if (v > mx) mx = v
        val floor = mx - 8f
        for (i in mel.indices) mel[i] = (max(mel[i], floor) + 4f) / 4f
        return mel
    }
}
