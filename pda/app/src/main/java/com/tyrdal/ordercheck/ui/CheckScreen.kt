package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.app
import com.tyrdal.ordercheck.domain.DiscStatus
import com.tyrdal.ordercheck.domain.DiscType
import com.tyrdal.ordercheck.domain.Line
import com.tyrdal.ordercheck.domain.Outcome
import com.tyrdal.ordercheck.domain.Pending
import com.tyrdal.ordercheck.domain.PendingKind
import com.tyrdal.ordercheck.domain.Tab as LineTab
import com.tyrdal.ordercheck.ui.theme.Palette

@Composable
fun checkViewModel(orderId: Long): CheckViewModel {
    val app = LocalContext.current.app
    return viewModel(key = "check-$orderId") { CheckViewModel(app, orderId) }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CheckScreen(orderId: Long, onBack: () -> Unit, onFinish: () -> Unit) {
    val app = LocalContext.current.app
    val vm = checkViewModel(orderId)
    val view by vm.view.collectAsState()
    val last by vm.last.collectAsState()
    val missing by vm.missing.collectAsState()
    var tab by remember { mutableIntStateOf(0) }
    var sheetLine by remember { mutableStateOf<Long?>(null) }
    var manual by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }

    // Every scan goes to this order while the screen is open — no product selection needed.
    LaunchedEffect(orderId) { app.scanner.scans.collect { vm.onScan(it) } }

    Scaffold(
        topBar = {
            TopAppBar(
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) } },
                title = {
                    Column {
                        Text(ltr(view?.info?.referenceId ?: ""), maxLines = 1)
                        Text(view?.info?.customer ?: "", style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                },
                actions = { SyncIndicator() },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Palette.TealDark, titleContentColor = Color.White,
                    navigationIconContentColor = Color.White, actionIconContentColor = Color.White,
                ),
            )
        },
        bottomBar = {
            Row(Modifier.fillMaxWidth().background(Color.White).padding(10.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedButton(onClick = { manual = true }, modifier = Modifier.height(56.dp)) {
                    Icon(Icons.Filled.Keyboard, null); Spacer(Modifier.width(6.dp)); Text(stringResource(R.string.manual_entry))
                }
                Button(onClick = onFinish, enabled = view?.info?.let { !it.locked && !it.revoked } == true,
                    modifier = Modifier.weight(1f).height(56.dp)) { Text(stringResource(R.string.finish)) }
            }
        },
    ) { pad ->
        val v = view
        if (v == null) {
            Box(Modifier.padding(pad).fillMaxSize(), contentAlignment = Alignment.Center) {
                if (missing) Text(stringResource(R.string.not_downloaded), color = Palette.Bad) else CircularProgressIndicator()
            }
            return@Scaffold
        }
        Column(Modifier.padding(pad).fillMaxSize()) {
            if (v.info.revoked || v.info.locked) {
                Text(
                    stringResource(if (v.info.revoked) R.string.order_revoked else R.string.order_locked),
                    color = Color.White, modifier = Modifier.fillMaxWidth().background(Palette.Bad).padding(10.dp),
                )
            }
            LastScanCard(last)
            val counts = listOf(v.counters.toCheck, v.counters.ok, v.counters.issue)
            val labels = listOf(R.string.tab_to_check, R.string.tab_ok, R.string.tab_issue)
            val colors = listOf(Palette.Muted, Palette.Ok, Palette.Bad)
            TabRow(selectedTabIndex = tab, containerColor = Color.White) {
                labels.forEachIndexed { i, l ->
                    Tab(selected = tab == i, onClick = { tab = i }, modifier = Modifier.heightIn(min = 60.dp)) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(n(counts[i]), fontSize = 22.sp, fontWeight = FontWeight.Bold, color = colors[i])
                            Text(stringResource(l), style = MaterialTheme.typography.bodySmall, maxLines = 1)
                        }
                    }
                }
            }
            ScanSafeTextField(query, { query = it }, stringResource(R.string.search_hint),
                Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 4.dp))
            val list = when (tab) { 0 -> v.toCheck; 1 -> v.ok; else -> v.issue }.let { lines ->
                val q = query.trim().lowercase()
                if (q.isEmpty()) lines else lines.filter { l ->
                    l.title.lowercase().contains(q) || l.productId.contains(q) || l.barcodes.any { it.contains(q) } || l.aisleTitle.lowercase().contains(q)
                }
            }
            val listState = rememberLazyListState()
            if (list.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                    Text(stringResource(R.string.empty_tab), color = Palette.Muted)
                }
            } else {
                LazyColumn(state = listState, contentPadding = PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    items(list, key = { it.id }) { line -> LineRow(line) { sheetLine = line.id } }
                }
            }
        }

        v.pending?.let { ExtraDialog(it, v, onRemoved = { vm.decide(true) }, onMistake = { vm.decide(false) }) }
        sheetLine?.let { id ->
            val line = (v.toCheck + v.ok + v.issue).firstOrNull { it.id == id }
            if (line != null) LineSheet(line, app.reasons.collectAsState().value, locked = v.info.locked || v.info.revoked, vm = vm, onClose = { sheetLine = null })
        }
        if (manual) ManualEntryDialog(onDismiss = { manual = false }) { vm.manualBarcode(it); manual = false }
    }
}

