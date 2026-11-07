package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ListAlt
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Inventory
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.app
import com.tyrdal.ordercheck.data.db.StockTaskEntity
import com.tyrdal.ordercheck.ui.theme.Palette
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale

/** Jalali date in the UI language (Persian digits in Persian), e.g. "۱۷ آبان ۱۴۰۵". */
fun jalaliDate(iso: String): String = runCatching {
    val millis = LocalDate.parse(iso).atTime(12, 0).atZone(ZoneId.of("Asia/Tehran")).toInstant().toEpochMilli()
    val locale = android.icu.util.ULocale("${Locale.getDefault().language}@calendar=persian")
    val fmt = android.icu.text.DateFormat.getDateInstance(android.icu.text.DateFormat.MEDIUM, locale)
    fmt.timeZone = android.icu.util.TimeZone.getTimeZone("Asia/Tehran")
    fmt.format(java.util.Date(millis))
}.getOrDefault(iso)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StocktakesScreen(onOpen: (Long) -> Unit, onSettings: () -> Unit, onOrders: (() -> Unit)?) {
    val app = LocalContext.current.app
    val scope = rememberCoroutineScope()
    val tasks by app.db.stock().tasks().collectAsState(initial = emptyList())
    val user by app.user.collectAsState()
    val pending by app.sync.pendingEvents.collectAsState(initial = 0)
    val masterCount by app.db.stock().masterCount().collectAsState(initial = 0)
    var refreshing by remember { mutableStateOf(false) }
    var confirmLogout by remember { mutableStateOf(false) }

    LaunchedEffect(Unit) { refreshing = true; app.sync.refreshStocktakes(); refreshing = false; app.sync.syncStockMaster() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(stringResource(R.string.my_stocktakes))
                        Text(user?.fullName?.ifBlank { user?.username } ?: "", style = MaterialTheme.typography.bodySmall)
                    }
                },
                actions = {
                    SyncIndicator()
                    if (onOrders != null) IconButton(onClick = onOrders) { Icon(Icons.AutoMirrored.Filled.ListAlt, stringResource(R.string.st_orders)) }
                    IconButton(onClick = { scope.launch { refreshing = true; app.sync.pushStock(); app.sync.refreshStocktakes(); refreshing = false } }) {
                        Icon(Icons.Filled.Refresh, stringResource(R.string.refresh))
                    }
                    IconButton(onClick = onSettings) { Icon(Icons.Filled.Settings, stringResource(R.string.settings)) }
                    IconButton(onClick = { if (pending > 0) confirmLogout = true else app.logout() }) {
                        Icon(Icons.AutoMirrored.Filled.Logout, stringResource(R.string.logout))
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Palette.TealDark, titleContentColor = Color.White, actionIconContentColor = Color.White,
                ),
            )
        },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (refreshing) LinearProgressIndicator(Modifier.fillMaxWidth())
            Text(
                if (masterCount > 0) stringResource(R.string.st_master_n, java.text.NumberFormat.getInstance().format(masterCount)) else stringResource(R.string.st_master_loading),
                style = MaterialTheme.typography.bodySmall, color = Palette.Muted, modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
            )
            if (tasks.isEmpty() && !refreshing) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(stringResource(R.string.no_stocktakes), style = MaterialTheme.typography.titleMedium, color = Palette.Muted)
                }
            }
            LazyColumn(contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(tasks, key = { it.id }) { t -> TaskCard(t) { onOpen(t.id) } }
            }
        }
    }

    if (confirmLogout) {
        AlertDialog(
            onDismissRequest = { confirmLogout = false },
            text = { Text(stringResource(R.string.logout_unsent, pending)) },
            confirmButton = { TextButton(onClick = { confirmLogout = false; app.logout() }) { Text(stringResource(R.string.logout)) } },
            dismissButton = { TextButton(onClick = { confirmLogout = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

@Composable
private fun TaskCard(t: StockTaskEntity, onClick: () -> Unit) {
    val app = LocalContext.current.app
    val records by app.db.stock().records(t.id).collectAsState(initial = emptyList())
    Card(
        Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(containerColor = if (t.countable) Color.White else Color(0xFFF1F5F9)),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Inventory, null, tint = if (t.countable) Palette.Teal else Palette.Muted)
                Spacer(Modifier.padding(4.dp))
                Text(t.vendor, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
                if (t.countable) Pill(stringResource(R.string.st_in_progress), Palette.Teal, Color(0xFFCCFBF1))
                else Pill(stringResource(R.string.st_starts_on, jalaliDate(t.date)), Palette.Muted, Color(0xFFE2E8F0))
            }
            Text(jalaliDate(t.date), style = MaterialTheme.typography.bodyMedium, color = Palette.Muted)
            if (t.note.isNotBlank()) Text(t.note, style = MaterialTheme.typography.bodyMedium)
            Text(stringResource(R.string.st_records_units, records.size, records.sumOf { it.quantity }), style = MaterialTheme.typography.bodyMedium)
        }
    }
}
