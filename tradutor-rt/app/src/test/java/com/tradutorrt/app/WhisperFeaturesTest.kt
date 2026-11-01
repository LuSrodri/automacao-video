package com.tradutorrt.app

import com.tradutorrt.app.audio.WhisperFeatures
import kotlin.math.abs
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Compara com transformers.WhisperFeatureExtractor(chunk_length=8) usado pelo pipecat-ai/smart-turn. */
class WhisperFeaturesTest {
    private val fe = WhisperFeatures(TestUtil.floats(TestUtil.asset("whisper_mel_filters_201x80.f32").readBytes()))

    @Test
    fun matchesHuggingFaceExtractor() {
        val audio = TestUtil.resourceFloats("st_audio.f32")
        val expected = TestUtil.resourceFloats("st_features.f32")
        val t0 = System.nanoTime()
        val got = fe.compute(audio)
        println("WhisperFeatures (2.7 s de audio): ${(System.nanoTime() - t0) / 1_000_000} ms")
        assertEquals(80 * 800, got.size)
        var maxErr = 0f
        for (i in got.indices) maxErr = maxOf(maxErr, abs(got[i] - expected[i]))
        println("max |erro| = $maxErr")
        assertTrue("erro maximo $maxErr", maxErr < 2e-3f)
    }

    @Test
    fun longAudioKeepsLast8Seconds() {
        val audio = FloatArray(10 * 16000) { if (it < 2 * 16000) 0.9f else 0f }
        val (x, pad) = fe.padOrTruncate(audio)
        assertEquals(8 * 16000, x.size)
        assertEquals(0, pad)
        assertTrue(x.all { it == 0f })
    }
}
