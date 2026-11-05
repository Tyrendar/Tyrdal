package com.tyrdal.ordercheck.ui

import androidx.activity.compose.BackHandler
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.tyrdal.ordercheck.app

/** Tiny navigation: a handful of screens, no back stack library needed. */
sealed interface Screen {
    data object Settings : Screen
    data object Orders : Screen
    data class Check(val orderId: Long) : Screen
    data class Finish(val orderId: Long) : Screen
}

@Composable
fun AppRoot(onLanguageChanged: () -> Unit) {
    val app = LocalContext.current.app
    val user by app.user.collectAsState()
    var route by rememberSaveable(stateSaver = ScreenSaver) {
        mutableStateOf<Screen>(if (app.prefs.serverUrl.isBlank()) Screen.Settings else Screen.Orders)
    }

    if (route == Screen.Settings) {
        BackHandler(enabled = app.prefs.serverUrl.isNotBlank()) { route = Screen.Orders }
        SettingsScreen(onDone = { route = Screen.Orders }, onLanguageChanged = onLanguageChanged)
        return
    }
    if (user == null) {
        LoginScreen(onSettings = { route = Screen.Settings })
        return
    }
    when (val r = route) {
        Screen.Orders -> OrdersScreen(onOpen = { route = Screen.Check(it) }, onSettings = { route = Screen.Settings })
        is Screen.Check -> {
            BackHandler { route = Screen.Orders }
            CheckScreen(r.orderId, onBack = { route = Screen.Orders }, onFinish = { route = Screen.Finish(r.orderId) })
        }
        is Screen.Finish -> {
            BackHandler { route = Screen.Check(r.orderId) }
            FinishScreen(r.orderId, onBack = { route = Screen.Check(r.orderId) }, onCompleted = { route = Screen.Orders })
        }
        Screen.Settings -> {}
    }
}

private val ScreenSaver = androidx.compose.runtime.saveable.Saver<Screen, String>(
    save = {
        when (it) {
            Screen.Settings -> "settings"; Screen.Orders -> "orders"
            is Screen.Check -> "check:${it.orderId}"; is Screen.Finish -> "finish:${it.orderId}"
        }
    },
    restore = {
        when {
            it == "settings" -> Screen.Settings
            it.startsWith("check:") -> Screen.Check(it.removePrefix("check:").toLong())
            it.startsWith("finish:") -> Screen.Finish(it.removePrefix("finish:").toLong())
            else -> Screen.Orders
        }
    },
)
