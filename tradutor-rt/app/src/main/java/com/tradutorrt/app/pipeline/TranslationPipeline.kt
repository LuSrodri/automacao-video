package com.tradutorrt.app.pipeline

import android.content.Context
import android.util.Log
import com.tradutorrt.app.audio.AudioCapture
import com.tradutorrt.app.audio.SileroVad
import com.tradutorrt.app.audio.SmartTurn
import com.tradutorrt.app.audio.TurnDetector
import com.tradutorrt.app.audio.WhisperFeatures
import com.tradutorrt.app.core.AppSettings
import com.tradutorrt.app.core.CpuInfo
import com.tradutorrt.app.core.Mode
import com.tradutorrt.app.core.SettingsStore
import com.tradutorrt.app.models.ModelCatalog
import com.tradutorrt.app.models.ModelRepository
import com.tradutorrt.app.tts.AudioPlayer
import com.tradutorrt.app.tts.SopranoTextNormalizer
import com.tradutorrt.app.tts.SopranoTokenizer
import com.tradutorrt.app.tts.SopranoTts
import com.tradutorrt.app.tts.SystemTts
import com.tradutorrt.llama.LlamaEngine
import com.tradutorrt.whisper.PartialParams
import com.tradutorrt.whisper.WhisperContext
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExecutorCoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.asCoroutineDispatcher
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Microfone -> Silero VAD -> Smart Turn -> Whisper (LID + ASR) -> Hy-MT2 -> Soprano / TTS do sistema.
 *
 * Cada modelo roda numa thread propria (dispatchers single-thread), conectados por canais.
 * Isso nao e so organizacao: no teste de host, rodar o Soprano (ONNX Runtime) e depois o llama.cpp NA MESMA
 * thread fez o Hy-MT2 gerar lixo; em threads separadas, nao. E estado por thread deixado pelo ORT
 * (provavelmente flags de FPU/denormais). Por isso ORT (VAD, Smart Turn, Soprano) nunca divide thread
 * com whisper/llama.
 *   audio ──► vad (VAD + TurnDetector) ──► smart-turn ──┐
 *                       ▲───────── resultado ───────────┘
 *                       ├── parciais (conflated) ──► asr ──► mt ──► tts ──► AudioPlayer
 *                       └── turnos finais ─────────►
 * A UI so observa [state]; nada aqui roda na main thread.
 */
