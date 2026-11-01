// Teste de ponta a ponta no host: roda o pipeline do app sobre um WAV 16 kHz, simulando o microfone
// bloco a bloco (512 amostras), com os mesmos componentes do APK:
//   SileroVad -> TurnDetector -> SmartTurn -> Whisper (LID restrito ao par + ASR) -> Hy-MT2 -> Soprano (en)
//
//   ./tools/build_host_jni.sh
//   ./gradlew :hosttest:run --args="<dir modelos> <wav 16k> [pt en] [saida.wav]"
//
// O diretorio de modelos deve ter os arquivos com os nomes de ModelCatalog (silero_vad.onnx, ...).
import com.tradutorrt.app.audio.SileroVad
import com.tradutorrt.app.audio.SmartTurn
import com.tradutorrt.app.audio.TurnDetector
import com.tradutorrt.app.audio.WhisperFeatures
import com.tradutorrt.app.pipeline.TranslationPrompt
import com.tradutorrt.app.tts.SopranoTextNormalizer
import com.tradutorrt.app.tts.SopranoTokenizer
import com.tradutorrt.app.tts.SopranoTts
import com.tradutorrt.llama.LlamaEngine
import com.tradutorrt.whisper.WhisperContext
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

private fun ms(t0: Long) = (System.nanoTime() - t0) / 1_000_000

// uma thread por modelo, como no app (o ORT deixa estado por thread que estraga o ggml)
private val execs = HashMap<String, java.util.concurrent.ExecutorService>()
private fun <T> on(name: String, f: () -> T): T =
    execs.getOrPut(name) { java.util.concurrent.Executors.newSingleThreadExecutor { r -> Thread(r, name).apply { isDaemon = true } } }
        .submit(java.util.concurrent.Callable { f() }).get()

private fun readWav(f: File): FloatArray {
    val b = ByteBuffer.wrap(f.readBytes()).order(ByteOrder.LITTLE_ENDIAN)
    var pos = 12
    var fmt = 1
    var bits = 16
    while (pos + 8 <= b.limit()) {
        val id = String(ByteArray(4) { b.get(pos + it) })
        val size = b.getInt(pos + 4)
        if (id == "fmt ") {
            fmt = b.getShort(pos + 8).toInt(); bits = b.getShort(pos + 22).toInt()
            require(b.getInt(pos + 12) == 16000) { "WAV precisa ser 16 kHz" }
        }
        if (id == "data") {
            val n = size / (bits / 8)
            return FloatArray(n) { i ->
                if (fmt == 3) b.getFloat(pos + 8 + i * 4) else b.getShort(pos + 8 + i * 2) / 32768f
            }
        }
        pos += 8 + size + (size and 1)
    }
    error("WAV sem chunk data")
}

