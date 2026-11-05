package com.tyrdal.ordercheck.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.tyrdal.ordercheck.R
import com.tyrdal.ordercheck.app
import com.tyrdal.ordercheck.data.ApiException
import com.tyrdal.ordercheck.data.OfflineException
import com.tyrdal.ordercheck.ui.theme.Palette
import kotlinx.coroutines.launch

@Composable
fun LoginScreen(onSettings: () -> Unit) {
    val app = LocalContext.current.app
    val scope = rememberCoroutineScope()
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<Int?>(null) }

    Box(Modifier.fillMaxSize().background(Palette.TealDark)) {
        IconButton(onClick = onSettings, modifier = Modifier.align(Alignment.TopEnd).padding(8.dp)) {
            Icon(Icons.Filled.Settings, stringResource(R.string.settings), tint = Color.White)
        }
        Column(
            Modifier.align(Alignment.Center).fillMaxWidth().verticalScroll(rememberScrollState()).padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Image(painterResource(R.drawable.ic_launcher_foreground), null, Modifier.size(96.dp))
            Text(stringResource(R.string.app_name), style = MaterialTheme.typography.headlineSmall, color = Color.White)
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    val submit: () -> Unit = submit@{
                        if (busy || username.isBlank() || password.isBlank()) return@submit
                        busy = true
                        scope.launch {
                                error = try {
                                    app.login(username.trim(), password); null
                                } catch (e: OfflineException) {
                                    R.string.network_error
                                } catch (e: ApiException) {
                                    when {
                                        e.code == "no_server" -> R.string.no_server
                                        e.code == "not_a_checker" -> R.string.not_a_checker
                                        e.status == 401 -> R.string.login_failed
                                        else -> R.string.network_error
                                    }
                                } finally { busy = false }
                            }
                    }
                    // Keyboard "Next" moves to the password, "Done" signs in: no precise taps needed on a PDA.
                    ScanSafeTextField(username, { username = it; error = null }, stringResource(R.string.username), Modifier.fillMaxWidth(),
                        ltrInput = true, imeAction = ImeAction.Next)
                    ScanSafeTextField(password, { password = it; error = null }, stringResource(R.string.password), Modifier.fillMaxWidth(),
                        ltrInput = true, isPassword = true, imeAction = ImeAction.Done, onImeAction = submit)
                    error?.let { Text(stringResource(it), color = Palette.Bad, style = MaterialTheme.typography.bodyMedium) }
                    Button(
                        enabled = !busy && username.isNotBlank() && password.isNotBlank(),
                        modifier = Modifier.fillMaxWidth().height(56.dp),
                        onClick = submit,
                    ) {
                        if (busy) CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp, modifier = Modifier.size(22.dp))
                        else Text(stringResource(R.string.login))
                    }
                }
            }
            Text(ltr(app.prefs.serverUrl), color = Color.White.copy(alpha = 0.7f), style = MaterialTheme.typography.bodySmall)
        }
    }
}
