package com.tyrdal.ordercheck.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** HTTP error from the server, with its stable error `code`. */
class ApiException(val status: Int, val code: String, val body: ErrorDto? = null) : Exception(code)

/** Network unreachable / timeout: the app keeps working offline. */
class OfflineException(cause: Throwable) : IOException(cause)

val json = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true }

class Api(private val prefs: Prefs, private val onLoggedOut: () -> Unit) {
    private val http = OkHttpClient.Builder()
        .connectTimeout(8, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(30, TimeUnit.SECONDS)
        .retryOnConnectionFailure(true)
        .build()
    private val jsonType = "application/json; charset=utf-8".toMediaType()
    private val refreshLock = Mutex()

    private fun url(path: String): String {
        val base = prefs.serverUrl.ifBlank { throw ApiException(0, "no_server") }
        return "$base/api/${path.trimStart('/')}"
    }

    private suspend fun raw(method: String, path: String, body: String?, auth: Boolean): Pair<Int, String> = withContext(Dispatchers.IO) {
        val b = Request.Builder().url(url(path)).header("Accept", "application/json").header("X-Device-Serial", prefs.deviceSerial)
        if (auth) prefs.access?.let { b.header("Authorization", "Bearer $it") }
        b.method(method, body?.toRequestBody(jsonType) ?: if (method == "POST") "".toRequestBody(jsonType) else null)
        try {
            http.newCall(b.build()).execute().use { it.code to (it.body.string()) }
        } catch (e: IOException) {
            throw OfflineException(e)
        }
    }

    private suspend fun call(method: String, path: String, body: String? = null, auth: Boolean = true): String {
        var (status, text) = raw(method, path, body, auth)
        if (status == 401 && auth) {
            if (tryRefresh()) {
                val again = raw(method, path, body, auth)
                status = again.first; text = again.second
            } else {
                prefs.clearSession()
                onLoggedOut()
            }
        }
        if (status !in 200..299) {
            val err = runCatching { json.decodeFromString(ErrorDto.serializer(), text) }.getOrNull()
            throw ApiException(status, err?.code ?: "http_$status", err)
        }
        return text
    }

    private suspend fun tryRefresh(): Boolean = refreshLock.withLock {
        val token = prefs.refresh ?: return false
        val (status, text) = raw("POST", "auth/refresh/", """{"refresh":"$token"}""", auth = false)
        if (status != 200) return false
        val r = json.decodeFromString<RefreshResponse>(text)
        prefs.access = r.access
        r.refresh?.let { prefs.refresh = it }
        true
    }

    suspend fun health(): Boolean = withContext(Dispatchers.IO) {
        val base = prefs.serverUrl.ifBlank { return@withContext false }
        try {
            http.newCall(Request.Builder().url("$base/health/").build()).execute().use { it.isSuccessful }
        } catch (e: IOException) {
            false
        }
    }

    /**
     * A response the app cannot read (e.g. server and app versions out of step) becomes
     * a normal ApiException instead of crashing the app mid-shift.
     */
    private inline fun <reified T> decode(text: String): T = try {
        json.decodeFromString<T>(text)
    } catch (e: kotlinx.serialization.SerializationException) {
        android.util.Log.e("Api", "unreadable response", e)
        throw ApiException(200, "bad_response")
    } catch (e: IllegalArgumentException) {
        android.util.Log.e("Api", "unreadable response", e)
        throw ApiException(200, "bad_response")
    }

    suspend fun login(req: LoginRequest): LoginResponse =
        decode(call("POST", "auth/login/", json.encodeToString(LoginRequest.serializer(), req), auth = false))

    suspend fun config(): ConfigDto = decode(call("GET", "pda/config/"))
    suspend fun myOrders(): List<OrderSummaryDto> = decode(call("GET", "pda/orders/"))
    suspend fun snapshot(orderId: Long): SnapshotDto = decode(call("GET", "pda/orders/$orderId/"))

    suspend fun events(orderId: Long, req: EventsRequest): EventsResponse =
        decode(call("POST", "pda/orders/$orderId/events/", json.encodeToString(EventsRequest.serializer(), req)))

    suspend fun finish(orderId: Long): FinishResponse = decode(call("POST", "pda/orders/$orderId/finish/"))

    suspend fun myStocktakes(): List<StocktakeDto> = decode(call("GET", "pda/stocktakes/"))
    suspend fun stockRecords(id: Long): StockRecordsResponse = decode(call("GET", "pda/stocktakes/$id/records/"))
    suspend fun pushStock(id: Long, req: StockPushRequest): StockPushResponse =
        decode(call("POST", "pda/stocktakes/$id/records/", json.encodeToString(StockPushRequest.serializer(), req)))

    suspend fun barcodes(since: String?, afterId: Long): BarcodesResponse {
        val q = buildString {
            append("pda/barcodes/?after_id=").append(afterId)
            if (since != null) append("&since=").append(java.net.URLEncoder.encode(since, "UTF-8"))
        }
        return decode(call("GET", q))
    }
}
