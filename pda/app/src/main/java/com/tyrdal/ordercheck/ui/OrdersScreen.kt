package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.Inventory
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
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
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.app
import com.tyrdal.ordercheck.data.db.OrderEntity
import com.tyrdal.ordercheck.ui.theme.Palette
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun OrdersScreen(onOpen: (Long) -> Unit, onSettings: () -> Unit, onStock: (() -> Unit)? = null) {
    val ctx = LocalContext.current
    val app = ctx.app
    val scope = rememberCoroutineScope()
    val orders by app.db.orders().activeOrders().collectAsState(initial = emptyList())
    val user by app.user.collectAsState()
    val pending by app.sync.pendingEvents.collectAsState(initial = 0)
    var refreshing by remember { mutableStateOf(false) }
    var opening by remember { mutableStateOf<Long?>(null) }
    var confirmLogout by remember { mutableStateOf(false) }
    val snack = remember { SnackbarHostState() }
    val notDownloaded = stringResource(R.string.not_downloaded)

    LaunchedEffect(Unit) { refreshing = true; app.sync.refreshOrders(); refreshing = false }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(stringResource(R.string.my_orders))
                        Text(user?.fullName?.ifBlank { user?.username } ?: "", style = MaterialTheme.typography.bodySmall)
                    }
                },
                actions = {
                    SyncIndicator()
                    if (onStock != null) IconButton(onClick = onStock) { Icon(Icons.Filled.Inventory, stringResource(R.string.stocktaking)) }
                    IconButton(onClick = { scope.launch { refreshing = true; app.sync.pushAll(); app.sync.refreshOrders(); refreshing = false } }) {
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
        snackbarHost = { SnackbarHost(snack) },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (refreshing || opening != null) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (orders.isEmpty() && !refreshing) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(stringResource(R.string.no_orders), style = MaterialTheme.typography.titleMedium, color = Palette.Muted)
                }
            }
            LazyColumn(contentPadding = androidx.compose.foundation.layout.PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                items(orders, key = { it.id }) { o ->
                    OrderCard(o) {
                        scope.launch {
                            if (o.snapshotVersion == 0) {
                                opening = o.id
                                val ok = app.sync.refreshSnapshot(o.id)
                                opening = null
                                if (!ok) { snack.showSnackbar(notDownloaded); return@launch }
                            }
                            onOpen(o.id)
                        }
                    }
                }
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
private fun OrderCard(o: OrderEntity, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(ltr(o.referenceId), style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.weight(1f))
                val inProgress = o.status == "in_progress"
                Pill(statusLabel(o.status), if (inProgress) Palette.Teal else Palette.Muted, if (inProgress) Color(0xFFCCFBF1) else Color(0xFFE2E8F0))
            }
            Text(o.customer, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
            LinearProgressIndicator(
                progress = { if (o.linesTotal == 0) 0f else o.linesDone.toFloat() / o.linesTotal },
                modifier = Modifier.fillMaxWidth().height(8.dp),
                color = if (o.openIssues > 0) Palette.Warn else Palette.Teal,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(14.dp)) {
                Text(stringResource(R.string.lines_of, o.linesDone, o.linesTotal), style = MaterialTheme.typography.bodyMedium)
                Text(stringResource(R.string.boxes_of, o.boxesScanned, o.boxesOrdered), style = MaterialTheme.typography.bodyMedium)
                if (o.issuesTotal > 0) Text(stringResource(R.string.issues_n, o.issuesTotal), color = Palette.Bad, style = MaterialTheme.typography.bodyMedium)
            }
            if (o.snapshotVersion == 0) Text(stringResource(R.string.not_downloaded), color = Palette.Muted, style = MaterialTheme.typography.bodySmall)
        }
    }
}
