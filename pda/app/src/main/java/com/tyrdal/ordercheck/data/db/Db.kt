package com.tyrdal.ordercheck.data.db

import android.content.Context
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
        OutboxEntity::class, BarcodeEntity::class],
    version = 1,
    exportSchema = true,
)
abstract class AppDb : RoomDatabase() {
    abstract fun orders(): OrderDao
    abstract fun outbox(): OutboxDao
    abstract fun barcodes(): BarcodeDao

    companion object {
        fun create(context: Context): AppDb =
            Room.databaseBuilder(context, AppDb::class.java, "ordercheck.db").build()
    }
}
