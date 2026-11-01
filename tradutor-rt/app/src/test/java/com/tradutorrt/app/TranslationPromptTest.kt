package com.tradutorrt.app

import com.tradutorrt.app.pipeline.TranslationPrompt
import org.junit.Assert.assertEquals
import org.junit.Test

class TranslationPromptTest {
    @Test
    fun officialEnglishTemplate() {
        assertEquals(
            "<｜hy_begin▁of▁sentence｜><｜hy_User｜>Translate the following text into Portuguese. Note that you should " +
                "only output the translated result without any additional explanation:\n\nHello there.<｜hy_Assistant｜>",
            TranslationPrompt.build("Hello there.", "en", "pt"),
        )
    }

    @Test
    fun chinesePromptWhenChineseInvolved() {
        assertEquals(
            "<｜hy_begin▁of▁sentence｜><｜hy_User｜>将以下文本翻译为中文，注意只需要输出翻译后的结果，不要额外解释：\n\nHello<｜hy_Assistant｜>",
            TranslationPrompt.build("Hello", "en", "zh"),
        )
    }
}
