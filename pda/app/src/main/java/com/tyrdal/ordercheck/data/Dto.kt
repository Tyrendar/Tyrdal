package com.tyrdal.ordercheck.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

@Serializable
data class UserDto(
    val id: Long,
    val username: String,
    @SerialName("full_name") val fullName: String = "",
    val role: String,
    val permissions: List<String> = emptyList(),
)

@Serializable
data class LoginRequest(
    val username: String,
    val password: String,
    @SerialName("device_serial") val deviceSerial: String,
    @SerialName("device_model") val deviceModel: String,
    @SerialName("app_version") val appVersion: String,
)

@Serializable
data class LoginResponse(val access: String, val refresh: String, val user: UserDto)

@Serializable
data class RefreshResponse(val access: String, val refresh: String? = null)

@Serializable
data class OrderSummaryDto(
    val id: Long,
    @SerialName("reference_id") val referenceId: String,
    @SerialName("reference_type") val referenceType: String = "",
    val version: Int = 1,
    val customer: String = "",
    val status: String,
    @SerialName("lines_total") val linesTotal: Int = 0,
    @SerialName("lines_done") val linesDone: Int = 0,
    @SerialName("boxes_ordered") val boxesOrdered: Int = 0,
    @SerialName("boxes_scanned") val boxesScanned: Int = 0,
    @SerialName("open_issues") val openIssues: Int = 0,
    @SerialName("issues_total") val issuesTotal: Int = 0,
    @SerialName("is_mine") val isMine: Boolean = true,
    val locked: Boolean = false,
)

@Serializable
data class DiscDto(
    val type: String,
    @SerialName("qty_boxes") val qtyBoxes: Int,
    @SerialName("reason_id") val reasonId: Long? = null,
    val note: String = "",
    val status: String,
)

@Serializable
data class CodeDto(val code: String, val derived: Boolean = false)

@Serializable
data class LineDto(
    val id: Long,
    @SerialName("product_id") val productId: String,
    val title: String,
    @SerialName("aisle_title") val aisleTitle: String = "",
    @SerialName("aisle_rank") val aisleRank: Int = 0,
    @SerialName("pack_ordered") val packOrdered: Int,
    @SerialName("inc_ordered") val inc: Int,
    @SerialName("physical_stock") val physicalStock: Int? = null,
    @SerialName("is_unordered") val isUnordered: Boolean = false,
    @SerialName("boxes_scanned") val boxesScanned: Int = 0,
    @SerialName("boxes_extra") val boxesExtra: Int = 0,
    val state: String = "pending",
    val barcodes: List<String> = emptyList(),
    val discrepancies: List<DiscDto> = emptyList(),
    val codes: List<CodeDto>? = null,
)

@Serializable
data class PendingDto(
    val id: String,
    val result: String,
    @SerialName("line_id") val lineId: Long? = null,
    @SerialName("product_id") val productId: String? = null,
    val barcode: String = "",
)

@Serializable
data class SnapshotDto(val order: OrderSummaryDto, val lines: List<LineDto>, val pending: List<PendingDto> = emptyList())

@Serializable
data class EventResultDto(
    val id: String? = null,
    val result: String,
    val error: String? = null,
    @SerialName("line_id") val lineId: Long? = null,
)

@Serializable
data class EventsRequest(@SerialName("sent_at") val sentAt: String, val events: List<JsonObject>)

@Serializable
data class EventsResponse(
    val results: List<EventResultDto>,
    val lines: List<LineDto> = emptyList(),
    val order: OrderSummaryDto,
    val pending: List<PendingDto> = emptyList(),
)

@Serializable
data class ReasonDto(
    val id: Long,
    val code: String,
    @SerialName("name_fa") val nameFa: String,
    @SerialName("name_en") val nameEn: String,
    @SerialName("applies_to") val appliesTo: String,
    @SerialName("requires_note") val requiresNote: Boolean = false,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("default_for") val defaultFor: String? = null,
)

@Serializable
data class ConfigDto(
    @SerialName("debounce_ms") val debounceMs: Int = 700,
    val reasons: List<ReasonDto> = emptyList(),
)

@Serializable
data class BarcodeDto(
    val id: Long,
    val code: String,
    @SerialName("product_id") val productId: String,
    val title: String,
    val active: Boolean,
)

@Serializable
data class BarcodesResponse(
    @SerialName("server_time") val serverTime: String,
    @SerialName("has_more") val hasMore: Boolean,
    @SerialName("next_after_id") val nextAfterId: Long,
    val barcodes: List<BarcodeDto>,
)

@Serializable
data class FinishResponse(val order: OrderSummaryDto)

@Serializable
data class ProblemDto(val code: String, @SerialName("line_id") val lineId: Long? = null)

@Serializable
data class ErrorDto(val code: String = "error", val detail: String = "", val data: JsonObject? = null)

// --- Stocktaking ---------------------------------------------------------------------
@Serializable
data class StocktakeDto(
    val id: Long,
    val vendor: String,
    @SerialName("vendor_code") val vendorCode: String = "",
    val date: String,
    val status: String,
    val note: String = "",
    val countable: Boolean,
    @SerialName("my_records") val myRecords: Int = 0,
    @SerialName("my_quantity") val myQuantity: Int = 0,
)

@Serializable
data class StockRecordDto(
    val id: String,
    val barcode: String,
    val quantity: Int,
    /** Sent as text ("1200.5"); the server returns a number. */
    val price: kotlinx.serialization.json.JsonPrimitive? = null,
    @SerialName("counted_at") val countedAt: String,
    @SerialName("updated_at") val updatedAt: String,
    val deleted: Boolean = false,
)

@Serializable
data class StockPushRequest(@SerialName("sent_at") val sentAt: String, val records: List<StockRecordDto>)

@Serializable
data class StockRejectDto(val id: String? = null, val error: String)

@Serializable
data class StockPushResponse(val accepted: List<String>, val rejected: List<StockRejectDto> = emptyList(), val stocktake: StocktakeDto)

@Serializable
data class StockRecordsResponse(val stocktake: StocktakeDto, val records: List<StockRecordDto>)
