package com.tyrdal.ordercheck.domain

import java.math.BigDecimal

/** Parsing of what the counter types: Persian/Arabic digits and separators are accepted. */
object StockInput {
    const val MAX_QUANTITY = 10_000_000
    private val MAX_PRICE = BigDecimal("99999999999999")

    fun asciiDigits(s: String): String = buildString(s.length) {
        for (c in s) append(
            when (c) {
                in '۰'..'۹' -> '0' + (c - '۰')
                in '٠'..'٩' -> '0' + (c - '٠')
                '٫' -> '.'
                '٬', '،', ',' -> ','
                else -> c
            },
        )
    }

    /** Whole units, 0..MAX_QUANTITY; null when empty or invalid. */
    fun quantity(text: String): Int? {
        val s = asciiDigits(text).trim()
        if (s.isEmpty() || !s.all { it.isDigit() } || s.length > 8) return null
        return s.toInt().takeIf { it in 0..MAX_QUANTITY }
    }

    sealed interface Price {
        data object Empty : Price
        data object Invalid : Price
        data class Value(val text: String) : Price
    }

    /** Optional price: thousands separators ignored, up to 2 decimals. Normalized text ("1200.5"). */
    fun price(text: String): Price {
        val s = asciiDigits(text).replace(",", "").trim()
        if (s.isEmpty()) return Price.Empty
        if (!Regex("^\\d+(\\.\\d{1,2})?$").matches(s)) return Price.Invalid
        val d = BigDecimal(s)
        if (d > MAX_PRICE) return Price.Invalid
        return Price.Value(d.stripTrailingZeros().toPlainString())
    }
}
