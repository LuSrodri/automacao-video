package com.tradutorrt.app

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

object TestUtil {
    fun resourceBytes(name: String): ByteArray =
        requireNotNull(javaClass.getResourceAsStream("/$name")) { "recurso $name" }.use { it.readBytes() }

    fun floats(bytes: ByteArray): FloatArray {
        val fb = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
        return FloatArray(fb.remaining()).also { fb.get(it) }
    }

    fun resourceFloats(name: String) = floats(resourceBytes(name))

    /** Assets do app (testes JVM rodam com o diretorio do modulo como cwd). */
    fun asset(name: String): File = File("src/main/assets/$name")
}
