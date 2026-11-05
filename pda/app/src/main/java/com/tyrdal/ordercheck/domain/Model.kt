package com.tyrdal.ordercheck.domain

enum class LineState(val api: String) {
    PENDING("pending"), PARTIAL("partial"), OK("ok"), SHORT("short"), EXTRA("extra");

    companion object {
        fun of(api: String) = entries.firstOrNull { it.api == api } ?: PENDING
    }
}

enum class DiscType(val api: String) {
    SHORT("short"), EXTRA("extra"), NOT_IN_ORDER("not_in_order");

    companion object {
        fun of(api: String) = entries.firstOrNull { it.api == api } ?: SHORT
    }
}

enum class DiscStatus(val api: String) {
    OPEN("open"), REASONED("reasoned"), RESOLVED("resolved");

    companion object {
        fun of(api: String) = entries.firstOrNull { it.api == api } ?: OPEN
    }
}

enum class Tab { TO_CHECK, OK, ISSUE }

data class Disc(
    val type: DiscType,
    var qtyBoxes: Int,
    var reasonId: Long?,
    var note: String,
    var status: DiscStatus,
)

class Line(
    val id: Long,
    val productId: String,
    val title: String,
    val aisleTitle: String,
    val aisleRank: Int,
    val packOrdered: Int,
    val inc: Int,
    var boxesScanned: Int,
    var boxesExtra: Int,
    var state: LineState,
    val isUnordered: Boolean,
    val barcodes: List<String>,
    val physicalStock: Int?,
    var lastScanAt: Long?,
    val discs: MutableMap<DiscType, Disc> = mutableMapOf(),
) {
    val remaining: Int get() = (packOrdered - boxesScanned).coerceAtLeast(0)
    val tab: Tab
        get() = when {
            state == LineState.PENDING || state == LineState.PARTIAL -> Tab.TO_CHECK
            state == LineState.OK && boxesExtra == 0 -> Tab.OK
            else -> Tab.ISSUE
        }

    fun activeDiscs(): List<Disc> = discs.values.filter { it.status != DiscStatus.RESOLVED }

    fun copyDeep(): Line = Line(
        id, productId, title, aisleTitle, aisleRank, packOrdered, inc, boxesScanned, boxesExtra, state,
        isUnordered, barcodes, physicalStock, lastScanAt, discs.mapValues { it.value.copy() }.toMutableMap(),
    )
}

data class CodeRef(val lineId: Long, val derived: Boolean)

enum class PendingKind { OVER, NOT_IN_ORDER }

data class Pending(
    val eventId: String,
    val kind: PendingKind,
    val lineId: Long?,
    val productId: String,
    val title: String,
    val barcode: String,
)

data class Reason(
    val id: Long,
    val code: String,
    val nameFa: String,
    val nameEn: String,
    val appliesTo: String, // short | extra | both
    val requiresNote: Boolean,
    val defaultFor: String?, // extra | not_in_order | null
    val sortOrder: Int,
) {
    fun applies(type: DiscType): Boolean = when (appliesTo) {
        "both" -> true
        "short" -> type == DiscType.SHORT
        else -> type == DiscType.EXTRA || type == DiscType.NOT_IN_ORDER
    }

    fun name(lang: String) = if (lang == "fa") nameFa else nameEn
}

data class OrderInfo(
    val id: Long,
    val referenceId: String,
    val customer: String,
    val status: String,
    val version: Int,
    val locked: Boolean,
    val revoked: Boolean,
)

/** A product found in the central barcode mapping (PDA cache). */
data class MappedProduct(val productId: String, val title: String)

class OrderModel(
    var info: OrderInfo,
    val lines: MutableMap<Long, Line>,
    val codes: MutableMap<String, MutableList<CodeRef>>,
    var pending: Pending?,
) {
    val orderedLines get() = lines.values.filter { !it.isUnordered }

    data class Counters(
        val linesTotal: Int, val linesDone: Int, val boxesOrdered: Int, val boxesScanned: Int,
        val openIssues: Int, val issuesTotal: Int, val toCheck: Int, val ok: Int, val issue: Int,
    )

    fun counters(): Counters {
        val ordered = orderedLines
        val done = ordered.count {
            it.state == LineState.OK ||
                (it.state == LineState.SHORT && it.discs[DiscType.SHORT]?.status == DiscStatus.REASONED)
        }
        val discs = lines.values.flatMap { it.discs.values }
        return Counters(
            linesTotal = ordered.size,
            linesDone = done,
            boxesOrdered = ordered.sumOf { it.packOrdered },
            boxesScanned = ordered.sumOf { it.boxesScanned },
            openIssues = discs.count { it.status == DiscStatus.OPEN } + (if (pending != null) 1 else 0),
            issuesTotal = discs.count { it.status != DiscStatus.RESOLVED },
            toCheck = lines.values.count { it.tab == Tab.TO_CHECK },
            ok = lines.values.count { it.tab == Tab.OK },
            issue = lines.values.count { it.tab == Tab.ISSUE },
        )
    }
}
