package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalIconButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.domain.DiscStatus
import com.tyrdal.ordercheck.domain.DiscType
import com.tyrdal.ordercheck.domain.Line
import com.tyrdal.ordercheck.domain.Reason
import com.tyrdal.ordercheck.ui.theme.Palette

/** Everything a checker can do with one item: declare shortage, give a reason, correct the count. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LineSheet(line: Line, reasons: List<Reason>, locked: Boolean, vm: CheckViewModel, onClose: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onClose, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(line.title, style = MaterialTheme.typography.titleLarge)
            Text(ltr(line.productId) + "  ·  " + line.barcodes.joinToString("  ") { ltr(it) }, style = MaterialTheme.typography.bodySmall, color = Palette.Muted)
            if (!line.isUnordered) {
                Row(horizontalArrangement = Arrangement.spacedBy(20.dp)) {
                    Stat(stringResource(R.string.ordered), line.packOrdered)
                    Stat(stringResource(R.string.scanned), line.boxesScanned)
                    Stat(stringResource(R.string.remaining), line.remaining)
                }
                Text(stringResource(R.string.units_per_box, line.inc) + if (line.aisleTitle.isNotBlank()) "  ·  ${stringResource(R.string.aisle)} ${ltr(line.aisleTitle)}" else "",
                    style = MaterialTheme.typography.bodyMedium)
            }
            if (locked) return@Column

            // Existing discrepancies: set or change the reason.
            line.activeDiscs().forEach { d ->
                HorizontalDivider()
                val title = when (d.type) {
                    DiscType.SHORT -> stringResource(R.string.short_n, d.qtyBoxes, d.qtyBoxes * line.inc)
                    DiscType.EXTRA -> stringResource(R.string.extra_n, d.qtyBoxes)
                    DiscType.NOT_IN_ORDER -> stringResource(R.string.not_in_order_n, d.qtyBoxes)
                }
                Text(title, style = MaterialTheme.typography.titleMedium, color = if (d.status == DiscStatus.OPEN) Palette.Bad else Palette.Extra)
                ReasonEditor(
                    reasons = reasons.filter { it.applies(d.type) }, initialReason = d.reasonId, initialNote = d.note,
                    buttonText = stringResource(R.string.set_reason),
                ) { reasonId, note -> vm.setReason(line.id, d.type, reasonId, note); onClose() }
            }

            // Not fully scanned and no shortage yet: "Not found".
            if (!line.isUnordered && line.remaining > 0 && line.discs[DiscType.SHORT]?.status.let { it == null || it == DiscStatus.RESOLVED }) {
                HorizontalDivider()
                Text(stringResource(R.string.not_found) + " — " + stringResource(R.string.short_n, line.remaining, line.remaining * line.inc),
                    style = MaterialTheme.typography.titleMedium)
                ReasonEditor(reasons.filter { it.applies(DiscType.SHORT) }, null, "", stringResource(R.string.not_found)) { reasonId, note ->
                    vm.declareShort(line.id, reasonId, note); onClose()
                }
            }

            // Correct the counted boxes (e.g. a box scanned from the wrong pallet).
            if (!line.isUnordered) {
                HorizontalDivider()
                Text(stringResource(R.string.correct_qty), style = MaterialTheme.typography.titleMedium)
                var boxes by remember(line.id, line.boxesScanned) { mutableIntStateOf(line.boxesScanned) }
                var note by remember { mutableStateOf("") }
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    FilledTonalIconButton(onClick = { if (boxes > 0) boxes-- }, modifier = Modifier.size(56.dp)) { Icon(Icons.Filled.Remove, null) }
                    Text(n(boxes), fontSize = 30.sp, fontWeight = FontWeight.Bold)
                    FilledTonalIconButton(onClick = { if (boxes < line.packOrdered) boxes++ }, modifier = Modifier.size(56.dp)) { Icon(Icons.Filled.Add, null) }
                }
                ScanSafeTextField(note, { note = it }, stringResource(R.string.note), Modifier.fillMaxWidth())
                OutlinedButton(enabled = boxes != line.boxesScanned, onClick = { vm.adjust(line.id, boxes, note.ifBlank { null }); onClose() },
                    modifier = Modifier.fillMaxWidth().height(52.dp)) { Text(stringResource(R.string.apply)) }
            }
        }
    }
}

@Composable
private fun Stat(label: String, value: Int) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(n(value), fontSize = 26.sp, fontWeight = FontWeight.Bold)
        Text(label, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
fun ReasonEditor(reasons: List<Reason>, initialReason: Long?, initialNote: String, buttonText: String, onApply: (Long, String?) -> Unit) {
    var reason by remember { mutableStateOf(initialReason) }
    var note by remember { mutableStateOf(initialNote) }
    val needsNote = reasons.firstOrNull { it.id == reason }?.requiresNote == true
    ReasonChips(reasons, reason) { reason = it }
    ScanSafeTextField(note, { note = it }, stringResource(R.string.note), Modifier.fillMaxWidth())
    if (needsNote && note.isBlank()) Text(stringResource(R.string.note_required), color = Palette.Bad, style = MaterialTheme.typography.bodySmall)
    Button(
        enabled = reason != null && (!needsNote || note.isNotBlank()),
        onClick = { onApply(reason!!, note.ifBlank { null }) },
        modifier = Modifier.fillMaxWidth().height(56.dp),
    ) { Text(buttonText) }
}
