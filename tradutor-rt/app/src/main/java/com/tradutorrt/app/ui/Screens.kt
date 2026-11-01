package com.tradutorrt.app.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Download
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradutorrt.app.core.AppSettings
import com.tradutorrt.app.core.CpuInfo
import com.tradutorrt.app.core.Languages
import com.tradutorrt.app.core.Mode
import com.tradutorrt.app.models.DownloadState
import com.tradutorrt.app.pipeline.ChatItem
import com.tradutorrt.app.pipeline.EngineState
import com.tradutorrt.app.pipeline.ItemStatus
import com.tradutorrt.app.pipeline.Latencies
import com.tradutorrt.app.pipeline.PipelineState
import java.util.Locale

private fun mb(bytes: Long) = String.format(Locale.US, "%.0f MB", bytes / 1_048_576.0)

// ================================================================================================
// Primeiro uso: download dos modelos

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SetupScreen(state: DownloadState, onDownload: () -> Unit, onCancel: () -> Unit, onOpenSettings: () -> Unit) {
    Scaffold(topBar = {
        TopAppBar(
            title = { Text("Tradutor RT — modelos") },
            actions = { IconButton(onClick = onOpenSettings) { Icon(Icons.Default.Settings, "Configurações") } },
        )
    }) { pad ->
        Column(
            Modifier.padding(pad).padding(16.dp).fillMaxSize(),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                "Tudo roda no aparelho. Na primeira vez é preciso baixar os modelos do Hugging Face " +
                    "(${mb(state.totalBytes)} no total). O download pode ser retomado se cair, e cada arquivo " +
                    "é verificado por tamanho e SHA-256.",
                style = MaterialTheme.typography.bodyMedium,
            )
            val total = state.totalBytes.coerceAtLeast(1)
            LinearProgressIndicator(
                progress = { state.downloadedBytes.toFloat() / total },
                modifier = Modifier.fillMaxWidth().height(8.dp),
            )
            Text("${mb(state.downloadedBytes)} de ${mb(state.totalBytes)}", style = MaterialTheme.typography.labelMedium)
            LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(state.files, key = { it.file.id }) { f ->
                    Column {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(f.file.title, Modifier.weight(1f), fontWeight = FontWeight.Medium)
                            Text(if (f.done) "✓" else mb(f.downloaded) + " / " + mb(f.file.size), style = MaterialTheme.typography.labelSmall)
                        }
                        Text(f.file.repo, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline)
                        LinearProgressIndicator(
                            progress = { if (f.done) 1f else f.downloaded.toFloat() / f.file.size },
                            modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                        )
                        f.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall) }
                    }
                }
            }
            state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            if (state.running) {
                OutlinedButton(onClick = onCancel, modifier = Modifier.fillMaxWidth()) { Text("Pausar download") }
            } else {
                val partial = state.downloadedBytes > 0
                Button(onClick = onDownload, modifier = Modifier.fillMaxWidth().height(52.dp)) {
                    Icon(Icons.Default.Download, null)
                    Spacer(Modifier.width(8.dp))
                    Text(if (partial) "Retomar download" else "Baixar modelos")
                }
            }
        }
    }
}

