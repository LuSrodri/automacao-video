package com.tradutorrt.app.audio

/**
 * Maquina de estados VAD + Smart Turn.
 *
 *  IDLE --(fala por minSpeechChunks)--> SPEAKING --(silencio por pauseChunks)--> PAUSED
 *  PAUSED: pede Smart Turn sobre o turno atual (ultimos 8 s).
 *     - prob > limiar          -> TurnComplete
 *     - prob <= limiar         -> continua esperando
 *     - pessoa volta a falar   -> SPEAKING (resultado pendente e descartado; na proxima pausa roda de novo
 *                                 sobre o turno inteiro)
 *     - silencio > maxSilenceMs -> TurnComplete (rede de seguranca)
 *
 * Nao e thread-safe: o pipeline chama tudo a partir da mesma coroutine.
 */
class TurnDetector(private val cfg: Config = Config()) {

    data class Config(
        val chunkSamples: Int = 512,
        val sampleRate: Int = 16000,
        val speechThreshold: Float = 0.5f,
        val silenceThreshold: Float = 0.35f,
        val minSpeechChunks: Int = 3,      // ~96 ms para abrir um turno
        val pauseChunks: Int = 6,          // ~192 ms de silencio para consultar o Smart Turn
        val preRollChunks: Int = 10,       // ~320 ms de audio antes do inicio da fala
        val maxSilenceMs: Long = 2500,     // fecha o turno mesmo que o Smart Turn diga "incompleto"
        val maxTurnMs: Long = 28_000,      // Whisper processa janelas de 30 s
        val partialIntervalMs: Long = 900,
        val minVoicedMs: Long = 250,       // turnos mais curtos sao descartados (ruido)
        val tailKeepMs: Long = 300,        // silencio mantido no fim do audio enviado ao ASR
    )

    enum class EndReason { SMART_TURN, SILENCE_TIMEOUT, MAX_LENGTH }

    sealed class Event {
        data class SpeechStarted(val turnId: Int) : Event()
        data class RunSmartTurn(val turnId: Int, val version: Int, val audio: FloatArray) : Event()
        data class Partial(val turnId: Int, val audio: FloatArray) : Event()
        data class TurnComplete(
            val turnId: Int,
            val audio: FloatArray,
            val reason: EndReason,
            val endOfSpeechNanos: Long,
            val decisionNanos: Long,
            val smartTurnProb: Float?,
        ) : Event()
        data class TurnDiscarded(val turnId: Int) : Event()
    }

    enum class State { IDLE, SPEAKING, PAUSED }

    var state = State.IDLE
        private set
    private var turnId = 0
    private var version = 0
    private val preRoll = ArrayDeque<FloatArray>()
    private val turn = ArrayList<FloatArray>()
    private var speechRun = 0
    private var silenceRun = 0
    private var voicedChunks = 0
    private var lastVoiceChunkIndex = 0  // indice (em turn) do ultimo bloco com fala
    private var lastVoiceNanos = 0L
    private var lastPartialChunks = 0
    private var lastSmartTurnProb: Float? = null

    private val msPerChunk = cfg.chunkSamples * 1000.0 / cfg.sampleRate
    private fun chunksFor(ms: Long) = (ms / msPerChunk).toInt()

    fun reset() {
        state = State.IDLE
        preRoll.clear()
        turn.clear()
        speechRun = 0
        silenceRun = 0
        version++
    }

    fun process(chunk: FloatArray, prob: Float, nowNanos: Long): List<Event> {
        val ev = ArrayList<Event>(2)
        when (state) {
            State.IDLE -> {
                preRoll.addLast(chunk)
                if (preRoll.size > cfg.preRollChunks) preRoll.removeFirst()
                speechRun = if (prob >= cfg.speechThreshold) speechRun + 1 else 0
                if (speechRun >= cfg.minSpeechChunks) {
                    turnId++
                    version++
                    turn.clear()
                    turn.addAll(preRoll)
                    preRoll.clear()
                    state = State.SPEAKING
                    silenceRun = 0
                    voicedChunks = speechRun
                    lastVoiceChunkIndex = turn.size - 1
                    lastVoiceNanos = nowNanos
                    lastPartialChunks = turn.size
                    lastSmartTurnProb = null
                    ev += Event.SpeechStarted(turnId)
                }
            }
            State.SPEAKING, State.PAUSED -> {
                turn.add(chunk)
                val voiced = prob >= cfg.speechThreshold
                if (voiced) {
                    voicedChunks++
                    lastVoiceChunkIndex = turn.size - 1
                    lastVoiceNanos = nowNanos
                    silenceRun = 0
                    if (state == State.PAUSED) {
                        state = State.SPEAKING
                        version++ // invalida Smart Turn pendente
                    }
                } else if (prob < cfg.silenceThreshold) {
                    silenceRun++
                }
                if (state == State.SPEAKING) {
                    if (silenceRun >= cfg.pauseChunks) {
                        state = State.PAUSED
                        version++
                        ev += Event.RunSmartTurn(turnId, version, audioUpTo(turn.size, maxMs = 8000))
                    } else if (turn.size - lastPartialChunks >= chunksFor(cfg.partialIntervalMs)) {
                        lastPartialChunks = turn.size
                        ev += Event.Partial(turnId, audioUpTo(turn.size))
                    }
                }
                val turnMs = (turn.size * msPerChunk).toLong()
                val silenceMs = ((turn.size - 1 - lastVoiceChunkIndex) * msPerChunk).toLong()
                if (turnMs >= cfg.maxTurnMs) {
                    ev += finish(EndReason.MAX_LENGTH, nowNanos)
                } else if (state == State.PAUSED && silenceMs >= cfg.maxSilenceMs) {
                    ev += finish(EndReason.SILENCE_TIMEOUT, nowNanos)
                }
            }
        }
        return ev
    }

    /** Resultado do Smart Turn; ignorado se o turno mudou ou a pessoa voltou a falar. */
    fun onSmartTurn(turnId: Int, version: Int, prob: Float, threshold: Float, nowNanos: Long): List<Event> {
        if (turnId != this.turnId || version != this.version || state != State.PAUSED) return emptyList()
        lastSmartTurnProb = prob
        return if (prob > threshold) listOf(finish(EndReason.SMART_TURN, nowNanos)) else emptyList()
    }

    private fun finish(reason: EndReason, nowNanos: Long): Event {
        val id = turnId
        val voicedMs = (voicedChunks * msPerChunk).toLong()
        val end = minOf(turn.size, lastVoiceChunkIndex + 1 + chunksFor(cfg.tailKeepMs))
        val audio = audioUpTo(end)
        val st = lastSmartTurnProb
        turn.clear()
        preRoll.clear()
        state = State.IDLE
        speechRun = 0
        silenceRun = 0
        version++
        if (voicedMs < cfg.minVoicedMs) return Event.TurnDiscarded(id)
        return Event.TurnComplete(id, audio, reason, lastVoiceNanos, nowNanos, st)
    }

    private fun audioUpTo(endChunk: Int, maxMs: Long = Long.MAX_VALUE): FloatArray {
        val maxChunks = if (maxMs == Long.MAX_VALUE) Int.MAX_VALUE else chunksFor(maxMs)
        val start = maxOf(0, endChunk - maxChunks)
        val out = FloatArray((endChunk - start) * cfg.chunkSamples)
        for (i in start until endChunk) System.arraycopy(turn[i], 0, out, (i - start) * cfg.chunkSamples, cfg.chunkSamples)
        return out
    }
}
