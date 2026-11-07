package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.viewmodel.compose.viewModel
import com.tyrdal.ordercheck.App
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.app
import com.tyrdal.ordercheck.data.StockStore
import com.tyrdal.ordercheck.data.db.StockRecordEntity
import com.tyrdal.ordercheck.domain.Outcome
import com.tyrdal.ordercheck.domain.StockInput
import com.tyrdal.ordercheck.scanner.ScanInput
import com.tyrdal.ordercheck.ui.theme.Palette
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.math.BigDecimal
import java.text.NumberFormat
import java.util.Calendar
import java.util.Locale

/** Counting screen state. Every scan goes to this stocktake; the count is typed, then saved locally at once. */
class StocktakeViewModel(private val app: App, val taskId: Long) : ViewModel() {
    enum class Msg { SAVED, AUTO_SAVED, NEED_QTY, BAD_PRICE, CLOSED, NEED_TITLE, CHOOSE_TITLE }
    enum class Focus { QTY, TITLE, NONE }

    val task = app.db.stock().task(taskId).stateIn(viewModelScope, SharingStarted.Eagerly, null)
    val records = app.db.stock().records(taskId).stateIn(viewModelScope, SharingStarted.Eagerly, emptyList())
    val unsynced = app.db.stock().unsyncedFor(taskId).stateIn(viewModelScope, SharingStarted.Eagerly, 0)

    var entry by mutableStateOf<StockStore.Lookup?>(null); private set
    var qty by mutableStateOf("")
    var price by mutableStateOf("")
    /** Title chosen from the stocktake master (several titles: the counter picks one). */
    var chosenTitle by mutableStateOf<String?>(null); private set
    /** Typing a title: the barcode is not in the master, or the counter chose "other title". */
    var typing by mutableStateOf(false); private set
    var typedTitle by mutableStateOf("")
    /** Bumped whenever focus should move (new barcode, title chosen) to `focus`. */
    var focusSeq by mutableIntStateOf(0); private set
    var focus by mutableStateOf(Focus.QTY); private set

    private fun focusOn(f: Focus) { focus = f; focusSeq++ }
    private val _msgs = Channel<Msg>(Channel.BUFFERED)
    val msgs = _msgs.receiveAsFlow()
    private val lock = Mutex()

    private val countable get() = task.value?.countable == true

    fun onScan(s: ScanInput) {
        if (s.duplicate) return // scanner double-read
        viewModelScope.launch { setBarcode(s.raw) }
    }

    /** A wedge scanner typing into the quantity field: a barcode is longer than any count. */
    fun onQtyChange(v: String) {
        val digits = StockInput.asciiDigits(v).filter { it.isDigit() }
        if (digits.length > 8) { qty = ""; viewModelScope.launch { setBarcode(digits) }; return }
        qty = v
    }

    suspend fun setBarcode(raw: String) = lock.withLock {
        if (!countable) { app.feedback.play(Outcome.LOCKED); _msgs.send(Msg.CLOSED); return@withLock }
        // Scanning the next item saves the current one if its count is filled in.
        if (entry != null && StockInput.quantity(qty) != null) {
            if (!saveLocked(auto = true)) return@withLock
        }
        val l = app.stock.lookup(taskId, raw) ?: return@withLock
        entry = l
        qty = ""
        price = ""
        typedTitle = ""
        chosenTitle = l.titles.singleOrNull()
        typing = l.titles.isEmpty()
        app.feedback.play(Outcome.COUNTED) // not being in the master is normal: vendors define their own barcodes
        focusOn(when { l.titles.isEmpty() -> Focus.TITLE; l.titles.size == 1 -> Focus.QTY; else -> Focus.NONE })
    }

    fun chooseTitle(t: String) { chosenTitle = t; typing = false; focusOn(Focus.QTY) }

    fun otherTitle() { chosenTitle = null; typing = true; focusOn(Focus.TITLE) }

    /** Title field "Next": on to the count. */
    fun titleDone() { focusOn(Focus.QTY)
    }

    fun save() { viewModelScope.launch { lock.withLock { saveLocked(auto = false) } } }

    fun clear() { entry = null; qty = ""; price = ""; typedTitle = ""; chosenTitle = null; typing = false }

