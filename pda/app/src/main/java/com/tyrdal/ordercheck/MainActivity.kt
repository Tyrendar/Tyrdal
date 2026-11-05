package com.tyrdal.ordercheck

import android.content.Context
import android.os.Bundle
import android.view.KeyEvent
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.tyrdal.ordercheck.ui.AppRoot
import com.tyrdal.ordercheck.ui.theme.OrderCheckTheme

class MainActivity : ComponentActivity() {

    override fun attachBaseContext(newBase: Context) {
        // Persian by default; the layout direction follows the locale (RTL for Persian).
        val lang = newBase.getSharedPreferences("oc", MODE_PRIVATE).getString("lang", "fa") ?: "fa"
        super.attachBaseContext(App.localized(newBase, lang))
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Checkers scan continuously; the screen must not turn off mid-order.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContent { OrderCheckTheme { AppRoot(onLanguageChanged = { recreate() }) } }
    }

    override fun onResume() {
        super.onResume()
        app.scanner.start()
        app.sync.trigger()
    }

    override fun onPause() {
        app.scanner.stop()
        super.onPause()
    }

    /** Keyboard-wedge scanners "type" the barcode; capture it before any view does. */
    override fun dispatchKeyEvent(event: KeyEvent): Boolean =
        app.scanner.onKeyEvent(event) || super.dispatchKeyEvent(event)
}
