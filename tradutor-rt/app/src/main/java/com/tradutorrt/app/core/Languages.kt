package com.tradutorrt.app.core

/**
 * Idiomas suportados ao mesmo tempo pelo Whisper (ASR/LID) e pelo Hy-MT2 (traducao).
 * [hyName] e o nome em ingles usado no prompt oficial; [hyNameZh] o nome em chines (prompt chines).
 */
data class Language(val code: String, val namePt: String, val hyName: String, val hyNameZh: String)

object Languages {
    val all: List<Language> = listOf(
        Language("pt", "Português", "Portuguese", "葡萄牙语"),
        Language("en", "Inglês", "English", "英语"),
        Language("es", "Espanhol", "Spanish", "西班牙语"),
        Language("fr", "Francês", "French", "法语"),
        Language("de", "Alemão", "German", "德语"),
        Language("it", "Italiano", "Italian", "意大利语"),
        Language("zh", "Chinês", "Chinese", "中文"),
        Language("ja", "Japonês", "Japanese", "日语"),
        Language("ko", "Coreano", "Korean", "韩语"),
        Language("ru", "Russo", "Russian", "俄语"),
        Language("ar", "Árabe", "Arabic", "阿拉伯语"),
        Language("tr", "Turco", "Turkish", "土耳其语"),
        Language("nl", "Holandês", "Dutch", "荷兰语"),
        Language("pl", "Polonês", "Polish", "波兰语"),
        Language("cs", "Tcheco", "Czech", "捷克语"),
        Language("uk", "Ucraniano", "Ukrainian", "乌克兰语"),
        Language("hi", "Hindi", "Hindi", "印地语"),
        Language("th", "Tailandês", "Thai", "泰语"),
        Language("vi", "Vietnamita", "Vietnamese", "越南语"),
        Language("id", "Indonésio", "Indonesian", "印尼语"),
        Language("ms", "Malaio", "Malay", "马来语"),
        Language("tl", "Filipino", "Filipino", "菲律宾语"),
        Language("he", "Hebraico", "Hebrew", "希伯来语"),
        Language("fa", "Persa", "Persian", "波斯语"),
        Language("ur", "Urdu", "Urdu", "乌尔都语"),
        Language("bn", "Bengali", "Bengali", "孟加拉语"),
        Language("ta", "Tâmil", "Tamil", "泰米尔语"),
        Language("te", "Telugo", "Telugu", "泰卢固语"),
        Language("mr", "Marati", "Marathi", "马拉地语"),
        Language("gu", "Guzerate", "Gujarati", "古吉拉特语"),
        Language("km", "Khmer", "Khmer", "高棉语"),
        Language("my", "Birmanês", "Burmese", "缅甸语"),
        Language("kk", "Cazaque", "Kazakh", "哈萨克语"),
        Language("mn", "Mongol", "Mongolian", "蒙古语"),
        Language("bo", "Tibetano", "Tibetan", "藏语"),
        Language("yue", "Cantonês", "Cantonese", "粤语"),
    )

    private val byCode = all.associateBy { it.code }

    fun of(code: String): Language? = byCode[code]

    fun displayName(code: String): String = byCode[code]?.namePt ?: code
}