    private suspend fun saveLocked(auto: Boolean): Boolean {
        val l = entry ?: return false
        if (!countable) { _msgs.send(Msg.CLOSED); return false }
        val title = if (typing) typedTitle.trim().replace(Regex("\\s+"), " ") else chosenTitle
        if (title.isNullOrEmpty()) {
            app.feedback.play(Outcome.INVALID)
            _msgs.send(if (typing) Msg.NEED_TITLE else Msg.CHOOSE_TITLE)
            return false
        }
        val q = StockInput.quantity(qty) ?: run { app.feedback.play(Outcome.INVALID); _msgs.send(Msg.NEED_QTY); return false }
        val p = when (val r = StockInput.price(price)) {
            StockInput.Price.Empty -> null
            StockInput.Price.Invalid -> { app.feedback.play(Outcome.INVALID); _msgs.send(Msg.BAD_PRICE); return false }
            is StockInput.Price.Value -> r.text
        }
        app.stock.add(taskId, l, title, typing, q, p)
        app.feedback.play(Outcome.LINE_COMPLETE)
        clear()
        app.sync.trigger()
        _msgs.send(if (auto) Msg.AUTO_SAVED else Msg.SAVED)
        return true
    }

    fun edit(id: String, qtyText: String, priceText: String, titleText: String): Boolean {
        val title = titleText.trim().replace(Regex("\\s+"), " ")
        if (title.isEmpty()) return false
        val q = StockInput.quantity(qtyText) ?: return false
        val p = when (val r = StockInput.price(priceText)) {
            StockInput.Price.Empty -> null
            StockInput.Price.Invalid -> return false
            is StockInput.Price.Value -> r.text
        }
        viewModelScope.launch { app.stock.edit(id, q, p, title); app.sync.trigger() }
        return true
    }

    fun delete(id: String) { viewModelScope.launch { app.stock.delete(id); app.sync.trigger() } }
}

fun formatPrice(p: String): String = runCatching { NumberFormat.getInstance(Locale.getDefault()).format(BigDecimal(p)) }.getOrDefault(p)

