package com.tradutorrt.app.audio

/**
 * Maquina de estados VAD + Smart Turn.
 *
 *  IDLE --(fala por minSpeechChunks)--> SPEAKING --(silencio por pauseChunks)--> PAUSED
 *  Ao entrar em PAUSED o Smart Turn e consultado imediatamente sobre o turno atual (ultimos 8 s),
 *  mas o turno so fecha quando AS DUAS condicoes valem:
 *     - Smart Turn deu prob > limiar, e
 *     - o silencio ja dura [minEndSilenceMs].
 *  Motivo (medido com 80 frases reais do FLEURS pt/en): com so ~200 ms de pausa o Smart Turn v3.2 diz
 *  "completo" em ~83% das pausas internas (virgulas), cortando ~1,1 vez por frase; pausas internas
 *  com 600 ms ou mais sao raras, e todo fim real passa disso.
 *     - Smart Turn <= limiar: espera; fecha por seguranca com [maxSilenceMs] de silencio.
 *     - A pessoa volta a falar (2 blocos seguidos com voz): volta a SPEAKING, o resultado pendente e
 *       descartado e na proxima pausa o Smart Turn roda de novo sobre o turno inteiro.
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
        val resumeChunks: Int = 2,         // blocos seguidos com voz para considerar que voltou a falar
        val preRollChunks: Int = 10,       // ~320 ms de audio antes do inicio da fala
        val maxSilenceMs: Long = 2000,     // fecha o turno mesmo que o Smart Turn diga "incompleto"
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

    /** Limiar do Smart Turn (pode mudar a qualquer momento, vem das configuracoes). */
    var threshold: Float = 0.5f

    /** Pausa minima para fechar o turno quando o Smart Turn diz "completo". */
    var minEndSilenceMs: Long = 600

    var state = State.IDLE
        private set
    private var turnId = 0
    private var version = 0
    private val preRoll = ArrayDeque<FloatArray>()
    private val turn = ArrayList<FloatArray>()
    private var speechRun = 0
    private var silenceRun = 0
    private var resumeRun = 0
    private var voicedChunks = 0
    private var lastVoiceChunkIndex = 0  // indice (em turn) do ultimo bloco com fala
    private var lastVoiceNanos = 0L
    private var lastPartialChunks = 0
    private var stProb: Float? = null     // resultado do Smart Turn para a pausa atual
    private var lastStProb: Float? = null

    private val msPerChunk = cfg.chunkSamples * 1000.0 / cfg.sampleRate
    private fun chunksFor(ms: Long) = (ms / msPerChunk).toInt()

    /** Silencio desde o ultimo bloco com voz, em ms. */
    val silenceMs: Long get() = if (state == State.IDLE) 0 else ((turn.size - 1 - lastVoiceChunkIndex) * msPerChunk).toLong()

    fun reset() {
        state = State.IDLE
        preRoll.clear()
        turn.clear()
        speechRun = 0
        silenceRun = 0
        resumeRun = 0
        stProb = null
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
                    resumeRun = 0
                    voicedChunks = speechRun
                    lastVoiceChunkIndex = turn.size - 1
                    lastVoiceNanos = nowNanos
                    lastPartialChunks = turn.size
                    stProb = null
                    lastStProb = null
                    ev += Event.SpeechStarted(turnId)
                }
            }
            State.SPEAKING -> {
                turn.add(chunk)
                if (prob >= cfg.speechThreshold) {
                    voicedChunks++
                    lastVoiceChunkIndex = turn.size - 1
                    lastVoiceNanos = nowNanos
                    silenceRun = 0
                } else if (prob < cfg.silenceThreshold) {
                    silenceRun++
                }
                if (silenceRun >= cfg.pauseChunks) {
                    state = State.PAUSED
                    version++
                    stProb = null
                    resumeRun = 0
                    ev += Event.RunSmartTurn(turnId, version, audioUpTo(turn.size, maxMs = 8000))
                } else if (turn.size - lastPartialChunks >= chunksFor(cfg.partialIntervalMs)) {
                    lastPartialChunks = turn.size
                    ev += Event.Partial(turnId, audioUpTo(turn.size))
                }
                if (turn.size * msPerChunk >= cfg.maxTurnMs) ev += finish(EndReason.MAX_LENGTH, nowNanos)
            }
            State.PAUSED -> {
                turn.add(chunk)
                if (prob >= cfg.speechThreshold) {
                    resumeRun++
                    if (resumeRun >= cfg.resumeChunks) {
                        // voltou a falar: os blocos do "resume" contam como fala
                        state = State.SPEAKING
                        version++ // invalida Smart Turn pendente
                        stProb = null
                        voicedChunks += resumeRun
                        lastVoiceChunkIndex = turn.size - 1
                        lastVoiceNanos = nowNanos
                        silenceRun = 0
                        resumeRun = 0
                        return ev
                    }
                } else {
                    resumeRun = 0
                }
                when {
                    turn.size * msPerChunk >= cfg.maxTurnMs -> ev += finish(EndReason.MAX_LENGTH, nowNanos)
                    else -> decide(nowNanos)?.let { ev += it }
                }
            }
        }
        return ev
    }

    /** Resultado do Smart Turn; ignorado se o turno mudou ou a pessoa voltou a falar. */
    fun onSmartTurn(turnId: Int, version: Int, prob: Float, nowNanos: Long): List<Event> {
        if (turnId != this.turnId || version != this.version || state != State.PAUSED) return emptyList()
        stProb = prob
        lastStProb = prob
        return listOfNotNull(decide(nowNanos))
    }

    private fun decide(nowNanos: Long): Event? {
        val p = stProb
        val silence = silenceMs
        return when {
            p != null && p > threshold && silence >= minEndSilenceMs -> finish(EndReason.SMART_TURN, nowNanos)
            silence >= cfg.maxSilenceMs -> finish(EndReason.SILENCE_TIMEOUT, nowNanos)
            else -> null
        }
    }

    private fun finish(reason: EndReason, nowNanos: Long): Event {
        val id = turnId
        val voicedMs = (voicedChunks * msPerChunk).toLong()
        val end = minOf(turn.size, lastVoiceChunkIndex + 1 + chunksFor(cfg.tailKeepMs))
        val audio = audioUpTo(end)
        val st = lastStProb
        turn.clear()
        preRoll.clear()
        state = State.IDLE
        speechRun = 0
        silenceRun = 0
        resumeRun = 0
        stProb = null
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
