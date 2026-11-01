package com.tradutorrt.app

import com.tradutorrt.app.audio.TurnDetector
import com.tradutorrt.app.audio.TurnDetector.Event
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TurnDetectorTest {
    private val chunk = FloatArray(512)
    private var t = 0L
    private fun feed(d: TurnDetector, prob: Float, n: Int): List<Event> =
        (0 until n).flatMap { t += 32_000_000L; d.process(chunk, prob, t) }

    @Test
    fun completesOnlyAfterSmartTurnAndMinimumPause() {
        val d = TurnDetector().apply { minEndSilenceMs = 600 }
        val ev = feed(d, 0.9f, 40) + feed(d, 0.05f, 6)
        assertTrue(ev.first() is Event.SpeechStarted)
        val st = ev.filterIsInstance<Event.RunSmartTurn>().single()
        assertTrue(ev.any { it is Event.Partial })
        // Smart Turn diz "completo" com ~190 ms de pausa: ainda NAO fecha
        assertTrue(d.onSmartTurn(st.turnId, st.version, 0.95f, t).isEmpty())
        assertTrue(feed(d, 0.05f, 10).none { it is Event.TurnComplete }) // ~510 ms
        val done = feed(d, 0.05f, 3).filterIsInstance<Event.TurnComplete>().single() // passa de 600 ms
        assertEquals(TurnDetector.EndReason.SMART_TURN, done.reason)
        assertTrue((done.decisionNanos - done.endOfSpeechNanos) / 1_000_000 in 600..700)
        assertTrue(done.audio.size >= 40 * 512)
        assertEquals(TurnDetector.State.IDLE, d.state)
    }

    @Test
    fun commaPauseDoesNotSplitSentence() {
        val d = TurnDetector().apply { minEndSilenceMs = 600 }
        feed(d, 0.9f, 30)
        val first = feed(d, 0.05f, 6).filterIsInstance<Event.RunSmartTurn>().single()
        assertTrue(d.onSmartTurn(first.turnId, first.version, 0.9f, t).isEmpty())
        feed(d, 0.05f, 4) // pausa de virgula ~320 ms
        val resumed = feed(d, 0.9f, 20)
        assertTrue(resumed.none { it is Event.TurnComplete })
        assertEquals(TurnDetector.State.SPEAKING, d.state)
        // resultado atrasado da primeira consulta e ignorado
        assertTrue(d.onSmartTurn(first.turnId, first.version, 0.99f, t).isEmpty())
        val second = feed(d, 0.05f, 6).filterIsInstance<Event.RunSmartTurn>().single()
        assertTrue("segunda consulta usa o turno inteiro", second.audio.size > first.audio.size)
        d.onSmartTurn(second.turnId, second.version, 0.7f, t)
        val done = feed(d, 0.05f, 15).filterIsInstance<Event.TurnComplete>().single()
        assertTrue("frase inteira num turno so", done.audio.size >= 50 * 512)
    }

    @Test
    fun singleNoiseBlipDoesNotResume() {
        val d = TurnDetector().apply { minEndSilenceMs = 600 }
        feed(d, 0.9f, 20)
        val st = feed(d, 0.05f, 6).filterIsInstance<Event.RunSmartTurn>().single()
        d.onSmartTurn(st.turnId, st.version, 0.9f, t)
        feed(d, 0.05f, 5)
        feed(d, 0.8f, 1) // estalo isolado
        assertEquals(TurnDetector.State.PAUSED, d.state)
        assertTrue(feed(d, 0.05f, 10).any { it is Event.TurnComplete })
    }

    @Test
    fun incompleteWaitsUntilSilenceTimeout() {
        val d = TurnDetector()
        feed(d, 0.9f, 20)
        val st = feed(d, 0.0f, 6).filterIsInstance<Event.RunSmartTurn>().single()
        d.onSmartTurn(st.turnId, st.version, 0.1f, t)
        assertTrue(feed(d, 0.0f, 40).none { it is Event.TurnComplete }) // ~1,5 s
        val done = feed(d, 0.0f, 30).filterIsInstance<Event.TurnComplete>().single()
        assertEquals(TurnDetector.EndReason.SILENCE_TIMEOUT, done.reason)
    }

    @Test
    fun shortNoiseIsDiscarded() {
        val d = TurnDetector()
        feed(d, 0.9f, 3)
        val ev = feed(d, 0.0f, 100)
        assertTrue(ev.any { it is Event.TurnDiscarded })
        assertTrue(ev.none { it is Event.TurnComplete })
    }
}
