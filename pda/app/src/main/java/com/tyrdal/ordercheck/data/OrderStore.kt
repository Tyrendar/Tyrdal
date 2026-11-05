package com.tyrdal.ordercheck.data

import androidx.room.withTransaction
import com.tyrdal.ordercheck.data.db.AppDb
import com.tyrdal.ordercheck.data.db.DiscEntity
import com.tyrdal.ordercheck.data.db.LineCodeEntity
import com.tyrdal.ordercheck.data.db.LineEntity
import com.tyrdal.ordercheck.data.db.OrderEntity
import com.tyrdal.ordercheck.data.db.OutboxEntity
import com.tyrdal.ordercheck.data.db.PendingEntity
import com.tyrdal.ordercheck.domain.CheckEngine
import com.tyrdal.ordercheck.domain.CodeRef
import com.tyrdal.ordercheck.domain.Disc
import com.tyrdal.ordercheck.domain.DiscStatus
import com.tyrdal.ordercheck.domain.DiscType
import com.tyrdal.ordercheck.domain.Line
import com.tyrdal.ordercheck.domain.LineState
import com.tyrdal.ordercheck.domain.OrderInfo
import com.tyrdal.ordercheck.domain.OrderModel
import com.tyrdal.ordercheck.domain.Pending
import com.tyrdal.ordercheck.domain.PendingKind
import com.tyrdal.ordercheck.domain.Result
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonPrimitive

/**
 * One order's live state. All changes — checker actions and server updates — go
 * through [mutex], so a server refresh can never overwrite a scan that has not
 * been sent yet.
 */
class OrderSession(val orderId: Long, private val db: AppDb, val model: OrderModel) {
    val mutex = Mutex()
    private val _revision = MutableStateFlow(0L)
    /** Bumped after every change; the UI rebuilds its view from [model]. */
    val revision: StateFlow<Long> = _revision

    internal fun bump() { _revision.value = _revision.value + 1 }

    /** Run a checker action through the engine and persist its effects atomically. */
    suspend fun act(block: (OrderModel) -> Result): Result = mutex.withLock {
        val r = block(model)
        persist(r)
        bump()
        r
    }

    private suspend fun persist(r: Result) {
        if (r.events.isEmpty() && r.changed.isEmpty()) return
        val now = System.currentTimeMillis()
        db.withTransaction {
            val dao = db.orders()
            val lines = r.changed.mapNotNull { model.lines[it] }
            dao.upsertLines(lines.map { it.toEntity(orderId) })
            lines.forEach { l ->
                dao.deleteDiscsOfLine(l.id)
                dao.upsertDiscs(l.discs.values.map { it.toEntity(l.id, orderId) })
            }
            val p = model.pending
            if (p == null) dao.deletePending(orderId) else dao.upsertPending(p.toEntity(orderId))
            db.outbox().insert(r.events.map {
                OutboxEntity(orderId = orderId, eventId = (it["id"] as JsonPrimitive).content, json = it.toString(), createdAt = now)
            })
            dao.get(orderId)?.let { o -> dao.upsert(o.withCounters(model)) }
        }
    }
}

class OrderStore(private val db: AppDb, private val engineFactory: () -> CheckEngine) {
    private val sessions = mutableMapOf<Long, OrderSession>()
    private val lock = Mutex()
    val engine: CheckEngine by lazy { engineFactory() }

    suspend fun session(orderId: Long): OrderSession? = lock.withLock {
        sessions[orderId]?.let { return it }
        val model = load(orderId) ?: return null
        OrderSession(orderId, db, model).also { sessions[orderId] = it }
    }

    suspend fun drop(orderId: Long) = lock.withLock { sessions.remove(orderId) }

