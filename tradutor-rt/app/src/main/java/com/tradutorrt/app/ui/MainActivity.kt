package com.tradutorrt.app.ui

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.Color
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.tradutorrt.app.TradutorApp
import com.tradutorrt.app.pipeline.EngineState
import com.tradutorrt.app.service.TranslatorService

class MainActivity : ComponentActivity() {
    private val app get() = application as TradutorApp

    private val permissionLauncher = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { res ->
        if (res[Manifest.permission.RECORD_AUDIO] == true) TranslatorService.start(this)
        else Toast.makeText(this, "Sem permissão de microfone", Toast.LENGTH_LONG).show()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AppTheme {
                val settings by app.settings.state.collectAsStateWithLifecycle()
                val download by app.models.state.collectAsStateWithLifecycle()
                val pipeline by app.pipeline.state.collectAsStateWithLifecycle()
                var showSettings by remember { mutableStateOf(false) }
                val required = remember(settings.whisperSize, settings.voiceEnabled, settings.sopranoForEnglish) { app.requiredModels() }
                LaunchedEffect(required, download.running) { if (!download.running) app.models.refresh(required) }
                val missing = app.models.missing(required)
                val ready = missing.isEmpty() && !download.running

                if (!ready) {
                    SetupScreen(
                        state = download,
                        onDownload = { app.models.downloadAll(required) },
                        onCancel = { app.models.cancel() },
                        onOpenSettings = { showSettings = true },
                    )
                } else {
                    MainScreen(
                        state = pipeline,
                        settings = settings,
                        onToggle = { toggleListening(pipeline.engine) },
                        onReplay = { app.pipeline.replay(it) },
                        onStopSpeaking = { app.pipeline.stopSpeaking() },
                        onOpenSettings = { showSettings = true },
                        onSwap = { app.settings.update { it.copy(langA = it.langB, langB = it.langA) } },
                    )
                }
                if (showSettings) {
                    SettingsDialog(
                        settings = settings,
                        onChange = { f -> app.settings.update(f) },
                        onClearHistory = { app.pipeline.clearHistory() },
                        onDismiss = { showSettings = false },
                    )
                }
            }
        }
    }

    private fun toggleListening(engine: EngineState) {
        if (engine == EngineState.LISTENING || engine == EngineState.LOADING) {
            TranslatorService.stop(this)
            return
        }
        val perms = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= 33) perms += Manifest.permission.POST_NOTIFICATIONS
        val missing = perms.filter { ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED }
        if (missing.isEmpty()) TranslatorService.start(this) else permissionLauncher.launch(missing.toTypedArray())
    }
}

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    val dark = isSystemInDarkTheme()
    val colors = if (dark) {
        darkColorScheme(primary = Color(0xFF8AB4F8), secondary = Color(0xFFFFD54F))
    } else {
        lightColorScheme(primary = Color(0xFF1E5BB8), secondary = Color(0xFFF9A825))
    }
    MaterialTheme(colorScheme = colors, content = content)
}
