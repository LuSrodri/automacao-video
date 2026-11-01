package com.tradutorrt.app.models

import android.content.Context
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class FileProgress(val file: ModelFile, val downloaded: Long, val done: Boolean, val error: String? = null)

data class DownloadState(
    val running: Boolean = false,
    val files: List<FileProgress> = emptyList(),
    val error: String? = null,
) {
    val totalBytes: Long get() = files.sumOf { it.file.size }
    val downloadedBytes: Long get() = files.sumOf { if (it.done) it.file.size else it.downloaded }
    val allDone: Boolean get() = files.isNotEmpty() && files.all { it.done }
}

class ModelRepository(context: Context) {
    val dir: File = File(context.filesDir, "models").apply { mkdirs() }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val downloader = Downloader()
    private var job: Job? = null

    private val _state = MutableStateFlow(DownloadState())
    val state: StateFlow<DownloadState> = _state.asStateFlow()

    fun fileFor(m: ModelFile): File = File(dir, m.localName)

    /** Apaga arquivos de modelos que sairam do catalogo (ex.: o VAD antigo). */
    fun removeObsolete(keep: Collection<ModelFile>) {
        val names = keep.flatMap { listOf(it.localName, it.localName + ".part") }.toSet()
        dir.listFiles()?.filter { it.name !in names }?.forEach { it.delete() }
    }

    /** Considera presente se o arquivo final existe com o tamanho certo (o hash e checado no download). */
    fun isPresent(m: ModelFile): Boolean = fileFor(m).let { it.exists() && it.length() == m.size }

    fun missing(files: List<ModelFile>): List<ModelFile> = files.filterNot { isPresent(it) }

    fun refresh(files: List<ModelFile>) {
        if (_state.value.running) return
        _state.value = DownloadState(files = files.map { snapshot(it) })
    }

    private fun snapshot(m: ModelFile): FileProgress {
        val present = isPresent(m)
        val partial = File(fileFor(m).path + ".part").length()
        return FileProgress(m, if (present) m.size else partial, present)
    }

    fun downloadAll(files: List<ModelFile>) {
        if (job?.isActive == true) return
        job = scope.launch {
            _state.value = DownloadState(running = true, files = files.map { snapshot(it) })
            for (m in files) {
                if (isPresent(m)) continue
                try {
                    downloader.download(m, fileFor(m)) { done, _ ->
                        setProgress(m, done, false)
                    }
                    setProgress(m, m.size, true)
                } catch (e: Exception) {
                    _state.update { s ->
                        s.copy(files = s.files.map { if (it.file.id == m.id) it.copy(error = e.message) else it },
                            error = "${m.title}: ${e.message}")
                    }
                    break
                }
            }
            _state.update { it.copy(running = false) }
        }
    }

    fun cancel() {
        job?.cancel()
        _state.update { it.copy(running = false) }
    }

    private fun setProgress(m: ModelFile, done: Long, finished: Boolean) {
        _state.update { s ->
            s.copy(files = s.files.map { if (it.file.id == m.id) it.copy(downloaded = done, done = finished, error = null) else it })
        }
    }
}
