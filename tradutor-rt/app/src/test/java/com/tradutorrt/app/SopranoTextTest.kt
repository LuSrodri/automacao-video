package com.tradutorrt.app

import com.tradutorrt.app.tts.SopranoTextNormalizer
import com.tradutorrt.app.tts.SopranoTokenizer
import org.json.JSONArray
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

/** Fixtures geradas por tools/make_test_fixtures.py com o clean_text() e o tokenizer.json originais. */
class SopranoTextTest {
    private val cases = JSONArray(String(TestUtil.resourceBytes("soprano_tok.json")))
    private val tok = SopranoTokenizer(TestUtil.asset("soprano_tokenizer.txt").readLines())

    @Test
    fun tokenizerMatchesHuggingFace() {
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val ids = c.getJSONArray("ids").let { a -> IntArray(a.length()) { a.getInt(it) } }
            assertArrayEquals("tokens de '${c.getString("clean")}'", ids, tok.encodePrompt(c.getString("clean")))
        }
    }

    @Test
    fun normalizerMatchesPython() {
        var ok = 0
        for (i in 0 until cases.length()) {
            val c = cases.getJSONObject(i)
            val got = SopranoTextNormalizer.clean(c.getString("text"))
            if (got == c.getString("clean")) ok++ else println("DIFERENTE: '${c.getString("text")}'\n  py: ${c.getString("clean")}\n  kt: $got")
        }
        println("normalizador: $ok/${cases.length()} identicos ao Python")
        assertEquals(cases.length(), ok)
    }

    @Test
    fun numbers() {
        assertEquals("one hundred twenty-three thousand, four hundred fifty-six", SopranoTextNormalizer.numberToWords(123456))
        assertEquals("twenty-first", SopranoTextNormalizer.ordinal(SopranoTextNormalizer.numberToWords(21)))
        assertEquals("nineteen oh five.", SopranoTextNormalizer.clean("1905"))
    }

    @Test
    fun sentences() {
        val s = SopranoTextNormalizer.sentences("hi. this is a longer sentence that has enough characters. ok!")
        assertEquals(listOf("hi. this is a longer sentence that has enough characters. ok!"), s)
        val s2 = SopranoTextNormalizer.sentences("this is the first sentence, long enough. and this is the second one, also long.")
        assertEquals(2, s2.size)
    }
}
