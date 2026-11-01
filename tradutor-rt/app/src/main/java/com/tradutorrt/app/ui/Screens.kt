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

// ================================================================================================
// Tela principal

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    state: PipelineState,
    settings: AppSettings,
    onToggle: () -> Unit,
    onReplay: (Long) -> Unit,
    onStopSpeaking: () -> Unit,
    onOpenSettings: () -> Unit,
    onSwap: () -> Unit,
) {
    Scaffold(topBar = {
        TopAppBar(
            title = {
                Column {
                    Text("Tradutor RT", fontWeight = FontWeight.Bold)
                    val sub = when (settings.mode) {
                        Mode.CONVERSATION -> "Conversa: ${Languages.displayName(settings.langA)} ↔ ${Languages.displayName(settings.langB)}"
                        Mode.LISTEN -> "Ouvir: qualquer idioma → ${Languages.displayName(settings.listenTarget)}"
                    }
                    Text(sub, style = MaterialTheme.typography.labelMedium)
                }
            },
            actions = {
                if (settings.mode == Mode.CONVERSATION) IconButton(onClick = onSwap) { Icon(Icons.Default.SwapHoriz, "Inverter") }
                IconButton(onClick = onStopSpeaking) { Icon(Icons.AutoMirrored.Filled.VolumeOff, "Parar voz") }
                IconButton(onClick = onOpenSettings) { Icon(Icons.Default.Settings, "Configurações") }
            },
        )
    }) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            LatencyBar(state.lastLatencies)
            val listState = rememberLazyListState()
            val count = state.items.size + if (state.partial.isNotEmpty() || state.speaking) 1 else 0
            LaunchedEffect(count, state.items.lastOrNull()?.translation, state.partial) {
                if (count > 0) listState.animateScrollToItem(count - 1)
            }
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth().padding(horizontal = 12.dp),
                state = listState,
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (state.items.isEmpty() && !state.speaking) {
                    item {
                        Text(
                            "Toque no microfone e fale. O idioma é detectado automaticamente pelo Whisper; " +
                                "quando o Smart Turn entende que você terminou, a frase é traduzida e falada.",
                            Modifier.padding(24.dp), textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.outline,
                        )
                    }
                }
                items(state.items, key = { it.id }) { ChatBubble(it, settings, onReplay) }
                if (state.partial.isNotEmpty() || state.speaking) {
                    item(key = "partial") { PartialBubble(state.partial, state.partialLang) }
                }
            }
            BottomControls(state, onToggle)
        }
    }
}

@Composable
private fun LatencyBar(l: Latencies) {
    fun f(v: Long?) = v?.let { "$it" } ?: "–"
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 6.dp)) {
            Text(
                "VAD/turno ${f(l.endpointMs)} ms" + (l.smartTurnMs?.let { " (ST $it)" } ?: "") +
                    " · ASR ${f(l.asrMs)} · MT ${f(l.mtMs)} · TTS ${f(l.ttsMs)} ms",
                style = MaterialTheme.typography.labelMedium,
            )
            Text(
                "Total fim da fala → voz: ${f(l.totalMs)} ms · ${CpuInfo.bigCores} núcleos grandes",
                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline,
            )
        }
    }
}

