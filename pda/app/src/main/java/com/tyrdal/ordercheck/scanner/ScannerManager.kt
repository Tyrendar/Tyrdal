package com.tyrdal.ordercheck.scanner

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import com.tyrdal.ordercheck.data.Prefs
import com.tyrdal.ordercheck.domain.Barcode
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow

/** One physical trigger pull, as delivered by the PDA. */
data class ScanInput(val raw: String, val source: String, val duplicate: Boolean)

/** How a PDA brand delivers scans as a broadcast intent. */
data class Preset(val id: String, val label: String, val actions: List<String>, val extras: List<String>)

/**
 * Universal scanner input.
 *
 * Most PDAs can send each scan as a broadcast intent; the brands differ only in
 * the action and extra names. "Auto" listens for all known ones at once, so a
 * new device usually works without configuration. Keyboard-wedge input (scanner
 * "types" the barcode followed by Enter) is accepted as a fallback.
 *
 * Duplicate handling, using the monotonic clock (immune to wall-clock changes):
 *  - the same code within [ECHO_MS] from a different source is one scan reported
 *    twice by the device (e.g. Urovo sends two actions) → dropped silently;
 *  - the same code within the debounce window → flagged `duplicate` (recorded,
 *    never counted). A person cannot pick up and scan a second box that fast.
 */
class ScannerManager(private val context: Context, private val prefs: Prefs) {
    private val _scans = MutableSharedFlow<ScanInput>(extraBufferCapacity = 64)
    val scans: SharedFlow<ScanInput> = _scans
    private val _last = MutableStateFlow<ScanInput?>(null)
    /** Last raw input from any source (shown on the settings screen to diagnose a new device). */
    val last: StateFlow<ScanInput?> = _last

    private var registered: BroadcastReceiver? = null
    private var lastCode = ""
    private var lastAt = 0L
    private var lastSource = ""

