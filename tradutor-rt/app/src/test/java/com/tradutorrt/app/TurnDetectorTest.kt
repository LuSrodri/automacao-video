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
    fun completesWhenSmartTurnSaysSo() {
        val d = TurnDetector()
        val ev = feed(d, 0.9f, 40) + feed(d, 0.05f, 6)
        assertTrue(ev.first() is Event.SpeechStarted)
        val st = ev.filterIsInstance<Event.RunSmartTurn>().single()
        assertTrue(ev.any { it is Event.Partial })
        val done = d.onSmartTurn(st.turnId, st.version, 0.8f, 0.5f, t).single() as Event.TurnComplete
        assertEquals(TurnDetector.EndReason.SMART_TURN, done.reason)
        // pre-roll (3 blocos antes da abertura) + fala + 300 ms de cauda
        assertTrue(done.audio.size >= 40 * 512)
        assertEquals(TurnDetector.State.IDLE, d.state)
    }

    @Test
    fun resumesAndRerunsOnWholeTurnWhenIncomplete() {
        val d = TurnDetector()
        feed(d, 0.9f, 30)
        val first = feed(d, 0.05f, 6).filterIsInstance<Event.RunSmartTurn>().single()
        assertTrue(d.onSmartTurn(first.turnId, first.version, 0.2f, 0.5f, t).isEmpty())
        feed(d, 0.9f, 20) // voltou a falar
        // resultado atrasado da primeira consulta e ignorado
        assertTrue(d.onSmartTurn(first.turnId, first.version, 0.99f, 0.5f, t).isEmpty())
        val second = feed(d, 0.05f, 6).filterIsInstance<Event.RunSmartTurn>().single()
        assertTrue("segunda consulta usa o turno inteiro", second.audio.size > first.audio.size)
        val done = d.onSmartTurn(second.turnId, second.version, 0.7f, 0.5f, t).single()
        assertTrue(done is Event.TurnComplete)
    }

    @Test
    fun silenceTimeoutClosesTurn() {
        val d = TurnDetector()
        feed(d, 0.9f, 20)
        val ev = feed(d, 0.0f, 100)
        val done = ev.filterIsInstance<Event.TurnComplete>().single()
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