@Composable
private fun LastScanCard(last: LastScan?) {
    val (bg, fg, label) = when (last?.outcome) {
        null -> Triple(Color(0xFFE2E8F0), Palette.Muted, stringResource(R.string.scan_prompt))
        Outcome.COUNTED -> Triple(Palette.OkBg, Palette.Ok, stringResource(R.string.outcome_counted))
        Outcome.LINE_COMPLETE -> Triple(Palette.Ok, Color.White, stringResource(R.string.outcome_complete))
        Outcome.DUPLICATE -> Triple(Color(0xFFE2E8F0), Palette.Muted, stringResource(R.string.outcome_duplicate))
        Outcome.UNKNOWN -> Triple(Palette.Bad, Color.White, stringResource(R.string.outcome_unknown))
        Outcome.BLOCKED -> Triple(Palette.BadBg, Palette.Bad, stringResource(R.string.outcome_blocked))
        Outcome.LOCKED -> Triple(Palette.BadBg, Palette.Bad, stringResource(R.string.outcome_locked))
        Outcome.OVER -> Triple(Palette.Bad, Color.White, stringResource(R.string.over_title))
        Outcome.NOT_IN_ORDER -> Triple(Palette.Bad, Color.White, stringResource(R.string.not_in_order_title))
        Outcome.REMOVED -> Triple(Palette.ExtraBg, Palette.Extra, stringResource(R.string.outcome_removed))
        Outcome.MISTAKE -> Triple(Color(0xFFE2E8F0), Palette.Muted, stringResource(R.string.outcome_mistake))
        else -> Triple(Palette.OkBg, Palette.Ok, stringResource(R.string.outcome_saved))
    }
    Row(
        Modifier.fillMaxWidth().background(bg).padding(horizontal = 14.dp, vertical = 10.dp).heightIn(min = 88.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(Modifier.weight(1f)) {
            Text(label, color = fg, style = MaterialTheme.typography.titleLarge)
            last?.title?.let { Text(it, color = fg, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis) }
            if (last != null && last.barcode.isNotEmpty()) Text(ltr(last.barcode), color = fg.copy(alpha = 0.8f), style = MaterialTheme.typography.bodySmall)
        }
        last?.line?.takeIf { !it.isUnordered }?.let { l ->
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(stringResource(R.string.x_of_y, l.boxesScanned, l.packOrdered), color = fg, fontSize = 34.sp, fontWeight = FontWeight.Bold)
                Text(stringResource(R.string.boxes), color = fg, style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
private fun LineRow(line: Line, onClick: () -> Unit) {
    val (accent, bg) = when (line.tab) {
        LineTab.TO_CHECK -> (if (line.boxesScanned > 0) Palette.Warn else Palette.Muted) to Color.White
        LineTab.OK -> Palette.Ok to Color.White
        LineTab.ISSUE -> (if (line.activeDiscs().any { it.status == DiscStatus.OPEN }) Palette.Bad else Palette.Extra) to Color.White
    }
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.background(bg).padding(start = 0.dp), verticalAlignment = Alignment.CenterVertically) {
            Box(Modifier.width(6.dp).heightIn(min = 76.dp).background(accent))
            Column(Modifier.weight(1f).padding(horizontal = 10.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(line.title, style = MaterialTheme.typography.titleMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (line.aisleTitle.isNotBlank()) Pill(ltr(line.aisleTitle), Palette.TealDark, Color(0xFFE0F2F1))
                    line.barcodes.firstOrNull()?.let { Text(ltr(it), style = MaterialTheme.typography.bodySmall, color = Palette.Muted) }
                }
                if (!line.isUnordered && line.inc > 0) Text(stringResource(R.string.units_per_box, line.inc), style = MaterialTheme.typography.bodySmall, color = Palette.Muted)
                DiscSummary(line)
            }
            Column(Modifier.padding(horizontal = 12.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                if (line.isUnordered) {
                    Text(n(line.boxesExtra), fontSize = 26.sp, fontWeight = FontWeight.Bold, color = Palette.Extra)
                } else {
                    Text(stringResource(R.string.x_of_y, line.boxesScanned, line.packOrdered), fontSize = 24.sp, fontWeight = FontWeight.Bold, color = accent)
                    if (line.tab == LineTab.TO_CHECK) Text("${stringResource(R.string.remaining)} ${n(line.remaining)}", style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
private fun DiscSummary(line: Line) {
    line.activeDiscs().forEach { d ->
        val text = when (d.type) {
            DiscType.SHORT -> stringResource(R.string.short_n, d.qtyBoxes, d.qtyBoxes * line.inc)
            DiscType.EXTRA -> stringResource(R.string.extra_n, d.qtyBoxes)
            DiscType.NOT_IN_ORDER -> stringResource(R.string.not_in_order_n, d.qtyBoxes)
        }
        val status = if (d.status == DiscStatus.OPEN) " · " + stringResource(R.string.disc_status_open) else ""
        Text(text + status, color = if (d.status == DiscStatus.OPEN) Palette.Bad else Palette.Extra, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
    }
}

/** Full-screen, non-dismissable: the box must physically come off the pallet, or the scan was a mistake. */
@Composable
private fun ExtraDialog(p: Pending, v: CheckView, onRemoved: () -> Unit, onMistake: () -> Unit) {
    val line = p.lineId?.let { id -> (v.ok + v.issue + v.toCheck).firstOrNull { it.id == id } }
    Dialog(onDismissRequest = {}, properties = DialogProperties(dismissOnBackPress = false, dismissOnClickOutside = false, usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize(), color = Palette.Bad) {
            Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Spacer(Modifier.height(12.dp))
                Icon(Icons.Filled.Warning, null, tint = Color.White, modifier = Modifier.size(72.dp))
                Text(stringResource(if (p.kind == PendingKind.OVER) R.string.over_title else R.string.not_in_order_title),
                    color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.Bold)
                Text(p.title, color = Color.White, style = MaterialTheme.typography.titleLarge)
                Text(ltr(p.barcode), color = Color.White.copy(alpha = 0.85f))
                if (p.kind == PendingKind.OVER && line != null) {
                    Text(stringResource(R.string.over_detail, line.packOrdered, line.boxesScanned), color = Color.White, style = MaterialTheme.typography.titleMedium)
                }
                Text(stringResource(R.string.must_remove), color = Color.White, style = MaterialTheme.typography.bodyLarge)
                Spacer(Modifier.weight(1f))
                Button(
                    onClick = onRemoved, modifier = Modifier.fillMaxWidth().height(76.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Color.White, contentColor = Palette.Bad),
                    shape = RoundedCornerShape(14.dp),
                ) { Text(stringResource(R.string.removed_btn), fontSize = 22.sp, fontWeight = FontWeight.Bold) }
                OutlinedButton(
                    onClick = onMistake, modifier = Modifier.fillMaxWidth().height(64.dp), shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.outlinedButtonColors(contentColor = Color.White),
                ) { Text(stringResource(R.string.mistake_btn), fontSize = 18.sp) }
            }
        }
    }
}

@Composable
private fun ManualEntryDialog(onDismiss: () -> Unit, onSubmit: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.manual_entry)) },
        text = { ScanSafeTextField(text, { text = it.filter { c -> !c.isWhitespace() } }, stringResource(R.string.enter_barcode), Modifier.fillMaxWidth(), ltrInput = true, keyboardType = KeyboardType.Number) },
        confirmButton = { TextButton(enabled = text.length >= 4, onClick = { onSubmit(text) }) { Text(stringResource(R.string.apply)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}
