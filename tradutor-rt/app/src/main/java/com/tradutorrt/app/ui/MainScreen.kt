package com.tradutorrt.app.ui

import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.expandVertically
import androidx.compose.animation.shrinkVertically
import androidx.compose.animation.togetherWith
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.VolumeOff
import androidx.compose.material.icons.automirrored.filled.VolumeUp
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.SwapHoriz
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.tradutorrt.app.core.AppSettings
import com.tradutorrt.app.core.CpuInfo
import com.tradutorrt.app.core.Languages
import com.tradutorrt.app.core.Mode
import com.tradutorrt.app.pipeline.ChatItem
import com.tradutorrt.app.pipeline.EngineState
import com.tradutorrt.app.pipeline.ItemStatus
import com.tradutorrt.app.pipeline.Latencies
import com.tradutorrt.app.pipeline.PipelineState
import kotlinx.coroutines.flow.StateFlow

/*
 * Tela principal pensada para nao "piscar" durante o processamento:
 *  - lista com reverseLayout: o fim da conversa fica ancorado embaixo, sem auto-scroll a cada parcial;
 *  - a bolha "ao vivo" e substituida pelo item da conversa no mesmo frame (o pipeline faz as duas
 *    coisas num unico update) e o texto parcial continua visivel como provisorio;
 *  - itens entram/saem com animateItem, cartoes mudam de tamanho com animateContentSize e os estados
 *    (transcrevendo -> traduzindo -> traducao) trocam com crossfade;
 *  - o nivel do microfone vem de um fluxo separado e so recompoe o botao.
 */

private val smooth = spring<Float>(stiffness = Spring.StiffnessMediumLow)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MainScreen(
    state: PipelineState,
    level: StateFlow<Float>,
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
            val showLive = state.engine == EngineState.LISTENING && (state.speaking || state.partial.isNotEmpty())
            // so acompanha o fim se o usuario ja estava no fim (nao "puxa" quem esta lendo o historico)
            LaunchedEffect(state.items.size) {
                if (listState.firstVisibleItemIndex <= 1) listState.animateScrollToItem(0)
            }
            Box(Modifier.weight(1f).fillMaxWidth()) {
                LazyColumn(
                    Modifier.fillMaxSize().padding(horizontal = 12.dp),
                    state = listState,
                    reverseLayout = true,
                    verticalArrangement = Arrangement.spacedBy(10.dp, Alignment.Bottom),
                ) {
                    if (showLive) {
                        item(key = "live") {
                            LiveBubble(state.partial, state.partialLang, Modifier.animateItem(fadeInSpec = tween(180), fadeOutSpec = tween(120)))
                        }
                    }
                    items(state.items.asReversed(), key = { it.id }) {
                        ChatBubble(it, settings, onReplay, Modifier.animateItem(fadeInSpec = tween(220), placementSpec = spring(stiffness = Spring.StiffnessMediumLow)))
                    }
                }
                if (state.items.isEmpty() && !showLive) {
                    Text(
                        "Toque no microfone e fale. O idioma é detectado automaticamente; quando você termina a " +
                            "frase, ela é traduzida e falada.",
                        Modifier.align(Alignment.Center).padding(32.dp),
                        textAlign = TextAlign.Center, color = MaterialTheme.colorScheme.outline,
                    )
                }
            }
            BottomControls(state, level, onToggle)
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
                style = MaterialTheme.typography.labelMedium, maxLines = 1,
            )
            Text(
                "Total fim da fala → voz: ${f(l.totalMs)} ms · ${CpuInfo.bigCores} núcleos grandes",
                style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline, maxLines = 1,
            )
        }
    }
}

/** Tres pontos pulsando, para estados de espera (sem trocar o layout). */
@Composable
private fun Dots(label: String) {
    val t = rememberInfiniteTransition(label = "dots")
    val a by t.animateFloat(0.35f, 1f, infiniteRepeatable(tween(700, easing = FastOutSlowInEasing), RepeatMode.Reverse), label = "a")
    Text("$label…", Modifier.alpha(a), fontStyle = FontStyle.Italic, style = MaterialTheme.typography.bodyMedium)
}

