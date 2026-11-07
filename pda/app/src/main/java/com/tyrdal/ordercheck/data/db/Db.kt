package com.tyrdal.ordercheck.data.db

import android.content.Context
import androidx.room.AutoMigration
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Index
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Upsert
import kotlinx.coroutines.flow.Flow

@Entity(tableName = "orders")
data class OrderEntity(
    @PrimaryKey val id: Long,
    val referenceId: String,
    val customer: String,
    val status: String,
    val version: Int,
    val linesTotal: Int,
    val linesDone: Int,
    val boxesOrdered: Int,
    val boxesScanned: Int,
    val openIssues: Int,
    val issuesTotal: Int,
    val locked: Boolean,
    /** No longer assigned to this checker (reassigned/cancelled on the server). */
    val revoked: Boolean,
    /** Version of the downloaded lines; 0 = not downloaded yet. */
    val snapshotVersion: Int,
    val sortKey: Long,
)

@Entity(tableName = "lines", indices = [Index("orderId")])
data class LineEntity(
    @PrimaryKey val id: Long,
    val orderId: Long,
    val productId: String,
    val title: String,
    val aisleTitle: String,
    val aisleRank: Int,
    val packOrdered: Int,
    val inc: Int,
    val boxesScanned: Int,
    val boxesExtra: Int,
    val state: String,
    val isUnordered: Boolean,
    val barcodes: String, // display values, '\n'-separated
    val physicalStock: Int?,
    val lastScanAt: Long?,
)

@Entity(tableName = "discs", primaryKeys = ["lineId", "type"], indices = [Index("orderId")])
data class DiscEntity(
    val lineId: Long,
    val orderId: Long,
    val type: String,
    val qtyBoxes: Int,
    val reasonId: Long?,
    val note: String,
    val status: String,
)

@Entity(tableName = "line_codes", primaryKeys = ["orderId", "code", "lineId"])
data class LineCodeEntity(val orderId: Long, val code: String, val lineId: Long, val derived: Boolean)

@Entity(tableName = "pending")
data class PendingEntity(
    @PrimaryKey val orderId: Long,
    val eventId: String,
    val kind: String,
    val lineId: Long?,
    val productId: String,
    val title: String,
    val barcode: String,
)

/** Events waiting to be sent, in order. Never lost: removed only after the server accepted them. */
@Entity(tableName = "outbox", indices = [Index("orderId")])
data class OutboxEntity(
    @PrimaryKey(autoGenerate = true) val seq: Long = 0,
    val orderId: Long,
    val eventId: String,
    val json: String,
    val createdAt: Long,
)

/** Local copy of the central barcode mapping (active rows only). */
@Entity(tableName = "barcodes")
data class BarcodeEntity(@PrimaryKey val code: String, val productId: String, val title: String)

/** A stocktake (vendor + date) this counter is assigned to. `active` = still in my list on the server. */
@Entity(tableName = "stock_tasks")
data class StockTaskEntity(
    @PrimaryKey val id: Long,
    val vendor: String,
    val vendorCode: String,
    val date: String, // YYYY-MM-DD
    val status: String,
    val note: String,
    val countable: Boolean,
    val serverRecords: Int,
    val active: Boolean,
)

/** One count entry. Kept forever locally; `synced` = the server has this exact version. */
@Entity(tableName = "stock_records", indices = [Index("taskId"), Index("synced")])
data class StockRecordEntity(
    @PrimaryKey val id: String,
    val taskId: Long,
    val barcode: String,
    val code: String,
    val title: String?,
    val quantity: Int,
    val price: String?,
    val countedAt: Long,
    val updatedAt: Long,
    val deleted: Boolean,
    val synced: Boolean,
    /** Rejected by the server (e.g. stocktake closed); not retried until the task is open again. */
    val error: String?,
)

data class CodeTotal(val records: Int, val quantity: Int)

@Dao
interface StockDao {
    @Query("SELECT * FROM stock_tasks WHERE active = 1 ORDER BY date, vendor") fun tasks(): Flow<List<StockTaskEntity>>
    @Query("SELECT * FROM stock_tasks WHERE id = :id") fun task(id: Long): Flow<StockTaskEntity?>
    @Query("SELECT * FROM stock_tasks WHERE id = :id") suspend fun getTask(id: Long): StockTaskEntity?
    @Upsert suspend fun upsertTasks(t: List<StockTaskEntity>)
    /** Gone from my list on the server (closed, or I was removed): no more counting on this device. */
    @Query("UPDATE stock_tasks SET active = 0, countable = 0, status = 'closed' WHERE id NOT IN (:ids) AND active = 1")
    suspend fun deactivateExcept(ids: List<Long>)
    @Query("UPDATE stock_tasks SET status = :status, countable = 0 WHERE id = :id") suspend fun markNotCountable(id: Long, status: String)

    @Query("SELECT * FROM stock_records WHERE taskId = :taskId AND deleted = 0 ORDER BY countedAt DESC")
    fun records(taskId: Long): Flow<List<StockRecordEntity>>
    @Query("SELECT COUNT(*) FROM stock_records WHERE taskId = :taskId") suspend fun countAll(taskId: Long): Int
    @Query("SELECT COUNT(*) AS records, COALESCE(SUM(quantity), 0) AS quantity FROM stock_records WHERE taskId = :taskId AND code = :code AND deleted = 0")
    suspend fun totalFor(taskId: Long, code: String): CodeTotal
    @Query("SELECT * FROM stock_records WHERE id = :id") suspend fun get(id: String): StockRecordEntity?
    @Upsert suspend fun upsert(r: StockRecordEntity)
    @Insert(onConflict = OnConflictStrategy.IGNORE) suspend fun insertIfAbsent(r: List<StockRecordEntity>)