    private suspend fun load(orderId: Long): OrderModel? {
        val dao = db.orders()
        val o = dao.get(orderId) ?: return null
        if (o.snapshotVersion == 0) return null
        val discs = dao.discs(orderId).groupBy { it.lineId }
        val lines = dao.lines(orderId).associate { e ->
            e.id to Line(
                e.id, e.productId, e.title, e.aisleTitle, e.aisleRank, e.packOrdered, e.inc, e.boxesScanned, e.boxesExtra,
                LineState.of(e.state), e.isUnordered, e.barcodes.split('\n').filter { it.isNotBlank() }, e.physicalStock, e.lastScanAt,
                discs[e.id].orEmpty().associate { d -> DiscType.of(d.type) to Disc(DiscType.of(d.type), d.qtyBoxes, d.reasonId, d.note, DiscStatus.of(d.status)) }.toMutableMap(),
            )
        }.toMutableMap()
        val codes = mutableMapOf<String, MutableList<CodeRef>>()
        dao.codes(orderId).forEach { codes.getOrPut(it.code) { mutableListOf() }.add(CodeRef(it.lineId, it.derived)) }
        val pending = dao.pending(orderId)?.let {
            Pending(it.eventId, PendingKind.valueOf(it.kind), it.lineId, it.productId, it.title, it.barcode)
        }
        return OrderModel(o.toInfo(), lines, codes, pending)
    }

    /**
     * Replace local lines with the server's, but only when nothing is waiting in
     * the outbox for this order (otherwise local state is newer than the server's).
     * Returns false if skipped.
     */
    suspend fun applySnapshot(s: SnapshotDto, titleOf: suspend (String) -> String?): Boolean {
        val orderId = s.order.id
        val session = lock.withLock { sessions[orderId] }
        val run: suspend () -> Boolean = run@{
            if (db.outbox().count(orderId) > 0) return@run false
            val pending = s.pending.firstOrNull()?.let { p ->
                val title = p.lineId?.let { id -> s.lines.firstOrNull { it.id == id }?.title } ?: p.productId?.let { titleOf(it) } ?: ""
                PendingEntity(orderId, p.id, if (p.result == "over_pending") "OVER" else "NOT_IN_ORDER", p.lineId, p.productId ?: "", title, p.barcode)
            }
            db.withTransaction {
                val dao = db.orders()
                dao.deleteLines(orderId); dao.deleteDiscs(orderId); dao.deleteCodes(orderId); dao.deletePending(orderId)
                dao.upsertLines(s.lines.map { it.toEntity(orderId) })
                dao.upsertDiscs(s.lines.flatMap { l -> l.discrepancies.map { DiscEntity(l.id, orderId, it.type, it.qtyBoxes, it.reasonId, it.note, it.status) } })
                dao.insertCodes(s.lines.flatMap { l -> l.codes.orEmpty().map { LineCodeEntity(orderId, it.code, l.id, it.derived) } })
                pending?.let { dao.upsertPending(it) }
                val prev = dao.get(orderId)
                dao.upsert(s.order.toEntity(prev).copy(snapshotVersion = s.order.version))
            }
            true
        }
        if (session == null) return run()
        return session.mutex.withLock {
            val ok = run()
            if (ok) {
                val fresh = load(orderId)
                if (fresh != null) {
                    session.model.info = fresh.info
                    session.model.lines.clear(); session.model.lines.putAll(fresh.lines)
                    session.model.codes.clear(); session.model.codes.putAll(fresh.codes)
                    session.model.pending = fresh.pending
                }
                session.bump()
            }
            ok
        }
    }

