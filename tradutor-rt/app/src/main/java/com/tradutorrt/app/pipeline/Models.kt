package com.tradutorrt.app.pipeline

data class Latencies(
    val endpointMs: Long? = null,     // fim da fala -> decisao de fim de turno (VAD + espera + Smart Turn)
    val smartTurnMs: Long? = null,    // inferencia do Smart Turn (mel + ONNX)
    val asrMs: Long? = null,          // LID + transcricao
    val mtMs: Long? = null,           // traducao
    val ttsMs: Long? = null,          // ate o primeiro audio pronto
    val totalMs: Long? = null,        // fim da fala -> inicio da voz
)

enum class ItemStatus { TRANSCRIBING, TRANSLATING, SPEAKING, DONE, ERROR }

data class ChatItem(
    val id: Long,
    val original: String = "",
    val provisional: Boolean = false,   // texto ainda e a transcricao parcial
    val sourceLang: String = "",
    val sourceLangProb: Float = 0f,
    val translation: String = "",
    val targetLang: String = "",
    val status: ItemStatus = ItemStatus.TRANSCRIBING,
    val latencies: Latencies = Latencies(),
    val endReason: String = "",
    val ttsEngine: String = "",
    val error: String? = null,
)

enum class EngineState { STOPPED, LOADING, LISTENING, ERROR }

data class PipelineState(
    val engine: EngineState = EngineState.STOPPED,
    val status: String = "",
    val speaking: Boolean = false,      // usuario falando (VAD)
    val partial: String = "",
    val partialLang: String = "",
    val items: List<ChatItem> = emptyList(),
    val lastLatencies: Latencies = Latencies(),
    val error: String? = null,
)