    @Query("SELECT * FROM stock_records WHERE synced = 0 AND error IS NULL ORDER BY updatedAt LIMIT :limit")
    suspend fun unsynced(limit: Int): List<StockRecordEntity>
    @Query("SELECT COUNT(*) FROM stock_records WHERE synced = 0") fun unsyncedCount(): Flow<Int>
    @Query("SELECT COUNT(*) FROM stock_records WHERE taskId = :taskId AND synced = 0") fun unsyncedFor(taskId: Long): Flow<Int>
    /** Only if not edited again meanwhile. */
    @Query("UPDATE stock_records SET synced = 1, error = NULL WHERE id = :id AND updatedAt = :updatedAt")
    suspend fun markSynced(id: String, updatedAt: Long)
    @Query("UPDATE stock_records SET error = :error WHERE id = :id") suspend fun setError(id: String, error: String)
    @Query("UPDATE stock_records SET error = :error WHERE taskId = :taskId AND synced = 0") suspend fun setErrorForTask(taskId: Long, error: String)
    @Query("UPDATE stock_records SET error = NULL WHERE taskId = :taskId AND synced = 0") suspend fun clearErrors(taskId: Long)
}

@Dao
interface OrderDao {
    @Query("SELECT * FROM orders WHERE revoked = 0 AND status IN ('assigned','in_progress') ORDER BY sortKey, id")
    fun activeOrders(): Flow<List<OrderEntity>>

    @Query("SELECT * FROM orders WHERE id = :id") suspend fun get(id: Long): OrderEntity?
    @Query("SELECT * FROM orders") suspend fun all(): List<OrderEntity>
    @Upsert suspend fun upsert(o: OrderEntity)
    @Query("DELETE FROM orders WHERE id = :id") suspend fun delete(id: Long)

    @Query("SELECT * FROM lines WHERE orderId = :orderId") suspend fun lines(orderId: Long): List<LineEntity>
    @Upsert suspend fun upsertLines(l: List<LineEntity>)
    @Query("DELETE FROM lines WHERE orderId = :orderId") suspend fun deleteLines(orderId: Long)
    @Query("DELETE FROM lines WHERE id = :id") suspend fun deleteLine(id: Long)

    @Query("SELECT * FROM discs WHERE orderId = :orderId") suspend fun discs(orderId: Long): List<DiscEntity>
    @Upsert suspend fun upsertDiscs(d: List<DiscEntity>)
    @Query("DELETE FROM discs WHERE orderId = :orderId") suspend fun deleteDiscs(orderId: Long)
    @Query("DELETE FROM discs WHERE lineId = :lineId") suspend fun deleteDiscsOfLine(lineId: Long)

    @Query("SELECT * FROM line_codes WHERE orderId = :orderId") suspend fun codes(orderId: Long): List<LineCodeEntity>
    @Insert(onConflict = OnConflictStrategy.REPLACE) suspend fun insertCodes(c: List<LineCodeEntity>)
    @Query("DELETE FROM line_codes WHERE orderId = :orderId") suspend fun deleteCodes(orderId: Long)

    @Query("SELECT * FROM pending WHERE orderId = :orderId") suspend fun pending(orderId: Long): PendingEntity?
    @Upsert suspend fun upsertPending(p: PendingEntity)
    @Query("DELETE FROM pending WHERE orderId = :orderId") suspend fun deletePending(orderId: Long)
}

@Dao
interface OutboxDao {
    @Insert suspend fun insert(e: List<OutboxEntity>)
    @Query("SELECT * FROM outbox WHERE orderId = :orderId ORDER BY seq LIMIT :limit") suspend fun batch(orderId: Long, limit: Int): List<OutboxEntity>
    @Query("SELECT DISTINCT orderId FROM outbox") suspend fun ordersWithEvents(): List<Long>
    @Query("SELECT COUNT(*) FROM outbox WHERE orderId = :orderId") suspend fun count(orderId: Long): Int
    @Query("SELECT COUNT(*) FROM outbox") fun countAll(): Flow<Int>
    @Query("DELETE FROM outbox WHERE seq <= :maxSeq AND orderId = :orderId") suspend fun deleteUpTo(orderId: Long, maxSeq: Long)
}

@Dao
interface BarcodeDao {
    @Query("SELECT * FROM barcodes WHERE code = :code") suspend fun get(code: String): BarcodeEntity?
    @Query("SELECT * FROM barcodes WHERE code = :code") fun getBlocking(code: String): BarcodeEntity?
    @Query("SELECT title FROM barcodes WHERE productId = :productId LIMIT 1") suspend fun titleOf(productId: String): String?
    @Upsert suspend fun upsert(b: List<BarcodeEntity>)
    @Query("DELETE FROM barcodes WHERE code IN (:codes)") suspend fun delete(codes: List<String>)
    @Query("SELECT COUNT(*) FROM barcodes") suspend fun count(): Int
}

@Database(
    entities = [OrderEntity::class, LineEntity::class, DiscEntity::class, LineCodeEntity::class, PendingEntity::class,
        OutboxEntity::class, BarcodeEntity::class, StockTaskEntity::class, StockRecordEntity::class],
    version = 2,
    exportSchema = true,
    autoMigrations = [AutoMigration(from = 1, to = 2)],
)
abstract class AppDb : RoomDatabase() {
    abstract fun orders(): OrderDao
    abstract fun outbox(): OutboxDao
    abstract fun barcodes(): BarcodeDao
    abstract fun stock(): StockDao

    companion object {
        fun create(context: Context): AppDb =
            Room.databaseBuilder(context, AppDb::class.java, "ordercheck.db").build()
    }
}
