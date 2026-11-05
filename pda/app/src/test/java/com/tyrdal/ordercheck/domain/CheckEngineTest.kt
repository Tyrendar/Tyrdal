package com.tyrdal.ordercheck.domain

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class BarcodeTest {
    @Test fun variantsMatch() {
        assertEquals(Barcode.canonical("6260108396830"), Barcode.canonical("06260108396830"))
        assertEquals(Barcode.canonical("012000800443"), Barcode.canonical("0012000800443"))
    }

    @Test fun scannerNoiseRemoved() {
        assertEquals("6260108396830", Barcode.clean(" 6260108396830\r\n"))
        assertEquals("6260108396830", Barcode.clean("]E06260108396830"))
        assertEquals("6260108396830", Barcode.clean("⁦6260108396830⁩"))
        assertEquals("6260108396830", Barcode.clean("۶۲۶۰۱۰۸۳۹۶۸۳۰"))
        assertEquals("06260108396830", Barcode.clean("]C10106260108396830\u001d10ABC"))
    }

    @Test fun internalCodesExact() {
        assertEquals("2162231168480006", Barcode.canonical("2162231168480006"))
        assertEquals("11201045", Barcode.canonical("11201045"))
    }
}

class CheckEngineTest {
    private val reasons = listOf(
        Reason(1, "no_stock", "", "No stock", "short", false, null, 10),
        Reason(2, "extra_item", "", "Extra", "extra", false, "extra", 20),
        Reason(3, "not_in_order", "", "Not in order", "extra", false, "not_in_order", 30),
        Reason(8, "other", "", "Other", "both", true, null, 80),
    )
    private val mapping = mutableMapOf<String, MappedProduct>()
    private val engine = CheckEngine({ reasons }, { mapping[it] })
    private lateinit var m: OrderModel

    private fun line(id: Long, pid: String, pack: Int, code: String, rank: Int = 0) =
        Line(id, pid, "T$pid", "A", rank, pack, 12, 0, 0, LineState.PENDING, false, listOf(code), 5, null)

    @Before fun setUp() {
        val lines = listOf(line(1, "P1", 1, "6260108396830"), line(2, "P2", 3, "6260055843500"), line(3, "P3", 2, "6260113899210"))
        m = OrderModel(
            OrderInfo(10, "1", "Store", "assigned", 1, locked = false, revoked = false),
            lines.associateBy { it.id }.toMutableMap(),
            lines.associate { Barcode.canonical(it.barcodes[0]) to mutableListOf(CodeRef(it.id, false)) }.toMutableMap(),
            null,
        )
        mapping[Barcode.canonical("6262754015370")] = MappedProduct("PX", "Other product")
    }

    @Test fun oneScanOneBox() {
        val r = engine.scan(m, "6260108396830", false)
        assertEquals(Outcome.LINE_COMPLETE, r.outcome)
        assertEquals(LineState.OK, m.lines[1]!!.state)
        assertEquals(1, r.events.size)
    }

    @Test fun partialThenComplete() {
        assertEquals(Outcome.COUNTED, engine.scan(m, "6260055843500", false).outcome)
        assertEquals(LineState.PARTIAL, m.lines[2]!!.state)
        engine.scan(m, "6260055843500", false)
        assertEquals(Outcome.LINE_COMPLETE, engine.scan(m, "6260055843500", false).outcome)
    }

    @Test fun duplicateFlaggedIsNotCounted() {
        engine.scan(m, "6260055843500", false)
        val r = engine.scan(m, "6260055843500", true)
        assertEquals(Outcome.DUPLICATE, r.outcome)
        assertEquals(1, m.lines[2]!!.boxesScanned)
        assertEquals(true, r.events[0]["duplicate"].toString().toBoolean())
    }

    @Test fun overScanBlocksUntilDecision() {
        engine.scan(m, "6260108396830", false)
        assertEquals(Outcome.OVER, engine.scan(m, "6260108396830", false).outcome)
        assertEquals(1, m.lines[1]!!.boxesScanned)
        assertEquals(Outcome.BLOCKED, engine.scan(m, "6260055843500", false).outcome)
        val d = engine.decide(m, removed = true)
        assertEquals(Outcome.REMOVED, d.outcome)
        val l = m.lines[1]!!
        assertEquals(1, l.boxesExtra)
        assertEquals(Tab.ISSUE, l.tab)
        assertEquals(2L, l.discs[DiscType.EXTRA]!!.reasonId)
        assertEquals(DiscStatus.REASONED, l.discs[DiscType.EXTRA]!!.status)
        assertNull(m.pending)
        assertEquals(Outcome.COUNTED, engine.scan(m, "6260055843500", false).outcome)
    }

