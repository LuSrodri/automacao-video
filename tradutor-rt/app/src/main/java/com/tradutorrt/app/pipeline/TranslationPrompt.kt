package com.tradutorrt.app.pipeline

import com.tradutorrt.app.core.Languages

/**
 * Prompt oficial de traducao do model card do Hy-MT2 ("Default Translation") dentro do chat template
 * do GGUF:  <｜hy_begin▁of▁sentence｜><｜hy_User｜>{prompt}<｜hy_Assistant｜>
 * O model card pede prompt em chines (com nomes de idioma em chines) quando o par envolve chines,
 * e prompt em ingles (nomes em ingles) caso contrario. Sem system prompt.
 */
object TranslationPrompt {
    const val BOS = "<｜hy_begin▁of▁sentence｜>"
    const val USER = "<｜hy_User｜>"
    const val ASSISTANT = "<｜hy_Assistant｜>"

    fun build(source: String, sourceLang: String, targetLang: String): String {
        val target = Languages.of(targetLang)
        val chinese = sourceLang == "zh" || targetLang == "zh" || sourceLang == "yue" || targetLang == "yue"
        val body = if (chinese) {
            "将以下文本翻译为${target?.hyNameZh ?: targetLang}，注意只需要输出翻译后的结果，不要额外解释：\n\n$source"
        } else {
            "Translate the following text into ${target?.hyName ?: targetLang}. " +
                "Note that you should only output the translated result without any additional explanation:\n\n$source"
        }
        return BOS + USER + body + ASSISTANT
    }

    fun clean(output: String): String = output.trim().removeSurrounding("\"").trim()
}
