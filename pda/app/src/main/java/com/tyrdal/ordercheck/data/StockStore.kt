package com.tyrdal.ordercheck.data

import com.tyrdal.ordercheck.data.db.AppDb
import com.tyrdal.ordercheck.data.db.CodeTotal
import com.tyrdal.ordercheck.data.db.StockRecordEntity
import com.tyrdal.ordercheck.domain.Barcode
import java.util.UUID

/**
 * Stocktaking records on the device. Saving is local and instant; SyncManager sends
 * unsynced records in the background. A record keeps its id forever, so edits and
 * deletes are new versions of the same record (newest `updatedAt` wins on the server).
 */
class StockStore(private val db: AppDb) {
    private val dao get() = db.stock()

    /** `titles`: from the stocktake master (0 = not in the master, 2+ = the counter chooses). */
    data class Lookup(val barcode: String, val code: String, val titles: List<String>, val total: CodeTotal)

    suspend fun lookup(taskId: Long, raw: String): Lookup? {
        val barcode = Barcode.clean(raw)
        if (barcode.isEmpty()) return null
        val code = Barcode.canonical(barcode)
        return Lookup(barcode, code, dao.masterTitles(code), dao.totalFor(taskId, code))
    }

    suspend fun add(taskId: Long, l: Lookup, title: String, typed: Boolean, quantity: Int, price: String?): StockRecordEntity {
        val now = System.currentTimeMillis()
        val r = StockRecordEntity(
            id = UUID.randomUUID().toString(), taskId = taskId, barcode = l.barcode, code = l.code, title = title, titleTyped = typed,
            quantity = quantity, price = price, countedAt = now, updatedAt = now, deleted = false, synced = false, error = null,
        )
        dao.upsert(r)
        return r
    }

    suspend fun edit(id: String, quantity: Int, price: String?, title: String) {
        val r = dao.get(id) ?: return
        val typed = r.titleTyped || title != (r.title ?: "")
        dao.upsert(r.copy(quantity = quantity, price = price, title = title, titleTyped = typed, updatedAt = nextTime(r), synced = false, error = null))
    }

    suspend fun delete(id: String) {
        val r = dao.get(id) ?: return
        dao.upsert(r.copy(deleted = true, updatedAt = nextTime(r), synced = false, error = null))
    }

    /** Strictly increasing per record even if the clock jumps back. */
    private fun nextTime(r: StockRecordEntity) = maxOf(System.currentTimeMillis(), r.updatedAt + 1)
}