    /** True while a text field has focus, so keyboard-wedge input goes to the field instead. */
    @Volatile var textInputActive = false

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(ctx: Context, intent: Intent) {
            val value = extract(intent) ?: return
            emit(value, intent.action ?: "broadcast")
        }
    }

    fun start() {
        stop()
        val mode = prefs.scannerMode
        if (mode == "keyboard") return
        val presets = if (mode == "auto") PRESETS else PRESETS.filter { it.id == mode || it.id == "generic" }
        val filter = IntentFilter().apply { presets.flatMap { it.actions }.distinct().forEach { addAction(it) } }
        if (Build.VERSION.SDK_INT >= 33) context.registerReceiver(receiver, filter, Context.RECEIVER_EXPORTED)
        else @Suppress("UnspecifiedRegisterReceiverFlag") context.registerReceiver(receiver, filter)
        registered = receiver
        if (mode == "auto" || mode == "urovo") enableUrovoIntentOutput()
        if (mode == "auto" || mode == "zebra") configureZebraDataWedge()
        if (mode == "auto" || mode == "honeywell") claimHoneywell(true)
    }

    fun stop() {
        registered?.let { runCatching { context.unregisterReceiver(it) } }
        registered = null
        if (prefs.scannerMode == "auto" || prefs.scannerMode == "honeywell") claimHoneywell(false)
    }

    private fun extract(intent: Intent): String? {
        val extras = intent.extras ?: return null
        for (key in ALL_EXTRAS) {
            when (val v = extras.get(key)) {
                is String -> if (v.isNotBlank()) return v
                is ByteArray -> {
                    val len = listOf("length", "barcodeLength", "barocodelen").firstNotNullOfOrNull { k -> extras.getInt(k, -1).takeIf { it > 0 } }
                    val s = String(v, 0, len?.coerceAtMost(v.size) ?: v.size, Charsets.UTF_8).trim()
                    if (s.isNotBlank()) return s
                }
                is CharSequence -> if (v.isNotBlank()) return v.toString()
            }
        }
        return null
    }

    /** Called for every input (broadcast or keyboard wedge). */
    fun emit(raw: String, source: String) {
        val code = Barcode.canonical(raw)
        if (code.isEmpty()) return
        val now = SystemClock.elapsedRealtime()
        val dt = now - lastAt
        val same = code == lastCode
        if (same && dt < ECHO_MS && source != lastSource) return // same scan delivered via two channels
        val duplicate = same && dt < prefs.debounceMs
        lastCode = code; lastAt = now; lastSource = source
        val input = ScanInput(raw, source, duplicate)
        _last.value = input
        _scans.tryEmit(input)
    }

    // --- Keyboard wedge -----------------------------------------------------------
    private val wedge = StringBuilder()
    private var wedgeAt = 0L

    /** Returns true when the key was consumed as scanner input. */
    fun onKeyEvent(event: KeyEvent): Boolean {
        if (textInputActive) return false
        if (event.action != KeyEvent.ACTION_DOWN) {
            return event.keyCode == KeyEvent.KEYCODE_ENTER && wedge.isNotEmpty()
        }
        val now = SystemClock.elapsedRealtime()
        if (now - wedgeAt > 300) wedge.clear() // humans type slowly; scanners send a burst
        wedgeAt = now
        when (event.keyCode) {
            KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_NUMPAD_ENTER, KeyEvent.KEYCODE_TAB -> {
                if (wedge.isEmpty()) return false
                val s = wedge.toString(); wedge.clear()
                emit(s, "keyboard")
                return true
            }
        }
        val ch = event.unicodeChar
        if (ch > 0 && !Character.isISOControl(ch)) {
            wedge.append(ch.toChar())
            return true
        }
        return false
    }

    // --- Vendor setup (best effort; harmless on other brands) ----------------------
    /** Urovo: switch the built-in scanner to broadcast output via android.device.ScanManager. */
    private fun enableUrovoIntentOutput() {
        try {
            val cls = Class.forName("android.device.ScanManager")
            val sm = cls.getDeclaredConstructor().newInstance()
            runCatching { cls.getMethod("openScanner").invoke(sm) }
            cls.getMethod("switchOutputMode", Int::class.javaPrimitiveType).invoke(sm, 0) // 0 = intent output
            Log.i(TAG, "Urovo scanner set to intent output")
        } catch (_: ClassNotFoundException) {
            // Not a Urovo device.
        } catch (e: Throwable) {
            Log.w(TAG, "Urovo setup failed", e)
        }
    }

    /** Zebra: create/update a DataWedge profile for this app with intent output. */
    private fun configureZebraDataWedge() {
        val pkg = context.packageName
        val intentConfig = Bundle().apply {
            putString("PLUGIN_NAME", "INTENT")
            putString("RESET_CONFIG", "true")
            putBundle("PARAM_LIST", Bundle().apply {
                putString("intent_output_enabled", "true")
                putString("intent_action", ACTION_GENERIC)
                putString("intent_delivery", "2") // broadcast
            })
        }
        val keystroke = Bundle().apply {
            putString("PLUGIN_NAME", "KEYSTROKE")
            putBundle("PARAM_LIST", Bundle().apply { putString("keystroke_output_enabled", "false") })
        }
        val config = Bundle().apply {
            putString("PROFILE_NAME", "OrderCheck")
            putString("PROFILE_ENABLED", "true")
            putString("CONFIG_MODE", "CREATE_IF_NOT_EXIST")
            putParcelableArray("APP_LIST", arrayOf(Bundle().apply {
                putString("PACKAGE_NAME", pkg); putStringArray("ACTIVITY_LIST", arrayOf("*"))
            }))
            putParcelableArrayList("PLUGIN_CONFIG", arrayListOf(intentConfig, keystroke))
        }
        context.sendBroadcast(Intent("com.symbol.datawedge.api.ACTION").putExtra("com.symbol.datawedge.api.SET_CONFIG", config))
    }

    /** Honeywell: ask the scanner service to send scans to us as an intent while the app runs. */
    private fun claimHoneywell(claim: Boolean) {
        val i = if (claim) {
            Intent("com.honeywell.aidc.action.ACTION_CLAIM_SCANNER")
                .putExtra("com.honeywell.aidc.extra.EXTRA_SCANNER", "dcs.scanner.imager")
                .putExtra("com.honeywell.aidc.extra.EXTRA_PROFILE", "DEFAULT")
                .putExtra("com.honeywell.aidc.extra.EXTRA_PROPERTIES", Bundle().apply {
                    putBoolean("DPR_DATA_INTENT", true)
                    putString("DPR_DATA_INTENT_ACTION", ACTION_GENERIC)
                })
        } else {
            Intent("com.honeywell.aidc.action.ACTION_RELEASE_SCANNER")
        }
        i.setPackage("com.intermec.datacollectionservice")
        runCatching { context.sendBroadcast(i) }
    }

    companion object {
        private const val TAG = "Scanner"
        private const val ECHO_MS = 120L
        const val ACTION_GENERIC = "com.tyrdal.ordercheck.SCAN"

        val PRESETS = listOf(
            Preset("urovo", "Urovo", listOf("android.intent.ACTION_DECODE_DATA", "urovo.rcv.message"), listOf("barcode_string", "barocode", "barcode")),
            Preset("zebra", "Zebra (DataWedge)", listOf(ACTION_GENERIC), listOf("com.symbol.datawedge.data_string")),
            Preset("honeywell", "Honeywell", listOf(ACTION_GENERIC), listOf("data")),
            Preset("newland", "Newland", listOf("nlscan.action.SCANNER_RESULT"), listOf("SCAN_BARCODE1")),
            Preset("idata", "iData", listOf("android.intent.action.SCANRESULT"), listOf("value")),
            Preset("sunmi", "Sunmi", listOf("com.sunmi.scanner.ACTION_DATA_CODE_RECEIVED"), listOf("data")),
            Preset("chainway", "Chainway", listOf("com.scanner.broadcast"), listOf("data")),
            Preset("seuic", "Seuic", listOf("com.android.server.scannerservice.broadcast"), listOf("scannerdata")),
            Preset("generic", "Generic intent", listOf(ACTION_GENERIC), listOf("data", "barcode", "barcode_string")),
        )
        private val ALL_EXTRAS = PRESETS.flatMap { it.extras }.distinct()
        val MODES = listOf("auto") + PRESETS.map { it.id }.filter { it != "generic" } + "keyboard"
    }
}
