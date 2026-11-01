package com.tradutorrt.app.audio

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.nio.FloatBuffer

/** Smart Turn v3.2 (pipecat-ai/smart-turn-v3). Saida ja e a probabilidade (sigmoid) de fim de turno. */
class SmartTurn(modelPath: String, private val features: WhisperFeatures, threads: Int) : AutoCloseable {
    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession = env.createSession(modelPath, OrtSession.SessionOptions().apply {
        setIntraOpNumThreads(threads)
        setInterOpNumThreads(1)
        setExecutionMode(OrtSession.SessionOptions.ExecutionMode.SEQUENTIAL)
        setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
    })

    data class Result(val probability: Float, val featureMs: Long, val inferMs: Long)

    fun predict(audio: FloatArray): Result {
        val t0 = System.nanoTime()
        val feat = features.compute(audio)
        val t1 = System.nanoTime()
        val p = OnnxTensor.createTensor(env, FloatBuffer.wrap(feat), longArrayOf(1, 80, 800)).use { x ->
            session.run(mapOf("input_features" to x)).use { out ->
                @Suppress("UNCHECKED_CAST")
                (out[0].value as Array<FloatArray>)[0][0]
            }
        }
        val t2 = System.nanoTime()
        return Result(p, (t1 - t0) / 1_000_000, (t2 - t1) / 1_000_000)
    }

    override fun close() = session.close()
}
