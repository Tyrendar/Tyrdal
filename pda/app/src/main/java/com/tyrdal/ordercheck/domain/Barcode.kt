package com.tyrdal.ordercheck.domain

/**
 * Barcode normalization — an exact port of backend/apps/catalog/normalize.py.
 * Both sides reduce every barcode to the same canonical key, so lookups are plain equality.
 */
object Barcode {
    private const val GS = '\u001d'
    private val aimPrefix = Regex("^\\][A-Za-z][0-9A-Za-z]")
    private val gs1Aim = setOf("]C1", "]e0", "]d2", "]Q3", "]J1")
    private val noise = Regex("[\\s\\x00-\\x1f\\x7f\\u200b-\\u200f\\u202a-\\u202e\\u2066-\\u2069\\ufeff]")

    private fun asciiDigits(s: String): String = buildString(s.length) {
        for (c in s) append(
            when (c) {
                in '۰'..'۹' -> '0' + (c - '۰')
                in '٠'..'٩' -> '0' + (c - '٠')
                else -> c
            },
        )
    }

    fun clean(raw: String?): String {
        if (raw == null) return ""
        var s = asciiDigits(raw).trim()
        val aim = s.take(3)
        if (aimPrefix.containsMatchIn(s)) s = s.substring(3)
        val isGs1 = aim in gs1Aim || s.contains(GS)
        if (isGs1 && s.startsWith("01") && s.length >= 16 && s.substring(2, 16).all { it.isDigit() }) {
            s = s.substring(2, 16) // AI (01) = GTIN-14
        }
        s = noise.replace(s, "")
        if (s.endsWith(".0") && s.dropLast(2).all { it.isDigit() } && s.length > 2) s = s.dropLast(2)
        return s
    }

    /** GTIN-12/13/14 are left-padded to 14 digits; anything else is kept (upper-cased). */
    fun canonical(raw: String?): String {
        val s = clean(raw)
        return if (s.isNotEmpty() && s.all { it.isDigit() } && s.length in 12..14) s.padStart(14, '0') else s.uppercase()
    }

    /** Familiar 13-digit form for display. */
    fun display(code: String): String = if (code.length == 14 && code.startsWith("0")) code.substring(1) else code
}
