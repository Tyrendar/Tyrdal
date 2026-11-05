package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.tyrdal.ordercheck.BuildConfig
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.app
import com.tyrdal.ordercheck.scanner.ScannerManager
import com.tyrdal.ordercheck.ui.theme.Palette
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(onDone: () -> Unit, onLanguageChanged: () -> Unit) {
    val app = LocalContext.current.app
    val scope = rememberCoroutineScope()
    var url by remember { mutableStateOf(app.prefs.serverUrl.ifBlank { "http://" }) }
    var test by remember { mutableStateOf<Boolean?>(null) }
    val mode by app.prefs.scannerModeFlow.collectAsState()
    val last by app.scanner.last.collectAsState()
    var cached by remember { mutableIntStateOf(0) }
    LaunchedEffect(Unit) { cached = app.db.barcodes().count() }

    Scaffold(topBar = {
        TopAppBar(
            title = { Text(stringResource(R.string.setup_title)) },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = Palette.TealDark, titleContentColor = Color.White),
        )
    }) { pad ->
        Column(
            Modifier.padding(pad).fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            ScanSafeTextField(url, { url = it; test = null }, stringResource(R.string.server_url), Modifier.fillMaxWidth(),
                ltrInput = true, keyboardType = KeyboardType.Uri)
            Text(stringResource(R.string.server_hint), style = MaterialTheme.typography.bodySmall, color = Palette.Muted)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                OutlinedButton(onClick = {
                    app.prefs.serverUrl = url
                    scope.launch { test = app.api.health() }
                }, modifier = Modifier.height(52.dp)) { Text(stringResource(R.string.test_connection)) }
                test?.let {
                    Text(stringResource(if (it) R.string.connection_ok else R.string.connection_failed),
                        color = if (it) Palette.Ok else Palette.Bad, style = MaterialTheme.typography.bodyMedium)
                }
            }

            HorizontalDivider()
            Text(stringResource(R.string.language), style = MaterialTheme.typography.titleMedium)
            val langs = listOf("fa" to "فارسی", "en" to "English")
            SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                langs.forEachIndexed { i, (code, label) ->
                    SegmentedButton(
                        selected = app.prefs.language == code,
                        onClick = { if (app.prefs.language != code) { app.prefs.language = code; onLanguageChanged() } },
                        shape = SegmentedButtonDefaults.itemShape(i, langs.size),
                    ) { Text(label) }
                }
            }

            HorizontalDivider()
            Text(stringResource(R.string.scanner_mode), style = MaterialTheme.typography.titleMedium)
            ScannerManager.MODES.forEach { m ->
                val label = when (m) {
                    "auto" -> stringResource(R.string.mode_auto)
                    "keyboard" -> stringResource(R.string.mode_keyboard)
                    else -> ScannerManager.PRESETS.first { it.id == m }.label
                }
                Row(
                    Modifier.fillMaxWidth().selectable(selected = mode == m, onClick = {
                        app.prefs.scannerMode = m; app.scanner.start()
                    }).padding(vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    RadioButton(selected = mode == m, onClick = null)
                    Text(label, Modifier.padding(start = 8.dp), style = MaterialTheme.typography.bodyLarge)
                }
            }
            Card(colors = CardDefaults.cardColors(containerColor = if (last != null) Palette.OkBg else Palette.WarnBg)) {
                Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    Text(stringResource(R.string.scanner_test), style = MaterialTheme.typography.titleMedium)
                    Text(stringResource(R.string.scanner_test_hint), style = MaterialTheme.typography.bodySmall)
                    Text(
                        last?.let { stringResource(R.string.scanner_last, ltr(it.raw), ltr(it.source)) } ?: stringResource(R.string.scanner_nothing),
                        style = MaterialTheme.typography.bodyLarge,
                    )
                }
            }

            HorizontalDivider()
            Text(stringResource(R.string.cached_barcodes, cached), style = MaterialTheme.typography.bodyMedium)
            if (app.user.collectAsState().value != null) {
                OutlinedButton(onClick = { scope.launch { app.sync.syncBarcodes(); cached = app.db.barcodes().count() } }) {
                    Text(stringResource(R.string.sync_barcodes))
                }
            }
            Text(stringResource(R.string.device_id, ltr(app.prefs.deviceSerial)), style = MaterialTheme.typography.bodySmall, color = Palette.Muted)
            Text(stringResource(R.string.version, BuildConfig.VERSION_NAME), style = MaterialTheme.typography.bodySmall, color = Palette.Muted)

            Button(
                onClick = { app.prefs.serverUrl = url; onDone() },
                enabled = url.length > "http://".length,
                modifier = Modifier.fillMaxWidth().height(56.dp),
            ) { Text(stringResource(R.string.save)) }
        }
    }
}
