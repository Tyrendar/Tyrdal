package com.tyrdal.ordercheck.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class StockInputTest {
    @Test fun quantityAcceptsPersianDigitsAndZero() {
        assertEquals(24, StockInput.quantity("۲۴"))
        assertEquals(0, StockInput.quantity("0"))
        assertEquals(1200, StockInput.quantity(" 1200 "))
    }

    @Test fun quantityRejectsJunk() {
        assertNull(StockInput.quantity(""))
        assertNull(StockInput.quantity("-1"))
        assertNull(StockInput.quantity("1.5"))
        assertNull(StockInput.quantity("6260108396830")) // a barcode typed into the quantity field
    }

    @Test fun price() {
        assertEquals(StockInput.Price.Empty, StockInput.price(" "))
        assertEquals(StockInput.Price.Value("250000"), StockInput.price("۲۵۰٬۰۰۰"))
        assertEquals(StockInput.Price.Value("1200.5"), StockInput.price("1200.50"))
        assertEquals(StockInput.Price.Value("12.25"), StockInput.price("۱۲٫۲۵"))
        assertEquals(StockInput.Price.Invalid, StockInput.price("12.345"))
        assertEquals(StockInput.Price.Invalid, StockInput.price("abc"))
    }
}
