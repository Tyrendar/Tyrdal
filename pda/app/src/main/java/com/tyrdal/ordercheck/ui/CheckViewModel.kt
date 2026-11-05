package com.tyrdal.ordercheck.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.tyrdal.ordercheck.App
import com.tyrdal.ordercheck.data.ApiException
import com.tyrdal.ordercheck.data.OfflineException
import com.tyrdal.ordercheck.data.OrderSession
import com.tyrdal.ordercheck.domain.CheckEngine
import com.tyrdal.ordercheck.domain.DiscType
import com.tyrdal.ordercheck.domain.Line
import com.tyrdal.ordercheck.domain.OrderInfo
import com.tyrdal.ordercheck.domain.OrderModel
import com.tyrdal.ordercheck.domain.Outcome
import com.tyrdal.ordercheck.domain.Pending
import com.tyrdal.ordercheck.domain.Result
import com.tyrdal.ordercheck.domain.Tab
import com.tyrdal.ordercheck.scanner.ScanInput
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** Immutable snapshot of the order for the UI (rebuilt after every change; 600 lines take ~1 ms). */
data class CheckView(
    val info: OrderInfo,
    val counters: OrderModel.Counters,
    val toCheck: List<Line>,
    val ok: List<Line>,
    val issue: List<Line>,
    val pending: Pending?,
    val problems: List<CheckEngine.Problem>,
    val revision: Long,
)

data class LastScan(val outcome: Outcome, val title: String?, val barcode: String, val line: Line?, val at: Long = System.currentTimeMillis())

sealed interface FinishState {
    data object Idle : FinishState
    data object Working : FinishState
    data object Done : FinishState
    data class Failed(val reason: String) : FinishState
}

class CheckViewModel(private val app: App, val orderId: Long) : ViewModel() {
    private var session: OrderSession? = null
    private val engine get() = app.store.engine

    private val _view = MutableStateFlow<CheckView?>(null)
    val view: StateFlow<CheckView?> = _view
    private val _last = MutableStateFlow<LastScan?>(null)
    val last: StateFlow<LastScan?> = _last
    private val _missing = MutableStateFlow(false)
    val missing: StateFlow<Boolean> = _missing
    private val _finish = MutableStateFlow<FinishState>(FinishState.Idle)
    val finish: StateFlow<FinishState> = _finish

    init {
        viewModelScope.launch(Dispatchers.IO) {
            var s = app.store.session(orderId)
            if (s == null && app.sync.refreshSnapshot(orderId)) s = app.store.session(orderId)
            if (s == null) { _missing.value = true; return@launch }
            session = s
            s.revision.collect { rev -> _view.value = build(s.model, rev) }
        }
    }

    private suspend fun build(m: OrderModel, rev: Long): CheckView = session!!.mutex.withLock {
        // Copied under the session lock so the UI never sees a line mid-update.
        val lines = m.lines.values.map { it.copyDeep() }
        CheckView(
            info = m.info,
            counters = m.counters(),
            toCheck = lines.filter { it.tab == Tab.TO_CHECK }.sortedWith(compareBy({ it.aisleRank }, { it.id })),
            ok = lines.filter { it.tab == Tab.OK }.sortedByDescending { it.lastScanAt ?: 0 },
            issue = lines.filter { it.tab == Tab.ISSUE }.sortedWith(compareBy({ it.activeDiscs().none { d -> d.status.api == "open" } }, { it.aisleRank })),
            pending = m.pending,
            problems = engine.completionProblems(m),
            revision = rev,
        )
    }

    private fun run(showAsScan: Boolean = false, block: (OrderModel) -> Result) {
        val s = session ?: return
        viewModelScope.launch(Dispatchers.IO) {
            val r = s.act(block)
            app.feedback.play(r.outcome)
            if (showAsScan || r.outcome in setOf(Outcome.REMOVED, Outcome.MISTAKE)) {
                _last.value = LastScan(r.outcome, r.title, r.barcode, r.line?.copyDeep())
            }
            if (r.events.isNotEmpty()) app.sync.trigger()
        }
    }

    fun onScan(input: ScanInput) = run(showAsScan = true) { engine.scan(it, input.raw, input.duplicate) }
    fun manualBarcode(raw: String) = run(showAsScan = true) { engine.scan(it, raw, duplicate = false) }
    fun decide(removed: Boolean) = run { engine.decide(it, removed) }
    fun declareShort(lineId: Long, reasonId: Long?, note: String?) = run { engine.declareShort(it, lineId, reasonId, note) }
    fun setReason(lineId: Long, type: DiscType, reasonId: Long, note: String?) = run { engine.setReason(it, lineId, type, reasonId, note) }
    fun adjust(lineId: Long, boxes: Int, note: String?) = run { engine.adjust(it, lineId, boxes, note) }

    fun declareShortMany(lineIds: Collection<Long>, reasonId: Long, note: String?) {
        val s = session ?: return
        val ids = lineIds.toList()
        viewModelScope.launch(Dispatchers.IO) {
            // One transaction and one screen update for the whole selection (hundreds of items at once).
            s.act { m ->
                val rs = ids.map { engine.declareShort(m, it, reasonId, note) }
                Result(Outcome.APPLIED, events = rs.flatMap { it.events }, changed = rs.flatMap { it.changed }.toSet())
            }
            app.feedback.play(Outcome.APPLIED)
            app.sync.trigger()
        }
    }

    /** Send everything, then ask the server to complete. Requires the network. */
    fun complete() {
        viewModelScope.launch {
            _finish.value = FinishState.Working
            _finish.value = withContext(Dispatchers.IO) {
                try {
                    if (!app.sync.pushOrder(orderId)) return@withContext FinishState.Failed("offline")
                    val r = app.api.finish(orderId)
                    app.store.markLocked(orderId, r.order.status)
                    app.sync.refreshOrders()
                    FinishState.Done
                } catch (e: OfflineException) {
                    FinishState.Failed("offline")
                } catch (e: ApiException) {
                    // Server state differs (e.g. supervisor changed something): reload and let the checker review.
                    if (e.code == "cannot_complete") app.sync.refreshSnapshot(orderId)
                    FinishState.Failed(e.code)
                }
            }
        }
    }

    fun resetFinish() { _finish.value = FinishState.Idle }
}
