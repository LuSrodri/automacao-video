package com.tradutorrt.app.core

import java.io.File

object CpuInfo {
    /**
     * Numero de nucleos "grandes" (todos os que nao pertencem ao cluster de menor frequencia maxima).
     * Em SoCs big.LITTLE tipicos (ex.: 4x A55 + 3x A78 + 1x X1) retorna 4. Limitado a [1, 6].
     */
    val bigCores: Int by lazy { computeBigCores() }

    private fun computeBigCores(): Int {
        val n = Runtime.getRuntime().availableProcessors()
        val freqs = (0 until n).mapNotNull { i ->
            runCatching {
                File("/sys/devices/system/cpu/cpu$i/cpufreq/cpuinfo_max_freq").readText().trim().toLong()
            }.getOrNull()
        }
        if (freqs.size < 2) return (n / 2).coerceIn(1, 4)
        val minF = freqs.min()
        val big = freqs.count { it > minF }
        return (if (big == 0) n / 2 else big).coerceIn(1, 6)
    }
}
