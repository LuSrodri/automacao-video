package com.tradutorrt.app.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ExposedDropdownMenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.tradutorrt.app.core.AppSettings
import com.tradutorrt.app.core.Languages
import com.tradutorrt.app.core.Mode
import com.tradutorrt.app.core.WhisperSize
import java.util.Locale

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsDialog(
    settings: AppSettings,
    onChange: ((AppSettings) -> AppSettings) -> Unit,
    onClearHistory: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("OK") } },
        title = { Text("Configurações") },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Modo", style = MaterialTheme.typography.labelLarge)
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    Mode.entries.forEachIndexed { i, m ->
                        SegmentedButton(
                            selected = settings.mode == m,
                            onClick = { onChange { it.copy(mode = m) } },
                            shape = SegmentedButtonDefaults.itemShape(i, Mode.entries.size),
                        ) { Text(if (m == Mode.CONVERSATION) "Conversa" else "Ouvir") }
                    }
                }
                if (settings.mode == Mode.CONVERSATION) {
                    LanguagePicker("Idioma A", settings.langA) { c -> onChange { it.copy(langA = c) } }
                    LanguagePicker("Idioma B", settings.langB) { c -> onChange { it.copy(langB = c) } }
                } else {
                    LanguagePicker("Traduzir para", settings.listenTarget) { c -> onChange { it.copy(listenTarget = c) } }
                }
                HorizontalDivider()
                SwitchRow("Falar a tradução", settings.voiceEnabled) { v -> onChange { it.copy(voiceEnabled = v) } }
                SwitchRow("Usar Soprano para inglês", settings.sopranoForEnglish) { v -> onChange { it.copy(sopranoForEnglish = v) } }
                Text(
                    "O Soprano só fala inglês; outros idiomas usam o TTS do sistema Android.",
                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline,
                )
                SwitchRow("Transcrição parcial enquanto fala", settings.partialTranscripts) { v -> onChange { it.copy(partialTranscripts = v) } }
                HorizontalDivider()
                Text("Modelo do Whisper", style = MaterialTheme.typography.labelLarge)
                SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                    WhisperSize.entries.forEachIndexed { i, w ->
                        SegmentedButton(
                            selected = settings.whisperSize == w,
                            onClick = { onChange { it.copy(whisperSize = w) } },
                            shape = SegmentedButtonDefaults.itemShape(i, WhisperSize.entries.size),
                        ) { Text(w.label) }
                    }
                }
                SwitchRow("ASR rápido (contexto do encoder reduzido)", settings.fastAsr) { v -> onChange { it.copy(fastAsr = v) } }
                Text(
                    "Limiar do Smart Turn: ${String.format(Locale.US, "%.2f", settings.smartTurnThreshold)}",
                    style = MaterialTheme.typography.labelLarge,
                )
                Slider(
                    value = settings.smartTurnThreshold,
                    onValueChange = { v -> onChange { it.copy(smartTurnThreshold = (v * 20).toInt() / 20f) } },
                    valueRange = 0.2f..0.9f,
                )
                Text(
                    "Pausa mínima para fechar a frase: ${settings.minEndSilenceMs} ms",
                    style = MaterialTheme.typography.labelLarge,
                )
                Slider(
                    value = settings.minEndSilenceMs.toFloat(),
                    onValueChange = { v -> onChange { it.copy(minEndSilenceMs = ((v / 50).toInt() * 50)) } },
                    valueRange = 200f..1500f,
                )
                Text(
                    "Menor = responde mais rápido, mas pode cortar frases em pausas de vírgula. 600 ms não cortou " +
                        "nenhuma frase nos testes com fala real.",
                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline,
                )
                Text(
                    "Limiar maior = o Smart Turn precisa de mais certeza de que você terminou.",
                    style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.outline,
                )
                OutlinedButton(onClick = onClearHistory, modifier = Modifier.fillMaxWidth()) { Text("Limpar conversa") }
            }
        },
    )
}

@Composable
private fun SwitchRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LanguagePicker(label: String, code: String, onPick: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { expanded = it }) {
        OutlinedTextField(
            value = "${Languages.displayName(code)} ($code)",
            onValueChange = {},
            readOnly = true,
            label = { Text(label) },
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            modifier = Modifier.menuAnchor(ExposedDropdownMenuAnchorType.PrimaryNotEditable).fillMaxWidth(),
        )
        ExposedDropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            Languages.all.forEach { l ->
                DropdownMenuItem(text = { Text("${l.namePt} (${l.code})") }, onClick = {
                    onPick(l.code); expanded = false
                }, modifier = Modifier.padding(0.dp))
            }
        }
    }
}
