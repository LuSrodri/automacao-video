package com.tradutorrt.app.tts

import java.text.Normalizer

/**
 * Port (subconjunto fiel) de soprano/utils/text_normalizer.py -> clean_text().
 * Cobre: ASCII, numeros (cardinais, anos, ordinais, decimais, $, %, horas), abreviacoes,
 * caracteres especiais, minusculas, remocao de caracteres desconhecidos e pontuacao duplicada.
 */
object SopranoTextNormalizer {
    private val ones = arrayOf(
        "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    )
    private val tens = arrayOf("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
    private val scales = arrayOf("", "thousand", "million", "billion", "trillion", "quadrillion")

    private fun under100(n: Int): String = when {
        n < 20 -> ones[n]
        n % 10 == 0 -> tens[n / 10]
        else -> tens[n / 10] + "-" + ones[n % 10]
    }

    private fun under1000(n: Int): String {
        val h = n / 100
        val r = n % 100
        return when {
            h == 0 -> under100(r)
            r == 0 -> "${ones[h]} hundred"
            else -> "${ones[h]} hundred ${under100(r)}"
        }
    }

    /** inflect.number_to_words(n, andword='') — grupos de milhar separados por ", ". */
    fun numberToWords(n: Long): String {
        if (n == 0L) return "zero"
        if (n < 0) return "minus " + numberToWords(-n)
        val groups = ArrayList<String>()
        var x = n
        var i = 0
        while (x > 0 && i < scales.size) {
            val g = (x % 1000).toInt()
            if (g != 0) groups.add(0, under1000(g) + if (scales[i].isNotEmpty()) " ${scales[i]}" else "")
            x /= 1000
            i++
        }
        return groups.joinToString(", ")
    }

    private val ordinalIrregular = mapOf(
        "one" to "first", "two" to "second", "three" to "third", "five" to "fifth", "eight" to "eighth",
        "nine" to "ninth", "twelve" to "twelfth",
    )

    fun ordinal(words: String): String {
        val m = Regex("([a-z]+)$").find(words) ?: return words
        val w = m.value
        val ord = ordinalIrregular[w] ?: when {
            w.endsWith("y") -> w.dropLast(1) + "ieth"
            else -> w + "th"
        }
        return words.substring(0, m.range.first) + ord
    }

    /** _expand_number: anos entre 1000 e 3000 sao lidos em pares ("nineteen oh five"). */
    private fun expandNumber(s: String): String {
        val num = s.toLongOrNull() ?: return s
        if (num in 1001..2999) {
            val n = num.toInt()
            return when {
                n == 2000 -> "two thousand"
                n in 2001..2009 -> "two thousand " + numberToWords((n % 100).toLong())
                n % 100 == 0 -> numberToWords((n / 100).toLong()) + " hundred"
                else -> {
                    val hi = n / 100
                    val lo = n % 100
                    numberToWords(hi.toLong()) + " " + if (lo < 10) "oh " + ones[lo] else under100(lo)
                }
            }
        }
        return numberToWords(num)
    }

    private val abbreviations = listOf(
        "mrs" to "misess", "ms" to "miss", "mr" to "mister", "dr" to "doctor", "st" to "saint", "co" to "company",
        "jr" to "junior", "maj" to "major", "gen" to "general", "drs" to "doctors", "rev" to "reverend",
        "lt" to "lieutenant", "hon" to "honorable", "sgt" to "sergeant", "capt" to "captain", "esq" to "esquire",
        "ltd" to "limited", "col" to "colonel", "ft" to "fort",
    ).map { Regex("\\b${it.first}\\.", RegexOption.IGNORE_CASE) to it.second }

    private val casedAbbreviations = listOf(
        "Hz" to "hertz", "kHz" to "kilohertz", "KB" to "kilobyte", "MB" to "megabyte", "GB" to "gigabyte",
        "TB" to "terabyte", "API" to "a p i", "CPU" to "c p u", "GPU" to "g p u", "etc" to "et cetera",
        "Jan" to "january", "Feb" to "february", "Mar" to "march", "Apr" to "april", "Aug" to "august",
        "Sept" to "september", "Oct" to "october", "Nov" to "november", "Dec" to "december",
        "Mon" to "monday", "Tues" to "tuesday", "Wed" to "wednesday", "Thurs" to "thursday", "Fri" to "friday",
        "Sat" to "saturday", "and/or" to "and or",
    ).map { Regex("\\b${Regex.escape(it.first)}\\b") to it.second }

    private fun toAscii(s: String): String {
        val d = Normalizer.normalize(s, Normalizer.Form.NFKD)
        val sb = StringBuilder()
        for (c in d) {
            when {
                c.code < 128 -> sb.append(c)
                Character.getType(c) == Character.NON_SPACING_MARK.toInt() -> {}
                c == '‘' || c == '’' -> sb.append('\'')
                c == '“' || c == '”' -> sb.append('"')
                c == '–' || c == '—' -> sb.append('-')
                c == '…' -> sb.append("...")
                c == ' ' -> sb.append(' ')
                c == '£' -> sb.append("PS")
                else -> {}
            }
        }
        return sb.toString()
    }

    private fun expandTime(m: MatchResult): String {
        val parts = m.value.split(":")
        val h = parts[0].toInt()
        val mm = parts[1]
        if (parts.size == 2) {
            if (mm == "00") return if (h == 0) "0" else if (h > 12) "$h hundred" else "$h o'clock"
            return if (mm.startsWith("0")) "$h oh ${mm.substring(1)}" else "$h $mm"
        }
        return parts.joinToString(" ") { it.trimStart('0').ifEmpty { "0" } }
    }

    private fun expandDollars(m: MatchResult): String {
        val match = m.groupValues[1].replace(",", "")
        val parts = match.split(".")
        if (parts.size > 2) return "$match dollars"
        val dollars = parts[0].toLongOrNull() ?: 0
        val cents = if (parts.size > 1 && parts[1].isNotEmpty()) parts[1].toLong() else 0
        val du = if (dollars == 1L) "dollar" else "dollars"
        val cu = if (cents == 1L) "cent" else "cents"
        return when {
            dollars > 0 && cents > 0 -> "$dollars $du, $cents $cu"
            dollars > 0 -> "$dollars $du"
            cents > 0 -> "$cents $cu"
            else -> "zero dollars"
        }
    }

    private fun normalizeNumbers(input: String): String {
        var t = input
        t = Regex("#\\d").replace(t) { "number ${it.value[1]}" }
        t = Regex("\\b(\\d+)([KMBT])\\b", RegexOption.IGNORE_CASE).replace(t) {
            val n = it.groupValues[1]
            when (it.groupValues[2].uppercase()) {
                "K" -> "$n thousand"; "M" -> "$n million"; "B" -> "$n billion"; else -> "$n trillion"
            }
        }
        t = Regex("(\\d[\\d,]+\\d)").replace(t) { it.value.replace(",", "") }
        t = Regex("(\\d\\d?:\\d\\d(?::\\d\\d)?)").replace(t) { expandTime(it) }
        t = Regex("£([\\d,]*\\d+)").replace(t) { "${it.groupValues[1]} pounds" }
        t = Regex("\\$([\\d.,]*\\d+)").replace(t) { expandDollars(it) }
        t = Regex("(\\d+(?:\\.\\d+)+)").replace(t) { m ->
            val p = m.value.split(".")
            p[0] + " point " + p.drop(1).joinToString(" point ") { it.toCharArray().joinToString(" ") }
        }
        t = Regex("(\\d)\\s?\\*\\s?(\\d)").replace(t) { "${it.groupValues[1]} times ${it.groupValues[2]}" }
        t = Regex("(\\d)\\s?\\+\\s?(\\d)").replace(t) { "${it.groupValues[1]} plus ${it.groupValues[2]}" }
        t = Regex("(\\d+)/(\\d+)").replace(t) { "${it.groupValues[1]} over ${it.groupValues[2]}" }
        t = Regex("(\\d+)(st|nd|rd|th)\\b").replace(t) { ordinal(numberToWords(it.groupValues[1].toLong())) }
        repeat(2) { t = Regex("(\\d)([a-zA-Z])|([a-zA-Z])(\\d)").replace(t) { m -> m.value[0] + " " + m.value[1] } }
        t = Regex("\\d+").replace(t) { expandNumber(it.value) }
        return t
    }

    private val special = listOf(
        "@" to " at ", "&" to " and ", "%" to " percent ", ":" to ".", ";" to ",", "+" to " plus ",
        "\\" to " backslash ", "~" to " about ", "<=" to " less than or equal to ", ">=" to " greater than or equal to ",
        "<" to " less than ", ">" to " greater than ", "=" to " equals ", "/" to " slash ", "_" to " ", "*" to " ",
    )

    private fun splitMixedCase(input: String): String = Regex("\\b([A-Z][a-z]*)+\\b").replace(input) { m ->
        val w = m.value
        val parts = Regex("[A-Z][a-z]*").findAll(w).map { it.value }.toList()
        when {
            parts.size == 1 -> w
            parts.size == w.length -> w
            parts.size == w.length - 1 && w.last() == 's' -> w.dropLast(1) + "'s"
            else -> parts.joinToString(" ")
        }
    }

    fun clean(input: String): String {
        var t = input.replace("—", " - ")
        t = toAscii(t)
        t = t.split('\n').map { it.trim() }.filter { it.isNotEmpty() }
            .joinToString(" ") { if (it.last() in ".!?") it else "$it." }
        t = normalizeNumbers(t)
        t = Regex("(https?://)").replace(t, "h t t p s colon slash slash ")
        t = Regex("(.) - (.)").replace(t) { "${it.groupValues[1]}, ${it.groupValues[2]}" }
        t = Regex("([A-Za-z])\\.([A-Za-z])").replace(t) { "${it.groupValues[1]} dot ${it.groupValues[2]}" }
        t = t.replace('(', ',').replace(')', ',').replace('[', ',').replace(']', ',').replace('{', ',').replace('}', ',')
        for ((re, rep) in abbreviations) t = re.replace(t, rep)
        for ((re, rep) in casedAbbreviations) t = re.replace(t, rep)
        t = splitMixedCase(t)
        for ((a, b) in special) t = t.replace(a, b)
        t = t.lowercase()
        t = Regex("[^A-Za-z !$%&'*+,\\-./0-9<>?_]").replace(t, "")
        t = Regex("[<>/_+]").replace(t, "")
        t = Regex("\\s+").replace(t, " ")
        t = Regex(" ([.?!,])").replace(t) { it.groupValues[1] }
        t = t.trim()
        t = Regex("\\.\\.\\.+").replace(t, "\u0000")
        t = Regex(",+").replace(t, ",")
        t = Regex("[.,]*\\.[.,]*").replace(t, ".")
        t = Regex("[.,!]*![.,!]*").replace(t, "!")
        t = Regex("[.,!?]*\\?[.,!?]*").replace(t, "?")
        t = t.replace("\u0000", "...")
        t = Regex("(\\w)\\1{2,}").replace(t) { it.value.substring(0, 2) }
        return t
    }

    /** Divide em frases (como split_and_recombine_text) e junta frases com menos de [minLength] caracteres. */
    fun sentences(text: String, minLength: Int = 30, maxLength: Int = 300): List<String> {
        val raw = Regex("(?<=[.!?])\\s+").split(text).map { it.trim() }
            .filter { it.isNotEmpty() && !Regex("^[\\s.,;:!?]*$").matches(it) }
        val split = raw.flatMap { s ->
            if (s.length <= maxLength) listOf(s) else s.chunked(maxLength)
        }
        val merged = ArrayList<String>()
        var carry: String? = null
        for ((i, s0) in split.withIndex()) {
            val s = carry?.let { "$it $s0" } ?: s0
            carry = null
            if (s.length < minLength && split.size > 1) {
                if (merged.isNotEmpty()) merged[merged.size - 1] = merged.last() + " " + s
                else if (i + 1 < split.size) carry = s
                else merged.add(s)
            } else merged.add(s)
        }
        carry?.let { merged.add(it) }
        return merged
    }
}

/** Tokenizer BPE do Soprano (normalizer Lowercase, pre-tokenizer Digits + Split \s+|\w+|[^\w\s]+). */
class SopranoTokenizer(lines: List<String>) {
    private val vocab = HashMap<String, Int>()
    private val ranks = HashMap<Pair<String, String>, Int>()

    init {
        for (l in lines) {
            if (l.startsWith("#") || l.isBlank()) continue
            val p = l.split('\t')
            when (p[0]) {
                "v" -> vocab[unquote(p[2])] = p[1].toInt()
                "m" -> ranks[unquote(p[1]) to unquote(p[2])] = ranks.size
            }
        }
    }

    companion object {
        const val UNK = 0
        const val TEXT = 1
        const val START = 2
        const val STOP = 3
        private val split = Regex("\\s+|\\w+|[^\\w\\s]+")

        private fun unquote(s: String): String {
            // JSON string simples (o arquivo foi gerado com json.dumps)
            val inner = s.substring(1, s.length - 1)
            val sb = StringBuilder()
            var i = 0
            while (i < inner.length) {
                val c = inner[i]
                if (c == '\\' && i + 1 < inner.length) {
                    when (val n = inner[i + 1]) {
                        'n' -> sb.append('\n'); 't' -> sb.append('\t'); 'u' -> {
                            sb.append(inner.substring(i + 2, i + 6).toInt(16).toChar()); i += 4
                        }
                        else -> sb.append(n)
                    }
                    i += 2
                } else {
                    sb.append(c); i++
                }
            }
            return sb.toString()
        }
    }

    private fun bpe(word: String): List<String> {
        val parts = word.map { it.toString() }.toMutableList()
        while (parts.size > 1) {
            var best = -1
            var bestRank = Int.MAX_VALUE
            for (i in 0 until parts.size - 1) {
                val r = ranks[parts[i] to parts[i + 1]] ?: continue
                if (r < bestRank) {
                    bestRank = r; best = i
                }
            }
            if (best < 0) break
            parts[best] = parts[best] + parts[best + 1]
            parts.removeAt(best + 1)
        }
        return parts
    }

    /** Tokens do texto ja normalizado (sem os especiais). */
    fun encodeText(text: String): IntArray {
        val norm = Regex("\\s+").replace(text.lowercase(), " ")
        val out = ArrayList<Int>()
        // Digits(individual_digits=true): cada digito vira um pre-token isolado
        val pieces = ArrayList<String>()
        var buf = StringBuilder()
        for (c in norm) {
            if (c.isDigit()) {
                if (buf.isNotEmpty()) {
                    pieces.add(buf.toString()); buf = StringBuilder()
                }
                pieces.add(c.toString())
            } else buf.append(c)
        }
        if (buf.isNotEmpty()) pieces.add(buf.toString())
        for (p in pieces) {
            for (m in split.findAll(p)) {
                for (t in bpe(m.value)) out.add(vocab[t] ?: UNK)
            }
        }
        return out.toIntArray()
    }

    /** Prompt no formato do Soprano: [STOP][TEXT]{texto}[START]. */
    fun encodePrompt(cleanText: String): IntArray = intArrayOf(STOP, TEXT) + encodeText(cleanText) + intArrayOf(START)
}
