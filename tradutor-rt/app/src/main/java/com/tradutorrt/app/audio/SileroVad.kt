package com.tradutorrt.app.audio

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer
import java.nio.LongBuffer

/**
 * Silero VAD v5 (ONNX). Entrada: 64 amostras de contexto + 512 novas (16 kHz); estado [2,1,128].
 * Mesma logica do OnnxWrapper do repositorio snakers4/silero-vad.
 */
class SileroVad(modelPath: String) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession = env.createSession(modelPath, OrtSession.SessionOptions().apply {
        setIntraOpNumThreads(1)
        setInterOpNumThreads(1)
        setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
    })
    private var state = FloatArray(2 * 128)
    private val context = FloatArray(64)
    private val srTensor = OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(16000)), longArrayOf())

    fun reset() {
        state = FloatArray(2 * 128)
        context.fill(0f)
    }

    /** Probabilidade de fala no bloco de 512 amostras. */
    fun process(chunk: FloatArray): Float {
        require(chunk.size == 512)
        val input = FloatArray(64 + 512)
        System.arraycopy(context, 0, input, 0, 64)
        System.arraycopy(chunk, 0, input, 64, 512)
        System.arraycopy(chunk, 512 - 64, context, 0, 64)
        OnnxTensor.createTensor(env, FloatBuffer.wrap(input), longArrayOf(1, input.size.toLong())).use { x ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(state), longArrayOf(2, 1, 128)).use { st ->
                session.run(mapOf("input" to x, "state" to st, "sr" to srTensor)).use { out ->
                    @Suppress("UNCHECKED_CAST")
                    val prob = (out[0].value as Array<FloatArray>)[0][0]
                    val newState = out[1] as OnnxTensor
                    state = FloatArray(2 * 128).also { newState.floatBuffer.get(it) }
                    return prob
                }
            }
        }
    }

    override fun close() {
        srTensor.close()
        session.close()
    }
}