private fun hhmm(ms: Long): String {
    val c = Calendar.getInstance().apply { timeInMillis = ms }
    return String.format(Locale.getDefault(), "%02d:%02d", c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE))
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StocktakeScreen(taskId: Long, onBack: () -> Unit) {
    val app = LocalContext.current.app
    val vm: StocktakeViewModel = viewModel(key = "stock-$taskId") { StocktakeViewModel(app, taskId) }
    val task by vm.task.collectAsState()
    val records by vm.records.collectAsState()
    var query by remember { mutableStateOf("") }
    var manual by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<StockRecordEntity?>(null) }
    val snack = remember { SnackbarHostState() }
    val qtyFocus = remember { FocusRequester() }
    val texts = mapOf(
        StocktakeViewModel.Msg.SAVED to stringResource(R.string.st_saved),
        StocktakeViewModel.Msg.AUTO_SAVED to stringResource(R.string.st_auto_saved),
        StocktakeViewModel.Msg.NEED_QTY to stringResource(R.string.st_need_qty),
        StocktakeViewModel.Msg.BAD_PRICE to stringResource(R.string.st_bad_price),
        StocktakeViewModel.Msg.CLOSED to stringResource(R.string.st_closed),
        StocktakeViewModel.Msg.NEED_TITLE to stringResource(R.string.st_need_title),
        StocktakeViewModel.Msg.CHOOSE_TITLE to stringResource(R.string.st_choose_title),
    )

    LaunchedEffect(taskId) { app.scanner.scans.collect { vm.onScan(it) } }
    LaunchedEffect(taskId) {
        vm.msgs.collect { m -> snack.currentSnackbarData?.dismiss(); launch { snack.showSnackbar(texts.getValue(m)) } }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                navigationIcon = { IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Filled.ArrowBack, stringResource(R.string.back)) } },
                title = {
                    Column {
                        Text(task?.vendor ?: "", maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(task?.date?.let { jalaliDate(it) } ?: "", style = MaterialTheme.typography.bodySmall)
                    }
                },
                actions = { SyncIndicator() },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = Palette.TealDark, titleContentColor = Color.White,
                    navigationIconContentColor = Color.White, actionIconContentColor = Color.White,
                ),
            )
        },
        snackbarHost = { SnackbarHost(snack) },
    ) { pad ->
        Column(Modifier.padding(pad).fillMaxSize()) {
            val t = task
            if (t != null && !t.countable) {
                Text(
                    if (t.status == "closed") stringResource(R.string.st_closed) else stringResource(R.string.st_not_started, jalaliDate(t.date)),
                    color = Color.White, modifier = Modifier.fillMaxWidth().background(Palette.Bad).padding(10.dp),
                )
            }
            val failed = records.count { it.error != null }
            if (failed > 0) {
                val why = if (records.any { it.error == "stocktake_closed" }) stringResource(R.string.st_err_closed) else stringResource(R.string.st_err_other)
                Text(stringResource(R.string.st_not_sent, failed, why), color = Color.White,
                    modifier = Modifier.fillMaxWidth().background(Palette.Warn).padding(10.dp))
            }

            EntryCard(vm, qtyFocus, enabled = t?.countable == true, onManual = { manual = true })

            Row(Modifier.fillMaxWidth().padding(horizontal = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(stringResource(R.string.st_my_records, records.size), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                Text("${n(records.sumOf { it.quantity })} ${stringResource(R.string.units)}", style = MaterialTheme.typography.titleSmall, color = Palette.TealDark)
            }
            ScanSafeTextField(query, { query = it }, stringResource(R.string.st_search), Modifier.fillMaxWidth().padding(horizontal = 10.dp, vertical = 4.dp))
            val q = query.trim().lowercase()
            val list = if (q.isEmpty()) records else records.filter { it.barcode.contains(q) || (it.title ?: "").lowercase().contains(q) }
            if (list.isEmpty()) {
                Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text(stringResource(R.string.st_no_records), color = Palette.Muted) }
            } else {
                LazyColumn(contentPadding = PaddingValues(8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    items(list, key = { it.id }) { r -> RecordRow(r) { if (t?.countable == true) editing = r } }
                }
            }
        }
        if (manual) ManualBarcodeDialog(onDismiss = { manual = false }) { code -> manual = false; app.appScope.launch { vm.setBarcode(code) } }
        editing?.let { r -> EditDialog(r, onDismiss = { editing = null }, onSave = { qt, pr, ti -> vm.edit(r.id, qt, pr, ti).also { if (it) editing = null } },
            onDelete = { vm.delete(r.id); editing = null }) }
    }
}

@Composable
private fun EntryCard(vm: StocktakeViewModel, qtyFocus: FocusRequester, enabled: Boolean, onManual: () -> Unit) {
    val app = LocalContext.current.app
    val e = vm.entry
    val titleFocus = remember { FocusRequester() }
    // After each scan focus moves to where the counter types next (title if unknown, else the count).
    LaunchedEffect(vm.focusSeq) {
        if (vm.entry == null || vm.focus == StocktakeViewModel.Focus.NONE) return@LaunchedEffect
        delay(60)
        runCatching { (if (vm.focus == StocktakeViewModel.Focus.TITLE) titleFocus else qtyFocus).requestFocus() }
    }
    Card(Modifier.fillMaxWidth().padding(10.dp)) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (e == null) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.heightIn(min = 72.dp)) {
                    Text(stringResource(R.string.st_scan_prompt), style = MaterialTheme.typography.titleLarge, color = Palette.Muted, modifier = Modifier.weight(1f))
                    OutlinedButton(onClick = onManual, enabled = enabled) { Icon(Icons.Filled.Keyboard, null); Spacer(Modifier.width(6.dp)); Text(stringResource(R.string.manual_entry)) }
                }
                return@Column
            }
            Text(ltr(e.barcode), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            TitlePicker(vm, e, titleFocus)
            if (e.total.records > 0) Text(stringResource(R.string.st_already, e.total.quantity, e.total.records), color = Palette.TealDark, style = MaterialTheme.typography.bodyMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                NumberField(vm.qty, vm::onQtyChange, stringResource(R.string.st_quantity), KeyboardType.Number,
                    Modifier.weight(1f).focusRequester(qtyFocus), app.scanner) { vm.save() }
                NumberField(vm.price, { vm.price = it }, stringResource(R.string.st_price), KeyboardType.Decimal,
                    Modifier.weight(1f), app.scanner) { vm.save() }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = vm::clear, modifier = Modifier.height(56.dp)) { Text(stringResource(R.string.st_clear)) }
                Button(onClick = vm::save, enabled = enabled, modifier = Modifier.weight(1f).height(56.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = Palette.Teal)) {
                    Text(stringResource(R.string.save), fontSize = 20.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TitlePicker(vm: StocktakeViewModel, e: StockStore.Lookup, titleFocus: FocusRequester) {
    val scanner = LocalContext.current.app.scanner
    if (e.titles.size >= 2 && !vm.typing) Text(stringResource(R.string.st_choose_title), color = Palette.Warn, style = MaterialTheme.typography.bodyMedium)
    if (e.titles.isNotEmpty()) {
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
            e.titles.forEach { t ->
                FilterChip(selected = !vm.typing && vm.chosenTitle == t, onClick = { vm.chooseTitle(t) },
                    label = { Text(t, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(vertical = 8.dp)) })
            }
            FilterChip(selected = vm.typing, onClick = vm::otherTitle,
                label = { Text(stringResource(R.string.st_other_title), modifier = Modifier.padding(vertical = 8.dp)) })
        }
    }
    if (vm.typing) {
        if (e.titles.isEmpty()) Text(stringResource(R.string.st_not_in_master), color = Palette.Muted, style = MaterialTheme.typography.bodyMedium)
        OutlinedTextField(
            value = vm.typedTitle, onValueChange = { vm.typedTitle = it }, label = { Text(stringResource(R.string.st_title)) }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, imeAction = ImeAction.Next),
            keyboardActions = KeyboardActions(onNext = { vm.titleDone() }),
            modifier = Modifier.fillMaxWidth().focusRequester(titleFocus).onFocusChanged { scanner.textInputActive = it.isFocused },
        )
    }
}

@Composable
private fun NumberField(value: String, onChange: (String) -> Unit, label: String, type: KeyboardType, modifier: Modifier,
                        scanner: com.tyrdal.ordercheck.scanner.ScannerManager, onDone: () -> Unit) {
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true,
        textStyle = MaterialTheme.typography.headlineSmall.copy(textDirection = TextDirection.Ltr, fontWeight = FontWeight.Bold),
        keyboardOptions = KeyboardOptions(keyboardType = type, imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { onDone() }),
        modifier = modifier.onFocusChanged { scanner.textInputActive = it.isFocused },
    )
}

