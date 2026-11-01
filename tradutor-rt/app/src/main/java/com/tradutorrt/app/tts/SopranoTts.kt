package com.tradutorrt.app.tts

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.nio.LongBuffer

/**
 * Soprano-1.1-80M em ONNX Runtime (somente ingles).
 * Backbone Qwen3 com KV cache explicito -> estados ocultos -> decoder Vocos (com ISTFT) -> audio 32 kHz.
 * Decodificacao gulosa com repetition_penalty=1.2 (o padrao do Soprano usa temperature=0).
 * Para cada token gerado (exceto o [STOP]) guarda o estado oculto da posicao que o previu,
 * exatamente como SopranoTTS.infer() faz com o backend transformers.
 */
class SopranoTts(
    backbonePath: String,
    decoderPath: String,
    private val tokenizer: SopranoTokenizer,
    threads: Int,
) : AutoCloseable {
    companion object {
        const val SAMPLE_RATE = 32000
        private const val LAYERS = 17
        private const val HEAD_DIM = 128
        private const val HIDDEN = 512
        private const val VOCAB = 8192
        private const val REP_PENALTY = 1.2f
    }

    private val env = OrtEnvironment.getEnvironment()
    private fun opts(threads: Int) = OrtSession.SessionOptions().apply {
        setIntraOpNumThreads(threads)
        setInterOpNumThreads(1)
        setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL)
        setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
    }
    private val backbone = env.createSession(backbonePath, opts(threads))
    private val decoder = env.createSession(decoderPath, opts(threads))

    data class Stats(val tokens: Int, val backboneMs: Long, val decoderMs: Long)

    var lastStats: Stats? = null
        private set

    /** Sintetiza uma frase (ja normalizada). */
    fun synthesizeSentence(clean: String): FloatArray {
        val prompt = tokenizer.encodePrompt(clean)
        val maxNew = minOf(512, 3 * clean.length + 30)
        val t0 = System.nanoTime()
        val hidden = generateHidden(prompt, maxNew)
        val t1 = System.nanoTime()
        if (hidden.isEmpty()) return FloatArray(0)
        val T = hidden.size
        val x = FloatArray(HIDDEN * T)
        for (t in 0 until T) for (c in 0 until HIDDEN) x[c * T + t] = hidden[t][c]
        val audio = OnnxTensor.createTensor(env, FloatBuffer.wrap(x), longArrayOf(1, HIDDEN.toLong(), T.toLong())).use { inp ->
            decoder.run(mapOf("hidden_states" to inp)).use { out ->
                val buf = (out[0] as OnnxTensor).floatBuffer
                FloatArray(buf.remaining()).also { buf.get(it) }
            }
        }
        val t2 = System.nanoTime()
        lastStats = Stats(T, (t1 - t0) / 1_000_000, (t2 - t1) / 1_000_000)
        return audio
    }

    private fun generateHidden(prompt: IntArray, maxNew: Int): List<FloatArray> {
        val seen = BooleanArray(VOCAB)
        prompt.forEach { seen[it] = true }
        val hidden = ArrayList<FloatArray>()
        val emptyKv = FloatBuffer.allocate(0)
        val pastTensors = HashMap<String, OnnxTensor>()
        for (i in 0 until LAYERS) for (kv in arrayOf("key", "value")) {
            pastTensors["past_key_values.$i.$kv"] = OnnxTensor.createTensor(env, emptyKv, longArrayOf(1, 1, 0, HEAD_DIM.toLong()))
        }
        var owned: OrtSession.Result? = null // resultado anterior cujos "present" estao sendo usados como "past"
        var cur = prompt.map { it.toLong() }.toLongArray()
        var past = 0
        val logits = FloatArray(VOCAB)
        try {
            for (step in 0 until maxNew) {
                val s = cur.size
                val ids = OnnxTensor.createTensor(env, LongBuffer.wrap(cur), longArrayOf(1, s.toLong()))
                val mask = OnnxTensor.createTensor(env, LongBuffer.wrap(LongArray(past + s) { 1 }), longArrayOf(1, (past + s).toLong()))
                val pos = OnnxTensor.createTensor(env, LongBuffer.wrap(LongArray(s) { (past + it).toLong() }), longArrayOf(1, s.toLong()))
                val inputs = HashMap<String, OnnxTensor>(pastTensors)
                inputs["input_ids"] = ids
                inputs["attention_mask"] = mask
                inputs["position_ids"] = pos
                val res = backbone.run(inputs)
                ids.close(); mask.close(); pos.close()
                if (owned == null) pastTensors.values.forEach { it.close() } else owned.close()
                owned = res
                for (i in 0 until LAYERS) for (kv in arrayOf("key", "value")) {
                    pastTensors["past_key_values.$i.$kv"] = res.get("present.$i.$kv").get() as OnnxTensor
                }
                past += s

                val lb = (res.get("logits").get() as OnnxTensor).floatBuffer
                lb.position((s - 1) * VOCAB)
                lb.get(logits, 0, VOCAB)
                var best = 0
                var bestV = Float.NEGATIVE_INFINITY
                for (v in 0 until VOCAB) {
                    var l = logits[v]
                    if (seen[v]) l = if (l < 0) l * REP_PENALTY else l / REP_PENALTY
                    if (l > bestV) {
                        bestV = l; best = v
                    }
                }
                if (best == SopranoTokenizer.STOP) break
                val hb = (res.get("last_hidden_state").get() as OnnxTensor).floatBuffer
                hb.position((s - 1) * HIDDEN)
                hidden.add(FloatArray(HIDDEN).also { hb.get(it) })
                seen[best] = true
                cur = longArrayOf(best.toLong())
            }
        } finally {
            if (owned == null) pastTensors.values.forEach { it.close() } else owned.close()
        }
        return hidden
    }

    override fun close() {
        backbone.close()
        decoder.close()
    }
}
