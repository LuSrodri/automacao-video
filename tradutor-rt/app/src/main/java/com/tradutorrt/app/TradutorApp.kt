package com.tradutorrt.app

import android.app.Application
import com.tradutorrt.app.core.SettingsStore
import com.tradutorrt.app.models.ModelCatalog
import com.tradutorrt.app.models.ModelRepository
import com.tradutorrt.app.pipeline.TranslationPipeline

/** Grafo de dependencias simples: tudo vive enquanto o processo vive (modelos carregados uma vez). */
class TradutorApp : Application() {
    lateinit var settings: SettingsStore
        private set
    lateinit var models: ModelRepository
        private set
    lateinit var pipeline: TranslationPipeline
        private set

    override fun onCreate() {
        super.onCreate()
        settings = SettingsStore(this)
        models = ModelRepository(this)
        models.removeObsolete(com.tradutorrt.app.models.ModelCatalog.all)
        pipeline = TranslationPipeline(this, settings, models)
    }

    fun requiredModels() = settings.value.let { ModelCatalog.required(it.whisperSize, it.voiceEnabled && it.sopranoForEnglish) }
}
