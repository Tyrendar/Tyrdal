package com.tyrdal.ordercheck

import android.app.Application
import android.content.Context
import android.os.Build
import com.tyrdal.ordercheck.data.Api
import com.tyrdal.ordercheck.data.ApiException
import com.tyrdal.ordercheck.data.LoginRequest
import com.tyrdal.ordercheck.data.OrderStore
import com.tyrdal.ordercheck.data.Prefs
import com.tyrdal.ordercheck.data.StockStore
import com.tyrdal.ordercheck.data.ReasonDto
import com.tyrdal.ordercheck.data.UserDto
import com.tyrdal.ordercheck.data.db.AppDb
import com.tyrdal.ordercheck.data.json
import com.tyrdal.ordercheck.domain.CheckEngine
import com.tyrdal.ordercheck.domain.MappedProduct
import com.tyrdal.ordercheck.domain.Reason
import com.tyrdal.ordercheck.feedback.Feedback
import com.tyrdal.ordercheck.scanner.ScannerManager
import com.tyrdal.ordercheck.sync.SyncManager
import com.tyrdal.ordercheck.sync.toDomain
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.builtins.ListSerializer
import java.util.Locale

/** Manual dependency container: one instance of each service for the whole app. */
class App : Application() {
    val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    lateinit var prefs: Prefs; private set
    lateinit var db: AppDb; private set
    lateinit var api: Api; private set
    lateinit var store: OrderStore; private set
    lateinit var stock: StockStore; private set
    lateinit var sync: SyncManager; private set
    lateinit var scanner: ScannerManager; private set
    lateinit var feedback: Feedback; private set

    private val _user = MutableStateFlow<UserDto?>(null)
    val user: StateFlow<UserDto?> = _user
    private val _reasons = MutableStateFlow<List<Reason>>(emptyList())
    val reasons: StateFlow<List<Reason>> = _reasons

    override fun onCreate() {
        super.onCreate()
        prefs = Prefs(this)
        db = AppDb.create(this)
        api = Api(prefs) { _user.value = null; sync.stop() }
        store = OrderStore(db) {
            CheckEngine(
                reasons = { _reasons.value },
                lookupMapping = { code -> db.barcodes().getBlocking(code)?.let { MappedProduct(it.productId, it.title) } },
            )
        }
        stock = StockStore(db)
        sync = SyncManager(appScope, api, db, store, prefs, { _reasons.value = it }) { _user.value?.permissions?.toSet() ?: emptySet() }
        scanner = ScannerManager(this, prefs)
        feedback = Feedback(this, appScope)
        prefs.reasonsJson?.let { s ->
            runCatching { json.decodeFromString(ListSerializer(ReasonDto.serializer()), s) }.getOrNull()
                ?.let { list -> _reasons.value = list.map { it.toDomain() } }
        }
        // Stay signed in across restarts (offline too): tokens are refreshed on the next request.
        if (prefs.access != null) {
            _user.value = prefs.userJson?.let { runCatching { json.decodeFromString(UserDto.serializer(), it) }.getOrNull() }
            if (_user.value != null) sync.start()
        }
    }

    suspend fun login(username: String, password: String): UserDto {
        val r = api.login(LoginRequest(username, password, prefs.deviceSerial, "${Build.MANUFACTURER} ${Build.MODEL}", BuildConfig.VERSION_NAME))
        if (PDA_PERMS.none { it in r.user.permissions }) throw ApiException(403, "not_a_checker")
        prefs.access = r.access
        prefs.refresh = r.refresh
        prefs.userJson = json.encodeToString(UserDto.serializer(), r.user)
        _user.value = r.user
        sync.start()
        sync.trigger()
        return r.user
    }

    fun logout() {
        sync.stop()
        prefs.clearSession()
        _user.value = null
    }

    companion object {
        /** A PDA account checks orders, counts stock, or both. */
        val PDA_PERMS = listOf("checking.perform", "stocktake.perform")

        fun localized(base: Context, lang: String): Context {
            val locale = Locale.forLanguageTag(lang)
            Locale.setDefault(locale)
            val cfg = base.resources.configuration
            cfg.setLocale(locale)
            cfg.setLayoutDirection(locale)
            return base.createConfigurationContext(cfg)
        }
    }
}

val Context.app: App get() = applicationContext as App
