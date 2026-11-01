package com.tradutorrt.app.core

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

enum class Mode { CONVERSATION, LISTEN }
enum class WhisperSize(val label: String) { BASE("base (q5_1)"), SMALL("small (q5_1)") }

data class AppSettings(
    val mode: Mode = Mode.CONVERSATION,
    val langA: String = "pt",
    val langB: String = "en",
    val listenTarget: String = "pt",
    val voiceEnabled: Boolean = true,
    val sopranoForEnglish: Boolean = true,
    val whisperSize: WhisperSize = WhisperSize.BASE,
    val smartTurnThreshold: Float = 0.5f,
    val partialTranscripts: Boolean = true,
    val fastAsr: Boolean = true,
)

class SettingsStore(context: Context) {
    private val prefs = context.getSharedPreferences("settings", Context.MODE_PRIVATE)
    private val _state = MutableStateFlow(load())
    val state: StateFlow<AppSettings> = _state.asStateFlow()
    val value: AppSettings get() = _state.value

    private fun load(): AppSettings {
        val d = AppSettings()
        return AppSettings(
            mode = runCatching { Mode.valueOf(prefs.getString("mode", d.mode.name)!!) }.getOrDefault(d.mode),
            langA = prefs.getString("langA", d.langA)!!,
            langB = prefs.getString("langB", d.langB)!!,
            listenTarget = prefs.getString("listenTarget", d.listenTarget)!!,
            voiceEnabled = prefs.getBoolean("voice", d.voiceEnabled),
            sopranoForEnglish = prefs.getBoolean("soprano", d.sopranoForEnglish),
            whisperSize = runCatching { WhisperSize.valueOf(prefs.getString("whisper", d.whisperSize.name)!!) }
                .getOrDefault(d.whisperSize),
            smartTurnThreshold = prefs.getFloat("stThreshold", d.smartTurnThreshold),
            partialTranscripts = prefs.getBoolean("partials", d.partialTranscripts),
            fastAsr = prefs.getBoolean("fastAsr", d.fastAsr),
        )
    }

    fun update(f: (AppSettings) -> AppSettings) {
        val s = f(_state.value)
        prefs.edit()
            .putString("mode", s.mode.name)
            .putString("langA", s.langA)
            .putString("langB", s.langB)
            .putString("listenTarget", s.listenTarget)
            .putBoolean("voice", s.voiceEnabled)
            .putBoolean("soprano", s.sopranoForEnglish)
            .putString("whisper", s.whisperSize.name)
            .putFloat("stThreshold", s.smartTurnThreshold)
            .putBoolean("partials", s.partialTranscripts)
            .putBoolean("fastAsr", s.fastAsr)
            .apply()
        _state.value = s
    }
}