private fun writeWav(f: File, pcm: FloatArray, rate: Int) {
    RandomAccessFile(f, "rw").use { r ->
        r.setLength(0)
        val bb = ByteBuffer.allocate(44 + pcm.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        bb.put("RIFF".toByteArray()).putInt(36 + pcm.size * 2).put("WAVEfmt ".toByteArray()).putInt(16)
            .putShort(1).putShort(1).putInt(rate).putInt(rate * 2).putShort(2).putShort(16)
            .put("data".toByteArray()).putInt(pcm.size * 2)
        for (v in pcm) bb.putShort((v.coerceIn(-1f, 1f) * 32767).toInt().toShort())
        r.write(bb.array())
    }
}

fun main(args: Array<String>) {
    val dir = File(args[0])
    if (args[1] == "--mt") { // so a traducao, varias chamadas seguidas
        val llama = LlamaEngine.load(File(dir, "Hy-MT2-1.8B-Q4_K_M.gguf").path, 4)
        val mode = args.getOrElse(2) { "" }
        val w = if (mode == "whisper") WhisperContext.load(File(dir, "ggml-base-q5_1.bin").path) else null
        val sop = if (mode.startsWith("ort")) SopranoTts(File(dir, "soprano_backbone_kv_int8.onnx").path, File(dir, "soprano_decoder_fp32.onnx").path,
            SopranoTokenizer(File("app/src/main/assets/soprano_tokenizer.txt").readLines()), 4) else null
        for (s in listOf("I think we should leave earlier tomorrow.", "Sure, that sounds good to me.", "What time do you want to leave?")) {
            val t0 = System.nanoTime()
            println("$s -> ${llama.generate(TranslationPrompt.build(s, "en", "pt"), 64)} (${ms(t0)} ms, ${llama.lastStats})")
            w?.transcribe(FloatArray(32000) { kotlin.math.sin(it * 0.05f) * 0.1f }, 4, "en")
            if (mode == "ort-thread") { val th = Thread { sop?.synthesizeSentence("hello there.") }; th.start(); th.join() }
            else sop?.synthesizeSentence("hello there.")
        }
        return
    }
    val audio = readWav(File(args[1]))
    val langA = args.getOrElse(2) { "pt" }
    val langB = args.getOrElse(3) { "en" }
    val outWav = File(args.getOrElse(4) { "build/hosttest_out.wav" })
    val threads = (Runtime.getRuntime().availableProcessors()).coerceAtMost(4)
    println("threads=$threads, audio=${audio.size / 16000.0}s, par=$langA<->$langB")

    var t = System.nanoTime()
    val vad = on("vad") { SileroVad(File(dir, "silero_vad.onnx").path) }
    val filters = File("app/src/main/assets/whisper_mel_filters_201x80.f32").readBytes()
        .let { val fb = ByteBuffer.wrap(it).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer(); FloatArray(fb.remaining()).also { a -> fb.get(a) } }
    val st = on("st") { SmartTurn(File(dir, "smart-turn-v3.2-cpu.onnx").path, WhisperFeatures(filters), 2) }
    println("carga VAD+SmartTurn: ${ms(t)} ms")
    t = System.nanoTime()
    val whisper = on("asr") { WhisperContext.load(File(dir, "ggml-base-q5_1.bin").path) }
    println("carga Whisper base: ${ms(t)} ms")
    t = System.nanoTime()
    val llama = on("mt") { LlamaEngine.load(File(dir, "Hy-MT2-1.8B-Q4_K_M.gguf").path, threads) }
    println("carga Hy-MT2 Q4_K_M: ${ms(t)} ms")
    t = System.nanoTime()
    val tok = SopranoTokenizer(File("app/src/main/assets/soprano_tokenizer.txt").readLines())
    val soprano = on("tts") { SopranoTts(File(dir, "soprano_backbone_kv_int8.onnx").path, File(dir, "soprano_decoder_fp32.onnx").path, tok, threads) }
    println("carga Soprano: ${ms(t)} ms\n")

    val det = TurnDetector()
    val partialLang = HashMap<Int, String>()
    val tts = ArrayList<FloatArray>()
    var vadTotal = 0L
    var chunks = 0
    val chunkNanos = 32_000_000L
    var i = 0
    while (i + 512 <= audio.size) {
        val chunk = audio.copyOfRange(i, i + 512)
        val now = (i / 512) * chunkNanos  // relogio do audio
        val tv = System.nanoTime()
        val p = on("vad") { vad.process(chunk) }
        vadTotal += System.nanoTime() - tv
        chunks++
        val events = ArrayList(det.process(chunk, p, now))
        while (events.isNotEmpty()) {
            when (val e = events.removeAt(0)) {
                is TurnDetector.Event.SpeechStarted -> println("[%.2fs] fala comecou".format(now / 1e9))
                is TurnDetector.Event.Partial -> {
                    val t0 = System.nanoTime()
                    val cached = partialLang[e.turnId]
                    val tr = on("asr") {
                        whisper.transcribe(e.audio, threads, cached ?: "auto", com.tradutorrt.whisper.PartialParams.audioCtx(e.audio.size),
                            partial = true, maxTokens = com.tradutorrt.whisper.PartialParams.maxTokens(e.audio.size))
                    }!!
                    if (cached == null && (tr.language == langA || tr.language == langB)) partialLang[e.turnId] = tr.language
                    println("[%.2fs]   parcial (%s, %d ms): %s".format(now / 1e9, tr.language, ms(t0), tr.text))
                }
                is TurnDetector.Event.RunSmartTurn -> {
                    val r = on("st") { st.predict(e.audio) }
                    println("[%.2fs]   pausa -> Smart Turn p=%.3f (mel %d ms + onnx %d ms) sobre %.2fs".format(
                        now / 1e9, r.probability, r.featureMs, r.inferMs, e.audio.size / 16000.0))
                    // resultado "chega" depois do tempo de computacao
                    events += det.onSmartTurn(e.turnId, e.version, r.probability, 0.5f, now + (r.featureMs + r.inferMs) * 1_000_000)
                }
                is TurnDetector.Event.TurnDiscarded -> println("[%.2fs]   turno descartado (curto)".format(now / 1e9))
                is TurnDetector.Event.TurnComplete -> {
                    val endpoint = (e.decisionNanos - e.endOfSpeechNanos) / 1_000_000
                    println("[%.2fs] FIM DE TURNO (%s), fim da fala -> decisao: %d ms".format(now / 1e9, e.reason, endpoint))
                    var t0 = System.nanoTime()
                    val probs = on("asr") { whisper.detectLanguage(e.audio, threads) }
                    val src = listOf(langA, langB).maxBy { probs[it] ?: 0f }
                    // como o app com "ASR rapido" ligado (padrao); FAST_ASR=0 usa o contexto cheio de 30 s
                    val fctx = if (System.getenv("FAST_ASR") == "0") 0 else com.tradutorrt.whisper.PartialParams.finalAudioCtx(e.audio.size)
                    val tr = on("asr") { whisper.transcribe(e.audio, threads, src, audioCtx = fctx) }!!
                    val asr = ms(t0)
                    val tgt = if (src == langA) langB else langA
                    t0 = System.nanoTime()
                    val out = TranslationPrompt.clean(on("mt") { llama.generate(TranslationPrompt.build(tr.text, src, tgt), tr.text.length * 2 + 48) }!!)
                    val mt = ms(t0)
                    println("   ASR %d ms  [%s %.0f%%] %s".format(asr, src, 100 * (probs[src] ?: 0f), tr.text))
                    println("   MT  %d ms  [%s] %s   (%s)".format(mt, tgt, out, llama.lastStats))
                    var ttsMs: Long? = null
                    if (tgt == "en") {
                        t0 = System.nanoTime()
                        val sents = SopranoTextNormalizer.sentences(SopranoTextNormalizer.clean(out))
                        for ((k, s) in sents.withIndex()) {
                            val a = on("tts") { soprano.synthesizeSentence(s) }
                            if (k == 0) ttsMs = ms(t0)
                            tts += a
                            println("   TTS Soprano '%s': %.2fs de audio, %s".format(s, a.size / 32000.0, soprano.lastStats))
                        }
                    } else println("   TTS: destino '$tgt' -> TTS do sistema Android (nao disponivel no host)")
                    println("   LATENCIA: turno $endpoint + ASR $asr + MT $mt" + (ttsMs?.let { " + TTS(1o audio) $it = ${endpoint + asr + mt + it} ms" } ?: " = ${endpoint + asr + mt} ms (sem TTS)") + "\n")
                }
            }
        }
        i += 512
    }
    println("VAD: %.2f ms por bloco de 32 ms (%d blocos)".format(vadTotal / 1e6 / chunks, chunks))
    if (tts.isNotEmpty()) {
        val all = FloatArray(tts.sumOf { it.size }).also { var o = 0; for (a in tts) { System.arraycopy(a, 0, it, o, a.size); o += a.size } }
        outWav.parentFile?.mkdirs()
        writeWav(outWav, all, 32000)
        println("voz gerada -> $outWav")
    }
    // segunda traducao igual para medir o reaproveitamento do KV cache
    val t2 = System.nanoTime()
    on("mt") { llama.generate(TranslationPrompt.build("Good morning, everyone.", "en", "pt"), 64) }
    println("MT curta com prefixo em cache: ${ms(t2)} ms ${llama.lastStats}")
    on("mt") { llama.close() }; on("asr") { whisper.close() }; on("tts") { soprano.close() }
    execs.values.forEach { it.shutdown() }
}