@Composable
private fun ChatBubble(item: ChatItem, settings: AppSettings, onReplay: (Long) -> Unit, modifier: Modifier) {
    // na conversa, a fala no idioma B fica alinhada a direita (como "o outro lado")
    val right = settings.mode == Mode.CONVERSATION && item.sourceLang == settings.langB
    val container by animateColorAsState(
        if (right) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.primaryContainer,
        tween(300), label = "bubble",
    )
    Row(modifier.fillMaxWidth(), horizontalArrangement = if (right) Arrangement.End else Arrangement.Start) {
        Card(
            modifier = Modifier.widthIn(max = 340.dp).animateContentSize(spring(stiffness = Spring.StiffnessMediumLow)),
            colors = CardDefaults.cardColors(containerColor = container),
            shape = RoundedCornerShape(16.dp),
        ) {
            Column(Modifier.padding(12.dp)) {
                AnimatedVisibility(item.sourceLang.isNotEmpty(), enter = fadeIn(tween(200)), exit = fadeOut()) {
                    Text(
                        "${Languages.displayName(item.sourceLang)} (${item.sourceLang}, ${(item.sourceLangProb * 100).toInt()}%) → " +
                            Languages.displayName(item.targetLang),
                        style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline,
                    )
                }
                // original: o texto parcial aparece apagado/italico e "acende" quando o final chega
                val originalAlpha by animateFloatAsState(if (item.provisional) 0.55f else 1f, tween(250), label = "orig")
                when {
                    item.original.isNotEmpty() -> Text(
                        item.original, Modifier.alpha(originalAlpha), style = MaterialTheme.typography.bodyMedium,
                        fontStyle = if (item.provisional) FontStyle.Italic else FontStyle.Normal,
                    )
                    item.status == ItemStatus.TRANSCRIBING -> Dots("transcrevendo")
                }
                Spacer(Modifier.height(6.dp))
                AnimatedContent(
                    targetState = item.translation.isNotEmpty() to item.status,
                    transitionSpec = { fadeIn(tween(220)) togetherWith fadeOut(tween(120)) },
                    label = "translation",
                ) { (has, status) ->
                    when {
                        has -> Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                item.translation, Modifier.weight(1f, fill = false),
                                style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold,
                            )
                            IconButton(onClick = { onReplay(item.id) }, modifier = Modifier.size(36.dp)) {
                                Icon(Icons.AutoMirrored.Filled.VolumeUp, "Repetir áudio")
                            }
                        }
                        status == ItemStatus.TRANSLATING -> Dots("traduzindo")
                        status == ItemStatus.ERROR -> Text(
                            "Erro: ${item.error}", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall,
                        )
                        else -> Spacer(Modifier.height(0.dp))
                    }
                }
                val l = item.latencies
                val parts = listOfNotNull(
                    l.endpointMs?.let { "turno ${it}ms" }, l.asrMs?.let { "ASR ${it}ms" }, l.mtMs?.let { "MT ${it}ms" },
                    l.ttsMs?.let { "TTS ${it}ms" }, l.totalMs?.let { "total ${it}ms" },
                )
                AnimatedVisibility(item.status == ItemStatus.DONE && parts.isNotEmpty(), enter = fadeIn(tween(250)) + expandVertically(), exit = fadeOut() + shrinkVertically()) {
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
private fun LiveBubble(text: String, lang: String, modifier: Modifier) {
    Card(
        modifier.widthIn(max = 340.dp).animateContentSize(spring(stiffness = Spring.StiffnessMediumLow)),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
        shape = RoundedCornerShape(16.dp),
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(if (lang.isNotEmpty()) "ouvindo · $lang" else "ouvindo", style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.outline)
            if (text.isEmpty()) Dots("") else Text(text, fontStyle = FontStyle.Italic)
        }
    }
}

@Composable
private fun BottomControls(state: PipelineState, levelFlow: StateFlow<Float>, onToggle: () -> Unit) {
    val listening = state.engine == EngineState.LISTENING
    val loading = state.engine == EngineState.LOADING
    val color by animateColorAsState(
        when {
            listening && state.speaking -> Color(0xFFE53935)
            listening -> MaterialTheme.colorScheme.primary
            else -> MaterialTheme.colorScheme.secondary
        },
        tween(350), label = "btn",
    )
    Column(Modifier.fillMaxWidth().padding(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        AnimatedVisibility(state.error != null, enter = fadeIn() + expandVertically(), exit = fadeOut() + shrinkVertically()) {
            Text(state.error ?: "", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.labelSmall)
        }
        val status = when {
            loading -> state.status.ifEmpty { "Carregando…" }
            listening && state.speaking -> "Ouvindo você…"
            listening -> "Pronto para ouvir"
            else -> "Toque para começar"
        }
        AnimatedContent(status, transitionSpec = { fadeIn(tween(200)) togetherWith fadeOut(tween(150)) }, label = "status") {
            Text(it, style = MaterialTheme.typography.labelLarge)
        }
        Spacer(Modifier.height(8.dp))
        Box(contentAlignment = Alignment.Center, modifier = Modifier.size(140.dp)) {
            Halo(levelFlow, listening, color)
            FilledIconButton(
                onClick = onToggle,
                modifier = Modifier.size(96.dp),
                colors = IconButtonDefaults.filledIconButtonColors(containerColor = color),
            ) {
                AnimatedContent(
                    targetState = when { loading -> 0; listening -> 1; else -> 2 },
                    transitionSpec = { fadeIn(tween(200)) togetherWith fadeOut(tween(150)) }, label = "icon",
                ) { s ->
                    when (s) {
                        0 -> CircularProgressIndicator(color = Color.White, modifier = Modifier.size(40.dp))
                        1 -> Icon(Icons.Default.Stop, "Parar", Modifier.size(48.dp))
                        else -> Icon(Icons.Default.Mic, "Iniciar", Modifier.size(48.dp))
                    }
                }
            }
        }
    }
}

/** Halo do microfone: so ele observa o nivel do VAD (o resto da tela nao recompoe). */
@Composable
private fun Halo(levelFlow: StateFlow<Float>, listening: Boolean, color: Color) {
    val raw by levelFlow.collectAsStateWithLifecycle()
    val level by animateFloatAsState(if (listening) raw else 0f, smooth, label = "level")
    val scale = remember(level) { 0.7f + 0.3f * level }
    Box(
        Modifier.size(140.dp).scale(scale).clip(CircleShape).background(color.copy(alpha = 0.18f)),
    )
}
