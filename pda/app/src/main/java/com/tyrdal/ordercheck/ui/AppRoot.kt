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
    data object Stocktakes : Screen
    data class Stocktake(val id: Long) : Screen
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
    // What this account may do on the PDA decides its home list (checkers: orders; stocktakers: stocktakes).
    val perms = user?.permissions.orEmpty()
    val canCheck = "checking.perform" in perms
    val canStock = "stocktake.perform" in perms
    when (val r = route) {
        Screen.Orders, Screen.Stocktakes -> {
            if ((r == Screen.Stocktakes && canStock) || !canCheck) {
                StocktakesScreen(onOpen = { route = Screen.Stocktake(it) }, onSettings = { route = Screen.Settings },
                    onOrders = if (canCheck) ({ route = Screen.Orders }) else null)
            } else {
                OrdersScreen(onOpen = { route = Screen.Check(it) }, onSettings = { route = Screen.Settings },
                    onStock = if (canStock) ({ route = Screen.Stocktakes }) else null)
            }
        }
        is Screen.Stocktake -> {
            BackHandler { route = Screen.Stocktakes }
            StocktakeScreen(r.id, onBack = { route = Screen.Stocktakes })
        }
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
            Screen.Settings -> "settings"; Screen.Orders -> "orders"; Screen.Stocktakes -> "stocktakes"
            is Screen.Stocktake -> "stocktake:${it.id}"
            is Screen.Check -> "check:${it.orderId}"; is Screen.Finish -> "finish:${it.orderId}"
        }
    },
    restore = {
        when {
            it == "settings" -> Screen.Settings
            it == "stocktakes" -> Screen.Stocktakes
            it.startsWith("stocktake:") -> Screen.Stocktake(it.removePrefix("stocktake:").toLong())
            it.startsWith("check:") -> Screen.Check(it.removePrefix("check:").toLong())
            it.startsWith("finish:") -> Screen.Finish(it.removePrefix("finish:").toLong())
            else -> Screen.Orders
        }
    },
)
