package com.tyrdal.ordercheck.data

import android.annotation.SuppressLint
import android.content.Context
import android.provider.Settings
import androidx.core.content.edit
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow

/** Small key-value settings in app-private storage. */
class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("oc", Context.MODE_PRIVATE)

    @SuppressLint("HardwareIds")
    val deviceSerial: String = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID) ?: "unknown"

    var serverUrl: String
        get() = sp.getString("server", "") ?: ""
        set(v) = sp.edit { putString("server", v.trim().trimEnd('/')) }

    var access: String?
        get() = sp.getString("access", null)
        set(v) = sp.edit { putString("access", v) }

    var refresh: String?
        get() = sp.getString("refresh", null)
        set(v) = sp.edit { putString("refresh", v) }

    var userJson: String?
        get() = sp.getString("user", null)
        set(v) = sp.edit { putString("user", v) }

    var language: String
        get() = sp.getString("lang", "fa") ?: "fa"
        set(v) = sp.edit { putString("lang", v) }

    private val _scannerMode = MutableStateFlow(sp.getString("scanner", "auto") ?: "auto")
    val scannerModeFlow: StateFlow<String> = _scannerMode
    var scannerMode: String
        get() = _scannerMode.value
        set(v) { sp.edit { putString("scanner", v) }; _scannerMode.value = v }

    var debounceMs: Int
        get() = sp.getInt("debounce", 700)
        set(v) = sp.edit { putInt("debounce", v) }

    /** Change-feed position of the stocktake master cache. */
    var stockMasterSince: String?
        get() = sp.getString("sm_since", null)
        set(v) = sp.edit { putString("sm_since", v) }

    var barcodeSince: String?
        get() = sp.getString("bc_since", null)
        set(v) = sp.edit { putString("bc_since", v) }

    var reasonsJson: String?
        get() = sp.getString("reasons", null)
        set(v) = sp.edit { putString("reasons", v) }

    fun clearSession() = sp.edit { remove("access"); remove("refresh"); remove("user") }
}
