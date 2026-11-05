package com.tyrdal.ordercheck.sync

import android.util.Log
import com.tyrdal.ordercheck.data.Api
import com.tyrdal.ordercheck.data.ApiException
import com.tyrdal.ordercheck.data.EventsRequest
import com.tyrdal.ordercheck.data.OfflineException
import com.tyrdal.ordercheck.data.OrderStore
import com.tyrdal.ordercheck.data.Prefs
import com.tyrdal.ordercheck.data.db.AppDb
import com.tyrdal.ordercheck.data.db.BarcodeEntity
import com.tyrdal.ordercheck.data.json
import com.tyrdal.ordercheck.data.toEntity
import com.tyrdal.ordercheck.domain.Reason
import com.tyrdal.ordercheck.data.ReasonDto
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withTimeoutOrNull
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.JsonObject
import java.time.OffsetDateTime

/**
 * Background synchronization:
 * - pushes outbox events in order (batches of up to 200) with the PDA clock as `sent_at`
 *   so the server can correct clock skew;
 * - refreshes the checker's order list and prefetches order snapshots;
 * - keeps the local barcode mapping and discrepancy reasons up to date.
 * Runs continuously while logged in; a failed request just means "offline", nothing is lost.
 */
class SyncManager(
    private val scope: CoroutineScope,
    private val api: Api,
    private val db: AppDb,
    private val store: OrderStore,
    private val prefs: Prefs,
    private val onReasons: (List<Reason>) -> Unit,
) {
    private val _online = MutableStateFlow(true)
    val online: StateFlow<Boolean> = _online
    private val _lastError = MutableStateFlow<String?>(null)
    val lastError: StateFlow<String?> = _lastError
    val pendingEvents = db.outbox().countAll()

    private val wake = Channel<Unit>(Channel.CONFLATED)
    private val pushLock = Mutex()
    private var job: Job? = null
    private var lastOrders = 0L
    private var lastBarcodes = 0L

    fun start() {
        if (job?.isActive == true) return
        job = scope.launch {
            while (true) {
                runCatching { cycle() }.onFailure { Log.w(TAG, "sync cycle", it) }
                withTimeoutOrNull(if (_online.value) 2_000 else 5_000) { wake.receive() }
            }
        }
    }

    fun stop() { job?.cancel(); job = null }

    /** Push now (after a scan) instead of waiting for the next tick. */
    fun trigger() { wake.trySend(Unit) }

    private suspend fun cycle() {
        pushAll()
        val now = System.currentTimeMillis()
        if (now - lastOrders > 30_000) { refreshOrders(); lastOrders = now }
        if (now - lastBarcodes > 5 * 60_000) { if (syncBarcodes()) lastBarcodes = now }
    }

    private suspend inline fun <T> net(block: () -> T): T? = try {
        block().also { _online.value = true; _lastError.value = null }
    } catch (e: OfflineException) {
        _online.value = false; null
    } catch (e: ApiException) {
        _online.value = true; _lastError.value = e.code; null
    }

    suspend fun pushAll() = pushLock.withLock {
        for (orderId in db.outbox().ordersWithEvents()) pushOrder(orderId)
    }

    /** Sends everything queued for one order. Returns true when the outbox for it is empty. */
    suspend fun pushOrder(orderId: Long): Boolean {
        while (true) {
            val batch = db.outbox().batch(orderId, 200)
            if (batch.isEmpty()) return true
            val events = batch.map { json.parseToJsonElement(it.json) as JsonObject }
            val res = try {
                api.events(orderId, EventsRequest(OffsetDateTime.now().toString(), events)).also { _online.value = true }
            } catch (e: OfflineException) {
                _online.value = false; return false
            } catch (e: ApiException) {
                if (e.code == "not_assigned" || e.status == 404) {
                    // This checker never had / no longer has this order: events can never be accepted.
                    Log.w(TAG, "dropping ${batch.size} events for order $orderId: ${e.code}")
                    db.outbox().deleteUpTo(orderId, batch.last().seq)
                    store.markRevoked(orderId)
                    continue
                }
                _lastError.value = e.code
                return false
            }
            db.outbox().deleteUpTo(orderId, batch.last().seq)
            if (res.results.any { it.error == "not_assigned" }) store.markRevoked(orderId)
            if (res.order.locked) store.markLocked(orderId, res.order.status)
            if (db.outbox().count(orderId) == 0) {
                if (!store.applyEventsResponse(orderId, res)) refreshSnapshot(orderId)
            }
        }
    }

    suspend fun refreshSnapshot(orderId: Long): Boolean {
        val s = net { api.snapshot(orderId) } ?: return false
        return store.applySnapshot(s) { pid -> db.barcodes().titleOf(pid) }
    }

    suspend fun refreshOrders(): Boolean {
        val list = net { api.myOrders() } ?: return false
        val dao = db.orders()
        val mine = list.map { it.id }.toSet()
        for (o in list) {
            val prev = dao.get(o.id)
            dao.upsert(o.toEntity(prev).copy(revoked = false))
            // Prefetch so opening is instant; re-download if the order was re-imported (new version).
            if (prev == null || prev.snapshotVersion != o.version) {
                if (db.outbox().count(o.id) == 0) {
                    store.drop(o.id)
                    refreshSnapshot(o.id)
                }
            }
        }
        // Orders no longer assigned to me (reassigned, cancelled, completed elsewhere).
        for (o in dao.all()) {
            if (o.id !in mine && !o.revoked && db.outbox().count(o.id) == 0) dao.upsert(o.copy(revoked = true))
        }
        net { api.config() }?.let { cfg ->
            prefs.debounceMs = cfg.debounceMs
            prefs.reasonsJson = json.encodeToString(ListSerializer(ReasonDto.serializer()), cfg.reasons)
            onReasons(cfg.reasons.map { it.toDomain() })
        }
        return true
    }

    /** Central barcode mapping → local cache (full on first run, then changes only). */
    suspend fun syncBarcodes(): Boolean {
        val since = prefs.barcodeSince
        var afterId = 0L
        var serverTime: String? = null
        while (true) {
            val page = net { api.barcodes(since, afterId) } ?: return false
            serverTime = serverTime ?: page.serverTime
            val (active, inactive) = page.barcodes.partition { it.active }
            db.barcodes().upsert(active.map { BarcodeEntity(it.code, it.productId, it.title) })
            // A deactivated row only removes the cache entry if no active row for that code arrived.
            val activeCodes = active.map { it.code }.toSet()
            inactive.map { it.code }.filter { it !in activeCodes }.chunked(500).forEach { db.barcodes().delete(it) }
            if (!page.hasMore) break
            afterId = page.nextAfterId
            delay(10)
        }
        prefs.barcodeSince = serverTime
        return true
    }

    companion object { private const val TAG = "Sync" }
}

fun ReasonDto.toDomain() = Reason(id, code, nameFa, nameEn, appliesTo, requiresNote, defaultFor, sortOrder)