@Composable
private fun RecordRow(r: StockRecordEntity, onClick: () -> Unit) {
    Card(Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(r.title?.takeIf { it.isNotBlank() } ?: ltr(r.barcode), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (!r.title.isNullOrBlank()) Text(ltr(r.barcode), style = MaterialTheme.typography.bodySmall, color = Palette.Muted)
                    Text(hhmm(r.countedAt), style = MaterialTheme.typography.bodySmall, color = Palette.Muted)
                    r.price?.let { Text(stringResource(R.string.st_price_n, formatPrice(it)), style = MaterialTheme.typography.bodySmall) }
                }
            }
            Text(n(r.quantity), fontSize = 24.sp, fontWeight = FontWeight.Bold, color = Palette.TealDark, modifier = Modifier.padding(horizontal = 10.dp))
            val (icon, tint) = when {
                r.error != null -> Icons.Filled.ErrorOutline to Palette.Bad
                !r.synced -> Icons.Filled.CloudUpload to Palette.Warn
                else -> Icons.Filled.CloudDone to Palette.Ok
            }
            Icon(icon, null, tint = tint, modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
private fun EditDialog(r: StockRecordEntity, onDismiss: () -> Unit, onSave: (String, String, String) -> Unit, onDelete: () -> Unit) {
    val scanner = LocalContext.current.app.scanner
    var qty by remember { mutableStateOf(n(r.quantity)) }
    var price by remember { mutableStateOf(r.price ?: "") }
    var title by remember { mutableStateOf(r.title ?: "") }
    var confirmDelete by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.st_edit)) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(ltr(r.barcode), color = Palette.Muted)
                OutlinedTextField(title, { title = it }, label = { Text(stringResource(R.string.st_title)) }, singleLine = true,
                    modifier = Modifier.fillMaxWidth().onFocusChanged { scanner.textInputActive = it.isFocused })
                NumberField(qty, { qty = it }, stringResource(R.string.st_quantity), KeyboardType.Number, Modifier.fillMaxWidth(), scanner) { onSave(qty, price, title) }
                NumberField(price, { price = it }, stringResource(R.string.st_price), KeyboardType.Decimal, Modifier.fillMaxWidth(), scanner) { onSave(qty, price, title) }
                TextButton(onClick = { confirmDelete = true }) { Text(stringResource(R.string.st_delete), color = Palette.Bad) }
            }
        },
        confirmButton = { TextButton(onClick = { onSave(qty, price, title) }) { Text(stringResource(R.string.save)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
    if (confirmDelete) {
        AlertDialog(
            onDismissRequest = { confirmDelete = false },
            text = { Text(stringResource(R.string.st_delete_confirm)) },
            confirmButton = { TextButton(onClick = { confirmDelete = false; onDelete() }) { Text(stringResource(R.string.st_delete), color = Palette.Bad) } },
            dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

@Composable
private fun ManualBarcodeDialog(onDismiss: () -> Unit, onSubmit: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.manual_entry)) },
        text = { ScanSafeTextField(text, { text = it.filter { c -> !c.isWhitespace() } }, stringResource(R.string.enter_barcode), Modifier.fillMaxWidth(), ltrInput = true, keyboardType = KeyboardType.Number, imeAction = ImeAction.Done, onImeAction = { if (text.length >= 4) onSubmit(text) }) },
        confirmButton = { TextButton(enabled = text.length >= 4, onClick = { onSubmit(text) }) { Text(stringResource(R.string.apply)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}