@Composable
private fun ChatBubble(item: ChatItem, settings: AppSettings, onReplay: (Long) -> Unit) {
    // na conversa, a fala no idioma B fica alinhada a direita (como "o outro lado")
    val right = settings.mode == Mode.CONVERSATION && item.sourceLang == settings.langB
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (right) Arrangement.End else Arrangement.Start) {
        Card(
            modifier = Modifier.widthIn(max = 340.dp),
            colors = CardDefaults.cardColors(
                containerColor = if (right) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.primaryContainer,
            ),
            shape = RoundedCornerShape(16.dp),
        ) {
            Column(Modifier.padding(12.dp)) {
                if (item.sourceLang.isNotEmpty()) {
                    Text(
                        "${Languages.displayName(item.sourceLang)} (${item.sourceLang}, ${(item.sourceLangProb * 100).toInt()}%) → " +
                            Languages.displayName(item.targetLang),
                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline,
                    )
                }
                if (item.original.isNotEmpty()) Text(item.original, style = MaterialTheme.typography.bodyMedium)
                else if (item.status == ItemStatus.TRANSCRIBING) Text("transcrevendo…", fontStyle = FontStyle.Italic)
                Spacer(Modifier.height(6.dp))
                when {
                    item.translation.isNotEmpty() -> Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(item.translation, Modifier.weight(1f, fill = false), style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        IconButton(onClick = { onReplay(item.id) }, modifier = Modifier.size(36.dp)) {
                            Icon(Icons.AutoMirrored.Filled.VolumeUp, "Repetir áudio")
                        }
                    }
                    item.status == ItemStatus.TRANSLATING -> Text("traduzindo…", fontStyle = FontStyle.Italic)
                }
                item.error?.let { Text("Erro: $it", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall) }
                val l = item.latencies
                val parts = listOfNotNull(
                    l.endpointMs?.let { "turno ${it}ms" }, l.asrMs?.let { "ASR ${it}ms" }, l.mtMs?.let { "MT ${it}ms" },
                    l.ttsMs?.let { "TTS ${it}ms" }, l.totalMs?.let { "total ${it}ms" },
                )
                if (parts.isNotEmpty()) {
                    Text(
                        parts.joinToString(" · ") + listOf(item.endReason, item.ttsEngine).filter { it.isNotEmpty() }
                            .joinToString(" · ", prefix = " · "),
                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline, fontSize = 10.sp,
                    )
                }
            }
        }
    }
}

@Composable
private fun PartialBubble(text: String, lang: String) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant), shape = RoundedCornerShape(16.dp)) {
        Column(Modifier.padding(12.dp)) {
            Text(if (lang.isNotEmpty()) "ouvindo… ($lang)" else "ouvindo…", style = MaterialTheme.typography.labelSmall)
            if (text.isNotEmpty()) Text(text, fontStyle = FontStyle.Italic)
        }
    }
}

@Composable
private fun BottomControls(state: PipelineState, onToggle: () -> Unit) {
    val listening = state.engine == EngineState.LISTENING
    val loading = state.engine == EngineState.LOADING
    val level by animateFloatAsState(if (listening) state.vadProb else 0f, label = "vad")
    val color by animateColorAsState(
        when {
            listening && state.speaking -> Color(0xFFE53935)
            listening -> MaterialTheme.colorScheme.primary
            else -> MaterialTheme.colorScheme.secondary
        },
        label = "btn",
    )
    Column(
        Modifier.fillMaxWidth().padding(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall) }
        Text(
            when {
                loading -> state.status
                listening && state.speaking -> "Falando…"
                listening -> "Ouvindo"
                else -> "Toque para começar"
            },
            style = MaterialTheme.typography.labelLarge,
        )
        Spacer(Modifier.height(8.dp))
        Box(contentAlignment = Alignment.Center) {
            Box(
                Modifier.size((96 + 40 * level).dp).clip(CircleShape)
                    .background(color.copy(alpha = 0.18f)),
            )
            FilledIconButton(
                onClick = onToggle,
                modifier = Modifier.size(96.dp),
                colors = IconButtonDefaults.filledIconButtonColors(containerColor = color),
            ) {
                if (loading) CircularProgressIndicator(color = Color.White, modifier = Modifier.size(40.dp))
                else Icon(if (listening) Icons.Default.Stop else Icons.Default.Mic, if (listening) "Parar" else "Iniciar", Modifier.size(48.dp))
            }
        }
    }
}

@Suppress("unused")
@Composable
private fun SmallTextButton(text: String, onClick: () -> Unit) = TextButton(onClick = onClick) { Text(text) }