class TranslationPipeline(
    private val context: Context,
    private val settings: SettingsStore,
    private val repo: ModelRepository,
) {
    private val tag = "Pipeline"

    private fun thread(name: String): ExecutorCoroutineDispatcher =
        Executors.newSingleThreadExecutor { r -> Thread(r, name).apply { isDaemon = true } }.asCoroutineDispatcher()

    private val audioDispatcher = thread("audio-capture")
    private val vadDispatcher = thread("vad")
    private val smartTurnDispatcher = thread("smart-turn")
    private val asrDispatcher = thread("asr-whisper")
    private val mtDispatcher = thread("mt-llama")
    private val ttsDispatcher = thread("tts")

    private val scope = CoroutineScope(SupervisorJob())
    private val _state = MutableStateFlow(PipelineState())
    val state: StateFlow<PipelineState> = _state.asStateFlow()

    // ---- modelos (cada um so e tocado pela sua thread)
    private var vad: SileroVad? = null
    private var smartTurn: SmartTurn? = null
    private var whisper: WhisperContext? = null
    private var whisperPath: String? = null
    private var llama: LlamaEngine? = null
    private var soprano: SopranoTts? = null
    private var systemTts: SystemTts? = null
    private var player: AudioPlayer? = null

    // ---- canais
    private sealed class VadInput {
        class Audio(val chunk: FloatArray, val t: Long) : VadInput()
        class StResult(val turnId: Int, val version: Int, val prob: Float, val ms: Long) : VadInput()
    }

    private class FinalTurn(val id: Long, val ev: TurnDetector.Event.TurnComplete, val smartTurnMs: Long?)
    private class PartialTurn(val turnId: Int, val audio: FloatArray)
    private class MtJob(val id: Long, val text: String, val src: String, val tgt: String, val endOfSpeech: Long)
    private class TtsJob(val id: Long, val text: String, val lang: String, val endOfSpeech: Long)

    private var vadInput = Channel<VadInput>(Channel.UNLIMITED)
    private val finals = Channel<FinalTurn>(Channel.UNLIMITED)
    private val partials = Channel<PartialTurn>(Channel.CONFLATED)
    private val mtJobs = Channel<MtJob>(Channel.UNLIMITED)
    private val ttsJobs = Channel<TtsJob>(Channel.UNLIMITED)

    private var listenJobs = emptyList<Job>()
    private var workersStarted = false
    private val ids = AtomicLong(0)
    private val replayAudio = ConcurrentHashMap<Long, FloatArray>()

    // half-duplex: o microfone e ignorado enquanto o app fala
    @Volatile private var outputBusy = false
    @Volatile private var muteUntil = 0L
    @Volatile private var lastSmartTurnMs: Long? = null
    @Volatile private var lastFinalTurnId = 0
    private val partialLang = ConcurrentHashMap<Int, String>()

    private val threads get() = CpuInfo.bigCores

    // =============================================================================================
    // ciclo de vida

    fun start() {
        if (_state.value.engine == EngineState.LISTENING || _state.value.engine == EngineState.LOADING) return
        _state.update { it.copy(engine = EngineState.LOADING, error = null, status = "Carregando modelos…") }
        if (!workersStarted) {
            workersStarted = true
            scope.launch(asrDispatcher) { asrWorker() }
            scope.launch(mtDispatcher) { mtWorker() }
            scope.launch(ttsDispatcher) { ttsWorker() }
        }
        scope.launch {
            val s = settings.value
            // carga em paralelo, cada modelo na sua thread
            val required = listOf(
                loadOn(vadDispatcher, "VAD") { if (vad == null) vad = SileroVad(path(ModelCatalog.sileroVad)) },
                loadOn(smartTurnDispatcher, "Smart Turn") {
                    if (smartTurn == null) {
                        val filters = loadFloatAsset("whisper_mel_filters_201x80.f32")
                        smartTurn = SmartTurn(path(ModelCatalog.smartTurn), WhisperFeatures(filters), minOf(2, threads))
                    }
                },
                loadOn(asrDispatcher, "Whisper") { ensureWhisper(s) },
            )
            // o LLM carrega uma vez so (em paralelo; a primeira traducao espera na fila da thread de MT)
            loadOn(mtDispatcher, "Hy-MT2") { ensureLlama() }
            loadOn(ttsDispatcher, "TTS") { ensureTts(s) }
            val errors = required.mapNotNull { it.await() }
            if (errors.isEmpty()) startListening()
            else _state.update { it.copy(engine = EngineState.ERROR, error = errors.joinToString("\n"), status = "Erro") }
        }
    }

    /** Carrega algo na thread do modelo; devolve a mensagem de erro (ou null) sem derrubar o pipeline. */
    private fun loadOn(d: ExecutorCoroutineDispatcher, name: String, block: () -> Unit) = scope.async(d) {
        try {
            block(); null
        } catch (e: Throwable) {
            Log.e(tag, "load $name", e)
            val msg = "$name: ${e.message ?: e.toString()}"
            _state.update { it.copy(error = msg) }
            msg
        }
    }

    fun stop() {
        scope.launch {
            listenJobs.forEach { it.cancelAndJoin() }
            listenJobs = emptyList()
            _state.update { it.copy(engine = EngineState.STOPPED, speaking = false, vadProb = 0f, partial = "", status = "Parado") }
        }
    }

    fun clearHistory() {
        replayAudio.clear()
        _state.update { it.copy(items = emptyList()) }
    }

    private fun startListening() {
        vadInput = Channel(Channel.UNLIMITED)
        val detector = TurnDetector()
        val input = vadInput
        val capture = scope.launch(audioDispatcher) {
            try {
                AudioCapture().run { chunk, t -> input.send(VadInput.Audio(chunk, t)) }
            } catch (e: Throwable) {
                if (e !is kotlinx.coroutines.CancellationException) {
                    Log.e(tag, "capture", e)
                    _state.update { it.copy(engine = EngineState.ERROR, error = "Microfone: ${e.message}") }
                }
            }
        }
        val vadLoop = scope.launch(vadDispatcher) { vadLoop(detector, input) }
        listenJobs = listOf(capture, vadLoop)
        _state.update { it.copy(engine = EngineState.LISTENING, status = "Ouvindo", error = null) }
    }

    // =============================================================================================
    // VAD + fim de turno (thread "vad")

    private suspend fun vadLoop(detector: TurnDetector, input: Channel<VadInput>) {
        val v = vad!!
        var wasMuted = false
        var uiCounter = 0
        for (msg in input) {
            when (msg) {
                is VadInput.Audio -> {
                    val muted = outputBusy || System.nanoTime() < muteUntil
                    if (muted) {
                        if (!wasMuted) {
                            detector.reset(); v.reset()
                            _state.update { it.copy(speaking = false, vadProb = 0f, partial = "") }
                        }
                        wasMuted = true
                        continue
                    }
                    wasMuted = false
                    val prob = v.process(msg.chunk)
                    val events = detector.process(msg.chunk, prob, msg.t)
                    if (++uiCounter % 3 == 0) {
                        val speaking = detector.state != TurnDetector.State.IDLE
                        _state.update { it.copy(vadProb = prob, speaking = speaking) }
                    }
                    handleEvents(events, input)
                }
                is VadInput.StResult -> {
                    lastSmartTurnMs = msg.ms
                    val thr = settings.value.smartTurnThreshold
                    handleEvents(detector.onSmartTurn(msg.turnId, msg.version, msg.prob, thr, System.nanoTime()), input)
                }
            }
        }
    }

    private suspend fun handleEvents(events: List<TurnDetector.Event>, input: Channel<VadInput>) {
        for (e in events) when (e) {
            is TurnDetector.Event.SpeechStarted -> _state.update { it.copy(speaking = true, partial = "") }
            is TurnDetector.Event.RunSmartTurn -> scope.launch(smartTurnDispatcher) {
                val r = smartTurn!!.predict(e.audio)
                Log.d(tag, "smart turn p=%.3f (%d+%d ms)".format(r.probability, r.featureMs, r.inferMs))
                input.trySend(VadInput.StResult(e.turnId, e.version, r.probability, r.featureMs + r.inferMs))
            }
            is TurnDetector.Event.Partial -> if (settings.value.partialTranscripts) partials.trySend(PartialTurn(e.turnId, e.audio))
            is TurnDetector.Event.TurnComplete -> {
                lastFinalTurnId = e.turnId
                val id = ids.incrementAndGet()
                val st = if (e.reason == TurnDetector.EndReason.SMART_TURN) lastSmartTurnMs else null
                addItem(
                    ChatItem(
                        id, status = ItemStatus.TRANSCRIBING,
                        endReason = when (e.reason) {
                            TurnDetector.EndReason.SMART_TURN -> "Smart Turn %.2f".format(e.smartTurnProb ?: 0f)
                            TurnDetector.EndReason.SILENCE_TIMEOUT -> "silêncio"
                            TurnDetector.EndReason.MAX_LENGTH -> "tamanho máx."
                        },
                        latencies = Latencies(endpointMs = (e.decisionNanos - e.endOfSpeechNanos) / 1_000_000, smartTurnMs = st),
                    ),
                )
                _state.update { it.copy(speaking = false, partial = "") }
                finals.send(FinalTurn(id, e, st))
            }
            is TurnDetector.Event.TurnDiscarded -> _state.update { it.copy(speaking = false, partial = "") }
        }
    }

    // =============================================================================================
    // ASR (thread "asr-whisper"): finais tem prioridade sobre parciais

    private suspend fun asrWorker() {
        while (true) {
            select {
                finals.onReceive { runCatching { handleFinal(it) }.onFailure { e -> fail(it.id, e) } }
                partials.onReceive { runCatching { handlePartial(it) }.onFailure { e -> Log.w(tag, "partial", e) } }
            }
        }
    }

    private fun ensureWhisper(s: AppSettings) {
        val p = path(ModelCatalog.whisper(s.whisperSize))
        if (whisper != null && whisperPath == p) return
        whisper?.close()
        whisper = null
        _state.update { it.copy(status = "Carregando Whisper ${s.whisperSize.label}…") }
        whisper = WhisperContext.load(p)
        whisperPath = p
    }

    private fun chooseLanguage(probs: Map<String, Float>, s: AppSettings): Pair<String, Float> = when (s.mode) {
        Mode.CONVERSATION -> listOf(s.langA, s.langB).map { it to (probs[it] ?: 0f) }.maxBy { it.second }
        Mode.LISTEN -> probs.maxBy { it.value }.toPair()
    }

    private fun handlePartial(p: PartialTurn) {
        if (p.turnId <= lastFinalTurnId) return
        val s = settings.value
        ensureWhisper(s)
        val w = whisper!!
        // Sem deteccao de idioma separada (custaria um encoder de 30 s): a primeira parcial do turno usa
        // "auto" com contexto reduzido e o idioma fica guardado para as seguintes. O turno final refaz a LID.
        val cached = partialLang[p.turnId]
        val tr = w.transcribe(
            p.audio, threads, cached ?: "auto",
            audioCtx = PartialParams.audioCtx(p.audio.size), partial = true, maxTokens = PartialParams.maxTokens(p.audio.size),
        ) ?: return
        val allowed = s.mode == Mode.LISTEN || tr.language == s.langA || tr.language == s.langB
        if (cached == null && allowed) partialLang[p.turnId] = tr.language
        if (p.turnId <= lastFinalTurnId) return
        _state.update { it.copy(partial = tr.text, partialLang = tr.language) }
    }

    private fun isNonSpeech(text: String): Boolean {
        val t = text.trim()
        if (t.isEmpty()) return true
        if (Regex("^[\\[(].*[\\])]$").matches(t)) return true // [BLANK_AUDIO], (música) ...
        return t.all { !it.isLetterOrDigit() }
    }

    private suspend fun handleFinal(f: FinalTurn) {
        val s = settings.value
        ensureWhisper(s)
        val w = whisper!!
        val t0 = System.nanoTime()
        val probs = w.detectLanguage(f.ev.audio, threads)
        val (src, prob) = chooseLanguage(probs, s)
        val ctx = if (s.fastAsr) PartialParams.finalAudioCtx(f.ev.audio.size) else 0
        val tr = w.transcribe(f.ev.audio, threads, src, audioCtx = ctx) ?: error("Whisper falhou")
        val asrMs = (System.nanoTime() - t0) / 1_000_000
        partialLang.clear()
        if (isNonSpeech(tr.text)) {
            removeItem(f.id)
            return
        }
        val tgt = when (s.mode) {
            Mode.CONVERSATION -> if (src == s.langA) s.langB else s.langA
            Mode.LISTEN -> s.listenTarget
        }
        updateItem(f.id) {
            it.copy(
                original = tr.text, sourceLang = src, sourceLangProb = prob, targetLang = tgt,
                status = ItemStatus.TRANSLATING, latencies = it.latencies.copy(asrMs = asrMs),
            )
        }
        mtJobs.send(MtJob(f.id, tr.text, src, tgt, f.ev.endOfSpeechNanos))
    }

    // =============================================================================================
    // MT (thread "mt-llama")

    private fun ensureLlama() {
        if (llama != null) return
        _state.update { if (it.engine == EngineState.LOADING) it.copy(status = "Carregando Hy-MT2…") else it }
        llama = LlamaEngine.load(path(ModelCatalog.hyMt), threads, nCtx = 2048)
    }

    private suspend fun mtWorker() {
        for (job in mtJobs) {
            try {
                val t0 = System.nanoTime()
                val translation = if (job.src == job.tgt) {
                    job.text
                } else {
                    ensureLlama()
                    val prompt = TranslationPrompt.build(job.text, job.src, job.tgt)
                    val out = llama!!.generate(prompt, maxTokens = minOf(512, job.text.length * 2 + 48)) ?: error("LLM falhou")
                    Log.d(tag, "mt stats ${llama!!.lastStats}")
                    TranslationPrompt.clean(out)
                }
                val mtMs = (System.nanoTime() - t0) / 1_000_000
                val voice = settings.value.voiceEnabled && translation.isNotBlank()
                updateItem(job.id) {
                    it.copy(
                        translation = translation,
                        status = if (voice) ItemStatus.SPEAKING else ItemStatus.DONE,
                        latencies = it.latencies.copy(mtMs = mtMs),
                    )
                }
                if (voice) ttsJobs.send(TtsJob(job.id, translation, job.tgt, job.endOfSpeech)) else publishLatencies(job.id)
            } catch (e: Throwable) {
                fail(job.id, e)
            }
        }
    }

    // =============================================================================================
    // TTS (thread "tts")

    private fun ensureTts(s: AppSettings) {
        if (player == null) {
            player = AudioPlayer(SopranoTts.SAMPLE_RATE).also { p -> p.onIdle = { onOutputIdle() } }
        }
        if (systemTts == null) {
            systemTts = SystemTts(context).also { t -> t.onIdle = { onOutputIdle() } }
        }
        val needSoprano = s.voiceEnabled && s.sopranoForEnglish
        if (needSoprano && soprano == null && ModelCatalog.soprano.all { repo.isPresent(it) }) {
            val tok = SopranoTokenizer(context.assets.open("soprano_tokenizer.txt").bufferedReader().readLines())
            soprano = SopranoTts(path(ModelCatalog.sopranoBackbone), path(ModelCatalog.sopranoDecoder), tok, threads)
        }
    }

    private fun onOutputIdle() {
        if (player?.isBusy == true || systemTts?.isBusy == true) return
        muteUntil = System.nanoTime() + 300_000_000L
        outputBusy = false
    }

    private suspend fun ttsWorker() {
        for (job in ttsJobs) {
            try {
                val s = settings.value
                ensureTts(s)
                val t0 = System.nanoTime()
                val useSoprano = job.lang == "en" && s.sopranoForEnglish && soprano != null
                var firstAudio = 0L
                if (useSoprano) {
                    val all = ArrayList<FloatArray>()
                    val sentences = SopranoTextNormalizer.sentences(SopranoTextNormalizer.clean(job.text))
                    for (sentence in sentences) {
                        val audio = soprano!!.synthesizeSentence(sentence)
                        Log.d(tag, "soprano '$sentence' ${soprano!!.lastStats}")
                        if (audio.isEmpty()) continue
                        if (firstAudio == 0L) {
                            firstAudio = System.nanoTime()
                            outputBusy = true
                        }
                        player!!.enqueue(audio)
                        all += audio
                    }
                    replayAudio[job.id] = concat(all)
                } else {
                    val started = CompletableDeferred<Long>()
                    systemTts!!.onStart = { started.complete(System.nanoTime()) }
                    outputBusy = true
                    if (!systemTts!!.speak(job.text, job.lang)) {
                        outputBusy = false
                        updateItem(job.id) { it.copy(ttsEngine = "sem voz para ${job.lang}") }
                    } else {
                        firstAudio = withTimeoutOrNull(5000) { started.await() } ?: System.nanoTime()
                    }
                }
                val ttsMs = if (firstAudio > 0) (firstAudio - t0) / 1_000_000 else null
                val total = if (firstAudio > 0) (firstAudio - job.endOfSpeech) / 1_000_000 else null
                updateItem(job.id) {
                    it.copy(
                        status = ItemStatus.DONE,
                        ttsEngine = if (it.ttsEngine.isNotEmpty()) it.ttsEngine else if (useSoprano) "Soprano" else "TTS do sistema",
                        latencies = it.latencies.copy(ttsMs = ttsMs, totalMs = total),
                    )
                }
                publishLatencies(job.id)
            } catch (e: Throwable) {
                outputBusy = false
                fail(job.id, e)
            }
        }
    }

    /** Repete o audio de uma mensagem (Soprano: audio guardado; sistema: fala de novo). */
    fun replay(id: Long) {
        val item = _state.value.items.firstOrNull { it.id == id } ?: return
        scope.launch(ttsDispatcher) {
            ensureTts(settings.value)
            val audio = replayAudio[id]
            outputBusy = true
            if (audio != null && audio.isNotEmpty()) {
                player!!.enqueue(audio)
            } else if (!systemTts!!.speak(item.translation, item.targetLang)) {
                outputBusy = false
            }
        }
    }

    fun stopSpeaking() {
        player?.stop()
        systemTts?.stop()
    }

    // =============================================================================================
    // utilitarios

    private fun path(m: com.tradutorrt.app.models.ModelFile): String {
        val f = repo.fileFor(m)
        check(f.exists()) { "Modelo ausente: ${m.title}" }
        return f.absolutePath
    }

    private fun loadFloatAsset(name: String): FloatArray {
        val bytes = context.assets.open(name).use { it.readBytes() }
        val fb = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        return FloatArray(fb.remaining()).also { fb.get(it) }
    }

    private fun concat(parts: List<FloatArray>): FloatArray {
        val out = FloatArray(parts.sumOf { it.size })
        var o = 0
        for (p in parts) {
            System.arraycopy(p, 0, out, o, p.size); o += p.size
        }
        return out
    }

    private fun addItem(item: ChatItem) = _state.update { it.copy(items = it.items + item) }
    private fun removeItem(id: Long) = _state.update { s -> s.copy(items = s.items.filterNot { it.id == id }) }
    private fun updateItem(id: Long, f: (ChatItem) -> ChatItem) =
        _state.update { s -> s.copy(items = s.items.map { if (it.id == id) f(it) else it }) }

    private fun publishLatencies(id: Long) {
        val item = _state.value.items.firstOrNull { it.id == id } ?: return
        _state.update { it.copy(lastLatencies = item.latencies) }
        Log.i(tag, "latencias #$id: ${item.latencies}")
    }

    private fun fail(id: Long, e: Throwable) {
        Log.e(tag, "item $id", e)
        updateItem(id) { it.copy(status = ItemStatus.ERROR, error = e.message ?: e.toString()) }
    }

    suspend fun warmup() = withContext(mtDispatcher) { ensureLlama() }
}