    /** After a successful event push with an empty outbox: take the server's view of the touched lines. */
    suspend fun applyEventsResponse(orderId: Long, r: EventsResponse): Boolean {
        val session = lock.withLock { sessions[orderId] } ?: run {
            // Not open on screen: just store order counters.
            db.orders().get(orderId)?.let { db.orders().upsert(r.order.toEntity(it).copy(snapshotVersion = it.snapshotVersion)) }
            return true
        }
        return session.mutex.withLock {
            if (db.outbox().count(orderId) > 0) return@withLock false
            // A line created offline (negative id) now exists on the server: caller must refetch the snapshot.
            if (session.model.lines.keys.any { it < 0 }) return@withLock false
            db.withTransaction {
                val dao = db.orders()
                for (l in r.lines) {
                    val local = session.model.lines[l.id] ?: continue
                    local.boxesScanned = l.boxesScanned
                    local.boxesExtra = l.boxesExtra
                    local.state = LineState.of(l.state)
                    local.discs.clear()
                    l.discrepancies.forEach { d -> local.discs[DiscType.of(d.type)] = Disc(DiscType.of(d.type), d.qtyBoxes, d.reasonId, d.note, DiscStatus.of(d.status)) }
                    dao.upsertLines(listOf(local.toEntity(orderId)))
                    dao.deleteDiscsOfLine(local.id)
                    dao.upsertDiscs(local.discs.values.map { it.toEntity(local.id, orderId) })
                }
                val o = dao.get(orderId)
                val entity = r.order.toEntity(o).copy(snapshotVersion = o?.snapshotVersion ?: r.order.version)
                dao.upsert(entity)
                session.model.info = entity.toInfo()
            }
            session.bump()
            true
        }
    }

    suspend fun markRevoked(orderId: Long) {
        db.orders().get(orderId)?.let { db.orders().upsert(it.copy(revoked = true)) }
        lock.withLock { sessions[orderId] }?.let { s ->
            s.mutex.withLock { s.model.info = s.model.info.copy(revoked = true); s.bump() }
        }
    }

    suspend fun markLocked(orderId: Long, status: String) {
        db.orders().get(orderId)?.let { db.orders().upsert(it.copy(locked = true, status = status)) }
        lock.withLock { sessions[orderId] }?.let { s ->
            s.mutex.withLock { s.model.info = s.model.info.copy(locked = true, status = status); s.bump() }
        }
    }
}

// --- Mapping helpers ----------------------------------------------------------
fun Line.toEntity(orderId: Long) = LineEntity(
    id, orderId, productId, title, aisleTitle, aisleRank, packOrdered, inc, boxesScanned, boxesExtra, state.api,
    isUnordered, barcodes.joinToString("\n"), physicalStock, lastScanAt,
)

fun Disc.toEntity(lineId: Long, orderId: Long) = DiscEntity(lineId, orderId, type.api, qtyBoxes, reasonId, note, status.api)

fun Pending.toEntity(orderId: Long) = PendingEntity(orderId, eventId, kind.name, lineId, productId, title, barcode)

fun LineDto.toEntity(orderId: Long) = LineEntity(
    id, orderId, productId, title, aisleTitle, aisleRank, packOrdered, inc, boxesScanned, boxesExtra, state,
    isUnordered, barcodes.joinToString("\n"), physicalStock, null,
)

fun OrderSummaryDto.toEntity(prev: OrderEntity?) = OrderEntity(
    id = id, referenceId = referenceId, customer = customer, status = status, version = version,
    linesTotal = linesTotal, linesDone = linesDone, boxesOrdered = boxesOrdered, boxesScanned = boxesScanned,
    openIssues = openIssues, issuesTotal = issuesTotal, locked = locked,
    revoked = !isMine, snapshotVersion = prev?.snapshotVersion ?: 0, sortKey = prev?.sortKey ?: id,
)

fun OrderEntity.toInfo() = OrderInfo(id, referenceId, customer, status, version, locked, revoked)

fun OrderEntity.withCounters(m: OrderModel): OrderEntity {
    val c = m.counters()
    return copy(
        linesTotal = c.linesTotal, linesDone = c.linesDone, boxesOrdered = c.boxesOrdered, boxesScanned = c.boxesScanned,
        openIssues = c.openIssues, issuesTotal = c.issuesTotal,
        status = if (status == "assigned" && c.boxesScanned > 0) "in_progress" else status,
    )
}
