package com.tradutorrt.app.models

import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import kotlin.coroutines.coroutineContext
import kotlinx.coroutines.delay
import kotlinx.coroutines.ensureActive

/**
 * Download HTTP com retomada (header Range sobre o arquivo .part), redirecionamentos manuais
 * (o HF redireciona para a CDN) e verificacao de tamanho + SHA-256 no final.
 */
class Downloader(private val userAgent: String = "TradutorRT/0.1") {

    suspend fun download(file: ModelFile, dest: File, onProgress: (Long, Long) -> Unit) {
        dest.parentFile?.mkdirs()
        val part = File(dest.path + ".part")
        if (part.length() > file.size) part.delete()
        var attempt = 0
        while (part.length() < file.size) {
            coroutineContext.ensureActive()
            try {
                fetch(file, part, onProgress)
            } catch (e: IOException) {
                if (++attempt >= 6) throw e
                delay(1000L * attempt * attempt)
            }
        }
        if (part.length() != file.size) {
            throw IOException("Tamanho inesperado para ${file.localName}: ${part.length()} != ${file.size}")
        }
        val sha = sha256(part)
        if (!sha.equals(file.sha256, ignoreCase = true)) {
            part.delete()
            throw IOException("SHA-256 nao confere para ${file.localName} (arquivo descartado)")
        }
        if (dest.exists()) dest.delete()
        if (!part.renameTo(dest)) throw IOException("Nao foi possivel mover ${part.name}")
    }

    private suspend fun fetch(file: ModelFile, part: File, onProgress: (Long, Long) -> Unit) {
        val start = part.length()
        var url = URL(file.url)
        var conn: HttpURLConnection
        var redirects = 0
        while (true) {
            conn = (url.openConnection() as HttpURLConnection).apply {
                instanceFollowRedirects = false
                connectTimeout = 20_000
                readTimeout = 60_000
                setRequestProperty("User-Agent", userAgent)
                if (start > 0) setRequestProperty("Range", "bytes=$start-")
            }
            val code = conn.responseCode
            if (code in 300..399) {
                val loc = conn.getHeaderField("Location") ?: throw IOException("Redirecionamento sem Location")
                conn.disconnect()
                url = URL(url, loc)
                if (++redirects > 8) throw IOException("Redirecionamentos demais")
                continue
            }
            if (code == 416) { // range ja satisfeito
                conn.disconnect()
                return
            }
            if (code != 200 && code != 206) throw IOException("HTTP $code para ${file.url}")
            break
        }
        val append = conn.responseCode == 206
        RandomAccessFile(part, "rw").use { raf ->
            if (append) raf.seek(start) else raf.setLength(0)
            var done = if (append) start else 0L
            conn.inputStream.use { input ->
                val buf = ByteArray(1 shl 16)
                var lastReport = 0L
                while (true) {
                    coroutineContext.ensureActive()
                    val n = input.read(buf)
                    if (n < 0) break
                    raf.write(buf, 0, n)
                    done += n
                    if (done - lastReport > 512 * 1024) {
                        lastReport = done
                        onProgress(done, file.size)
                    }
                }
            }
            onProgress(done, file.size)
        }
        conn.disconnect()
    }

    companion object {
        fun sha256(f: File): String {
            val md = MessageDigest.getInstance("SHA-256")
            FileInputStream(f).use { inp ->
                val buf = ByteArray(1 shl 20)
                while (true) {
                    val n = inp.read(buf)
                    if (n < 0) break
                    md.update(buf, 0, n)
                }
            }
            return md.digest().joinToString("") { "%02x".format(it) }
        }
    }
}
