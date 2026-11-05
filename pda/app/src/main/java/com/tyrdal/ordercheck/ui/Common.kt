package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.dp
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.ImeAction
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.app
import com.tyrdal.ordercheck.domain.Reason
import com.tyrdal.ordercheck.ui.theme.Palette
import java.util.Locale

/** Barcodes, product IDs, aisle codes: isolated LTR so RTL layout never reorders them. */
fun ltr(s: String) = "⁦$s⁩"

/** Numbers in the UI language's digits (Persian digits in Persian). */
fun n(i: Int): String = String.format(Locale.getDefault(), "%d", i)

@Composable
fun Pill(text: String, fg: Color, bg: Color, modifier: Modifier = Modifier) {
    Text(
        text, color = fg, style = MaterialTheme.typography.labelMedium,
        modifier = modifier.background(bg, RoundedCornerShape(50)).padding(horizontal = 10.dp, vertical = 3.dp),
    )
}

@Composable
fun SyncIndicator() {
    val app = LocalContext.current.app
    val online by app.sync.online.collectAsState()
    val pending by app.sync.pendingEvents.collectAsState(initial = 0)
    val (icon, color, text) = when {
        !online -> Triple(Icons.Filled.CloudOff, Palette.Bad, if (pending > 0) stringResource(R.string.pending_sync, pending) else stringResource(R.string.offline))
        pending > 0 -> Triple(Icons.Filled.CloudUpload, Palette.Warn, stringResource(R.string.pending_sync, pending))
        else -> Triple(Icons.Filled.CloudDone, Color.White, "")
    }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp),
        modifier = Modifier.padding(horizontal = 8.dp)) {
        Icon(icon, null, tint = color)
        if (text.isNotEmpty()) Text(text, color = color, style = MaterialTheme.typography.labelMedium)
    }
}

/** Text field that tells the scanner to leave keyboard input alone while focused. */
@Composable
fun ScanSafeTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    ltrInput: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
    singleLine: Boolean = true,
    isPassword: Boolean = false,
    imeAction: ImeAction = ImeAction.Default,
    onImeAction: (() -> Unit)? = null,
) {
    val scanner = LocalContext.current.app.scanner
    OutlinedTextField(
        value = value, onValueChange = onValueChange, label = { Text(label) }, singleLine = singleLine,
        textStyle = MaterialTheme.typography.bodyLarge.copy(textDirection = if (ltrInput) TextDirection.Ltr else TextDirection.Content),
        keyboardOptions = KeyboardOptions(keyboardType = if (isPassword) KeyboardType.Password else keyboardType, imeAction = imeAction),
        keyboardActions = KeyboardActions(onAny = { onImeAction?.invoke() ?: defaultKeyboardAction(imeAction) }),
        visualTransformation = if (isPassword) androidx.compose.ui.text.input.PasswordVisualTransformation() else androidx.compose.ui.text.input.VisualTransformation.None,
        modifier = modifier.onFocusChanged { scanner.textInputActive = it.isFocused },
    )
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ReasonChips(reasons: List<Reason>, selected: Long?, onSelect: (Long) -> Unit) {
    val lang = Locale.getDefault().language
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
        reasons.sortedBy { it.sortOrder }.forEach { r ->
            FilterChip(
                selected = r.id == selected, onClick = { onSelect(r.id) },
                label = { Text(r.name(lang), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(vertical = 10.dp)) },
            )
        }
    }
}

@Composable
fun statusLabel(status: String) = when (status) {
    "assigned" -> stringResource(R.string.status_assigned)
    "in_progress" -> stringResource(R.string.status_in_progress)
    "completed" -> stringResource(R.string.status_completed)
    "cancelled" -> stringResource(R.string.status_cancelled)
    else -> status
}
