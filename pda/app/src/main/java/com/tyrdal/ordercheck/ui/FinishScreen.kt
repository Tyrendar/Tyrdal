package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Surface
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
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
import com.tyrdal.ordercheck.domain.DiscStatus
import com.tyrdal.ordercheck.domain.DiscType
import com.tyrdal.ordercheck.domain.LineState
import com.tyrdal.ordercheck.ui.theme.Palette
import kotlinx.coroutines.delay

/**
 * Finish: shows exactly what still blocks completion. Remaining items can be marked as
 * shortages in bulk with one reason (typical: a few out-of-stock items → 3 taps).
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FinishScreen(orderId: Long, onBack: () -> Unit, onCompleted: () -> Unit) {
    val app = LocalContext.current.app
    val vm = checkViewModel(orderId)
    val view by vm.view.collectAsState()
    val finish by vm.finish.collectAsState()
    val reasons by app.reasons.collectAsState()
    var selected by remember { mutableStateOf(setOf<Long>()) }
    var reason by remember { mutableStateOf<Long?>(null) }
    var sheetLine by remember { mutableStateOf<Long?>(null) }

    LaunchedEffect(finish) {
        if (finish == FinishState.Done) { delay(1200); vm.resetFinish(); onCompleted() }
    }

    val v = view
    val remaining = v?.toCheck.orEmpty().filter { !it.isUnordered && (it.state == LineState.PENDING || it.state == LineState.PARTIAL) }
    val noReason = v?.issue.orEmpty().filter { l -> l.activeDiscs().any { it.status == DiscStatus.OPEN } }

    Scaffold(
        topBar = {
            TopAppBar(
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) } },
                title = { Text(stringResource(R.string.finish_title)) },
                actions = { SyncIndicator() },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = Palette.TealDark, titleContentColor = Color.White,
                    navigationIconContentColor = Color.White, actionIconContentColor = Color.White),
            )
        },
        // The action stays on screen however long the list is (an order can have hundreds of open items).
        bottomBar = {
            if (v != null && finish != FinishState.Done) Surface(shadowElevation = 8.dp) {
                Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (remaining.isNotEmpty()) {
                        Text(stringResource(R.string.reason), style = MaterialTheme.typography.titleMedium)
                        Row(Modifier.horizontalScroll(rememberScrollState())) {
                            ReasonChips(reasons.filter { it.applies(DiscType.SHORT) && !it.requiresNote }, reason) { reason = it }
                        }
                        Button(
                            enabled = selected.isNotEmpty() && reason != null,
                            onClick = { vm.declareShortMany(selected, reason!!, null); selected = emptySet() },
                            modifier = Modifier.fillMaxWidth().height(56.dp),
                        ) { Text(stringResource(R.string.record_shortage, selected.size)) }
                    } else {
                        val ready = v.problems.isEmpty()
                        if (ready) Text(stringResource(R.string.complete_ready), color = Palette.Ok, style = MaterialTheme.typography.titleMedium)
                        (finish as? FinishState.Failed)?.let { f ->
                            Text(stringResource(if (f.reason == "offline") R.string.finish_needs_online else R.string.cannot_complete),
                                color = Palette.Bad, style = MaterialTheme.typography.bodyMedium)
                        }
                        Button(
                            enabled = ready && finish != FinishState.Working && !v.info.locked && !v.info.revoked,
                            onClick = { vm.complete() },
                            modifier = Modifier.fillMaxWidth().height(64.dp),
                        ) {
                            if (finish == FinishState.Working) {
                                CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp, modifier = Modifier.size(22.dp))
                                Text("  " + stringResource(R.string.completing))
                            } else Text(stringResource(R.string.complete_order))
                        }
                    }
                }
            }
        },
    ) { pad ->
        if (v == null) return@Scaffold
        if (finish == FinishState.Done) {
            Box(Modifier.padding(pad).fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Filled.CheckCircle, null, tint = Palette.Ok, modifier = Modifier.size(96.dp))
                    Text(stringResource(R.string.completed_msg), style = MaterialTheme.typography.headlineSmall, color = Palette.Ok)
                }
            }
            return@Scaffold
        }
        LazyColumn(Modifier.padding(pad).fillMaxSize(), contentPadding = PaddingValues(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (v.pending != null) item {
                Text(stringResource(R.string.finish_pending), color = Palette.Bad, style = MaterialTheme.typography.titleMedium)
            }
            if (remaining.isNotEmpty()) {
                item {
                    Text(stringResource(R.string.finish_remaining, remaining.size), style = MaterialTheme.typography.titleMedium, color = Palette.Bad)
                    Text(stringResource(R.string.finish_remaining_hint), style = MaterialTheme.typography.bodySmall)
                    Row(Modifier.fillMaxWidth().clickable {
                        selected = if (selected.size == remaining.size) emptySet() else remaining.map { it.id }.toSet()
                    }, verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(checked = selected.size == remaining.size && remaining.isNotEmpty(), onCheckedChange = null)
                        Text(stringResource(R.string.select_all), style = MaterialTheme.typography.bodyLarge)
                    }
                }
                items(remaining, key = { it.id }) { l ->
                    Card(Modifier.fillMaxWidth().clickable { selected = if (l.id in selected) selected - l.id else selected + l.id }) {
                        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                            Checkbox(checked = l.id in selected, onCheckedChange = null)
                            Column(Modifier.weight(1f).padding(horizontal = 8.dp)) {
                                Text(l.title, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                                Text(stringResource(R.string.short_n, l.remaining, l.remaining * l.inc), color = Palette.Bad, style = MaterialTheme.typography.bodySmall)
                            }
                            Text(stringResource(R.string.x_of_y, l.boxesScanned, l.packOrdered), style = MaterialTheme.typography.titleMedium)
                        }
                    }
                }
            }
            if (noReason.isNotEmpty()) {
                item { Text(stringResource(R.string.finish_no_reason, noReason.size), style = MaterialTheme.typography.titleMedium, color = Palette.Bad) }
                items(noReason, key = { "nr-${it.id}" }) { l ->
                    Card(Modifier.fillMaxWidth().clickable { sheetLine = l.id }) {
                        Column(Modifier.padding(12.dp)) {
                            Text(l.title, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text(stringResource(R.string.no_reason), color = Palette.Bad, style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }
        sheetLine?.let { id ->
            (v.issue + v.toCheck + v.ok).firstOrNull { it.id == id }?.let { line ->
                LineSheet(line, reasons, locked = false, vm = vm, onClose = { sheetLine = null })
            }
        }
    }
}