    @Test fun mistakeRecordsNothing() {
        engine.scan(m, "6260108396830", false)
        engine.scan(m, "6260108396830", false)
        assertEquals(Outcome.MISTAKE, engine.decide(m, removed = false).outcome)
        assertEquals(0, m.lines[1]!!.boxesExtra)
        assertTrue(m.lines[1]!!.discs.isEmpty())
    }

    @Test fun notInOrderCreatesTempLine() {
        val r = engine.scan(m, "6262754015370", false)
        assertEquals(Outcome.NOT_IN_ORDER, r.outcome)
        engine.decide(m, removed = true)
        val l = m.lines.values.first { it.productId == "PX" }
        assertTrue(l.id < 0 && l.isUnordered)
        assertEquals(LineState.EXTRA, l.state)
        assertEquals(3L, l.discs[DiscType.NOT_IN_ORDER]!!.reasonId)
        // second box of the same wrong product reuses the line
        engine.scan(m, "6262754015370", false)
        engine.decide(m, removed = true)
        assertEquals(2, l.discs[DiscType.NOT_IN_ORDER]!!.qtyBoxes)
        assertEquals(3, m.counters().linesTotal)
    }

    @Test fun unknownBarcode() {
        assertEquals(Outcome.UNKNOWN, engine.scan(m, "1234567890123", false).outcome)
    }

    @Test fun realBarcodeBeatsRepairedOne() {
        // Line 3 carries a repaired code equal to line 1's real code (11596 vs 11590 case).
        m.codes.getValue(Barcode.canonical("6260108396830")).add(0, CodeRef(3, derived = true))
        val r = engine.scan(m, "6260108396830", false)
        assertEquals(1L, r.line!!.id)
    }

    @Test fun shortageFlowAndLateBoxes() {
        val r = engine.declareShort(m, 2, 1, null)
        assertEquals(Outcome.APPLIED, r.outcome)
        val l = m.lines[2]!!
        assertEquals(LineState.SHORT, l.state)
        assertEquals(3, l.discs[DiscType.SHORT]!!.qtyBoxes)
        assertEquals(DiscStatus.REASONED, l.discs[DiscType.SHORT]!!.status)
        repeat(3) { engine.scan(m, "6260055843500", false) }
        assertEquals(DiscStatus.RESOLVED, l.discs[DiscType.SHORT]!!.status)
        assertEquals(LineState.OK, l.state)
    }

    @Test fun reasonNeedingNote() {
        engine.declareShort(m, 3, 8, null)
        assertEquals(DiscStatus.OPEN, m.lines[3]!!.discs[DiscType.SHORT]!!.status)
        engine.setReason(m, 3, DiscType.SHORT, 8, "torn")
        assertEquals(DiscStatus.REASONED, m.lines[3]!!.discs[DiscType.SHORT]!!.status)
        assertEquals("reason_not_applicable", engine.declareShort(m, 2, 2, null).error)
    }

    @Test fun completionRules() {
        engine.scan(m, "6260108396830", false)
        assertEquals(setOf("line_not_checked"), engine.completionProblems(m).map { it.code }.toSet())
        engine.declareShort(m, 2, null, null)
        engine.declareShort(m, 3, 1, null)
        assertEquals(listOf("discrepancy_without_reason"), engine.completionProblems(m).map { it.code })
        engine.setReason(m, 2, DiscType.SHORT, 1, null)
        assertTrue(engine.completionProblems(m).isEmpty())
        val c = m.counters()
        assertEquals(3, c.linesDone)
    }

    @Test fun lockedOrderRejectsScans() {
        m.info = m.info.copy(locked = true)
        assertEquals(Outcome.LOCKED, engine.scan(m, "6260108396830", false).outcome)
    }

    @Test fun eventsForTempLinesCarryProductId() {
        engine.scan(m, "6262754015370", false)
        engine.decide(m, removed = true)
        val l = m.lines.values.first { it.productId == "PX" }
        val r = engine.setReason(m, l.id, DiscType.NOT_IN_ORDER, 8, "wrong flavor")
        assertEquals("\"PX\"", r.events[0]["product_id"].toString())
    }
}
