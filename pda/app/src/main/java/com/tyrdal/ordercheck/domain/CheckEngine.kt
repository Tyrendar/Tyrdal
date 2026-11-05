package com.tyrdal.ordercheck.domain

import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.time.OffsetDateTime
import java.util.UUID

/** What the checker sees and hears after an action. */
enum class Outcome {
    COUNTED, LINE_COMPLETE, DUPLICATE, OVER, NOT_IN_ORDER, UNKNOWN, BLOCKED, LOCKED,
    REMOVED, MISTAKE, APPLIED, INVALID,
}

data class Result(
    val outcome: Outcome,
    val line: Line? = null,
    val title: String? = null,
    val barcode: String = "",
    /** Events to append to the outbox (same JSON the server accepts). */
    val events: List<JsonObject> = emptyList(),
    /** Line ids whose state changed (to persist). */
    val changed: Set<Long> = emptySet(),
    val error: String? = null,
)

/**
 * Local checking rules — a port of backend/apps/checking/engine.py, applied to the
 * in-memory order so feedback is instant and works offline. The server re-applies
 * the same rules to the same events and is authoritative.
 */
class CheckEngine(
    private val reasons: () -> List<Reason>,
    private val lookupMapping: (code: String) -> MappedProduct?,
    private val now: () -> OffsetDateTime = { OffsetDateTime.now() },
    private val newId: () -> String = { UUID.randomUUID().toString() },
) {
    private fun event(kind: String, extra: Map<String, Any?> = emptyMap()): JsonObject = buildJsonObject {
        put("id", newId())
        put("kind", kind)
        put("at", now().toString())
        for ((k, v) in extra) when (v) {
            null -> {}
            is String -> put(k, v)
            is Number -> put(k, JsonPrimitive(v))
            is Boolean -> put(k, v)
            else -> put(k, v.toString())
        }
    }

    // --- Resolution -------------------------------------------------------
    /** Priority 1: this order's barcodes (real before repaired). 2: central mapping. */
    fun resolve(m: OrderModel, code: String): Triple<Line?, MappedProduct?, Boolean> {
        val refs = m.codes[code].orEmpty()
        val ids = refs.filter { !it.derived }.map { it.lineId }.ifEmpty { refs.map { it.lineId } }
        if (ids.isNotEmpty()) {
            val lines = ids.mapNotNull { m.lines[it] }.sortedWith(compareBy({ it.aisleRank }, { it.id }))
            val line = lines.firstOrNull { it.boxesScanned < it.packOrdered } ?: lines.firstOrNull()
            if (line != null) return Triple(line, MappedProduct(line.productId, line.title), true)
        }
        val mapped = lookupMapping(code) ?: return Triple(null, null, false)
        return Triple(m.lines.values.firstOrNull { it.productId == mapped.productId }, mapped, false)
    }

    // --- Scan -------------------------------------------------------------
    fun scan(m: OrderModel, raw: String, duplicate: Boolean): Result {
        val code = Barcode.canonical(raw)
        val shown = Barcode.clean(raw)
        if (m.info.locked || m.info.revoked) return Result(Outcome.LOCKED, barcode = shown)
        if (code.isEmpty()) return Result(Outcome.UNKNOWN, barcode = shown)
        if (duplicate) {
            val (line, mapped, _) = resolve(m, code)
            return Result(Outcome.DUPLICATE, line, mapped?.title, shown,
                listOf(event("scan", mapOf("barcode" to raw, "duplicate" to true))))
        }
        if (m.pending != null) return Result(Outcome.BLOCKED, barcode = shown)

        val ev = event("scan", mapOf("barcode" to raw))
        val (line, mapped, _) = resolve(m, code)
        if (mapped == null) return Result(Outcome.UNKNOWN, barcode = shown, events = listOf(ev))
        if (line == null || line.isUnordered) {
            m.pending = Pending(ev.id(), PendingKind.NOT_IN_ORDER, line?.id, mapped.productId, mapped.title, shown)
            return Result(Outcome.NOT_IN_ORDER, line, mapped.title, shown, listOf(ev))
        }
        if (line.boxesScanned >= line.packOrdered) {
            m.pending = Pending(ev.id(), PendingKind.OVER, line.id, line.productId, line.title, shown)
            return Result(Outcome.OVER, line, line.title, shown, listOf(ev))
        }
        line.boxesScanned += 1
        line.lastScanAt = System.currentTimeMillis()
        refresh(line)
        val outcome = if (line.boxesScanned >= line.packOrdered) Outcome.LINE_COMPLETE else Outcome.COUNTED
        return Result(outcome, line, line.title, shown, listOf(ev), setOf(line.id))
    }

    // --- Extra / not-in-order decision --------------------------------------
    fun decide(m: OrderModel, removed: Boolean): Result {
        val p = m.pending ?: return Result(Outcome.INVALID, error = "no_pending")
        val ev = event("extra_decision", mapOf("ref" to p.eventId, "decision" to if (removed) "removed" else "mistake"))
        m.pending = null
        if (!removed) return Result(Outcome.MISTAKE, p.lineId?.let { m.lines[it] }, p.title, p.barcode, listOf(ev))

        val (line, type, defaultFor) = if (p.kind == PendingKind.OVER) {
            Triple(m.lines.getValue(p.lineId!!), DiscType.EXTRA, "extra")
        } else {
            Triple(unorderedLine(m, p), DiscType.NOT_IN_ORDER, "not_in_order")
        }
        line.boxesExtra += 1
        val d = line.discs.getOrPut(type) { Disc(type, 0, null, "", DiscStatus.OPEN) }
        d.qtyBoxes += 1
        if (d.reasonId == null) d.reasonId = reasons().firstOrNull { it.defaultFor == defaultFor }?.id
        d.status = statusFor(d)
        refresh(line)
        return Result(Outcome.REMOVED, line, line.title, p.barcode, listOf(ev), setOf(line.id))
    }

    private fun unorderedLine(m: OrderModel, p: Pending): Line {
        m.lines.values.firstOrNull { it.productId == p.productId }?.let { return it }
        // No server id yet: a temporary negative id until the next sync replaces it.
        val tempId = (m.lines.keys.filter { it < 0 }.minOrNull() ?: 0L) - 1
        val line = Line(tempId, p.productId, p.title, "", 0, 0, 0, 0, 0, LineState.EXTRA, true, emptyList(), null, null)
        m.lines[tempId] = line
        return line
    }

    // --- Shortage, reasons, corrections -------------------------------------
    private fun lineRef(line: Line): Map<String, Any?> =
        if (line.id > 0) mapOf("line_id" to line.id) else mapOf("line_id" to line.id, "product_id" to line.productId)

    private fun reasonFor(id: Long?, type: DiscType, required: Boolean): Pair<Reason?, String?> {
        if (id == null) return null to (if (required) "reason_required" else null)
        val r = reasons().firstOrNull { it.id == id } ?: return null to "invalid_reason"
        return if (r.applies(type)) r to null else null to "reason_not_applicable"
    }

    fun declareShort(m: OrderModel, lineId: Long, reasonId: Long?, note: String?): Result {
        if (m.info.locked || m.info.revoked) return Result(Outcome.LOCKED)
        val line = m.lines[lineId] ?: return Result(Outcome.INVALID, error = "invalid_line")
        if (line.isUnordered) return Result(Outcome.INVALID, error = "line_not_ordered")
        if (line.boxesScanned >= line.packOrdered) return Result(Outcome.INVALID, error = "line_complete")
        val (reason, err) = reasonFor(reasonId, DiscType.SHORT, required = false)
        if (err != null) return Result(Outcome.INVALID, error = err)
        val d = line.discs.getOrPut(DiscType.SHORT) { Disc(DiscType.SHORT, 0, null, "", DiscStatus.OPEN) }
        if (reason != null) d.reasonId = reason.id
        if (note != null) d.note = note.take(500)
        d.status = DiscStatus.OPEN
        refresh(line)
        val ev = event("declare_short", lineRef(line) + mapOf("reason_id" to reason?.id, "note" to note))
        return Result(Outcome.APPLIED, line, line.title, events = listOf(ev), changed = setOf(line.id))
    }

    fun setReason(m: OrderModel, lineId: Long, type: DiscType, reasonId: Long, note: String?): Result {
        if (m.info.locked || m.info.revoked) return Result(Outcome.LOCKED)
        val line = m.lines[lineId] ?: return Result(Outcome.INVALID, error = "invalid_line")
        val d = line.discs[type]
        if (d == null || d.status == DiscStatus.RESOLVED) return Result(Outcome.INVALID, error = "no_discrepancy")
        val (reason, err) = reasonFor(reasonId, type, required = true)
        if (err != null) return Result(Outcome.INVALID, error = err)
        d.reasonId = reason!!.id
        if (note != null) d.note = note.take(500)
        d.status = statusFor(d)
        val ev = event("set_reason", lineRef(line) + mapOf("type" to type.api, "reason_id" to reason.id, "note" to note))
        return Result(Outcome.APPLIED, line, line.title, events = listOf(ev), changed = setOf(line.id))
    }

    fun adjust(m: OrderModel, lineId: Long, boxes: Int, note: String?): Result {
        if (m.info.locked || m.info.revoked) return Result(Outcome.LOCKED)
        val line = m.lines[lineId] ?: return Result(Outcome.INVALID, error = "invalid_line")
        if (line.isUnordered) return Result(Outcome.INVALID, error = "line_not_ordered")
        if (boxes < 0 || boxes > line.packOrdered) return Result(Outcome.INVALID, error = "invalid_quantity")
        line.boxesScanned = boxes
        refresh(line)
        val ev = event("adjust", lineRef(line) + mapOf("boxes" to boxes, "note" to note))
        return Result(Outcome.APPLIED, line, line.title, events = listOf(ev), changed = setOf(line.id))
    }

    // --- Completion -----------------------------------------------------------
    data class Problem(val code: String, val lineId: Long?)

    fun completionProblems(m: OrderModel): List<Problem> = buildList {
        m.pending?.let { add(Problem("pending_decision", it.lineId)) }
        m.orderedLines.filter { it.state == LineState.PENDING || it.state == LineState.PARTIAL }
            .forEach { add(Problem("line_not_checked", it.id)) }
        m.lines.values.forEach { l -> l.discs.values.filter { it.status == DiscStatus.OPEN }.forEach { add(Problem("discrepancy_without_reason", l.id)) } }
    }

    // --- State ---------------------------------------------------------------
    private fun statusFor(d: Disc): DiscStatus {
        if (d.qtyBoxes == 0) return DiscStatus.RESOLVED
        val reason = reasons().firstOrNull { it.id == d.reasonId } ?: return DiscStatus.OPEN
        if (reason.requiresNote && d.note.isBlank()) return DiscStatus.OPEN
        return DiscStatus.REASONED
    }

    /** Same derivation as the server's _refresh_line. */
    fun refresh(line: Line) {
        val short = line.discs[DiscType.SHORT]
        if (short != null && !line.isUnordered && short.status != DiscStatus.RESOLVED) {
            short.qtyBoxes = line.remaining
            short.status = statusFor(short)
        }
        line.state = when {
            line.isUnordered -> LineState.EXTRA
            line.boxesScanned >= line.packOrdered -> LineState.OK
            short != null && short.status != DiscStatus.RESOLVED -> LineState.SHORT
            line.boxesScanned > 0 -> LineState.PARTIAL
            else -> LineState.PENDING
        }
    }
}

private fun JsonObject.id(): String = (this["id"] as JsonPrimitive).content
