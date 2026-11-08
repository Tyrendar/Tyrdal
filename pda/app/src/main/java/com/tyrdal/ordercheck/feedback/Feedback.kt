package com.tyrdal.ordercheck.feedback

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import com.tyrdal.ordercheck.domain.Outcome
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Distinct sound + vibration per outcome so the checker rarely needs to look at
 * the screen. Uses the alarm stream so it stays audible in a noisy warehouse even
 * when media volume is down. No audio files: generated tones only.
 */
class Feedback(context: Context, private val scope: CoroutineScope) {
    private val tones = runCatching { ToneGenerator(AudioManager.STREAM_ALARM, 100) }.getOrNull()
    // Own generator so the warning is quieter than the normal beeps and never cuts them off.
    private val warn = runCatching { ToneGenerator(AudioManager.STREAM_ALARM, WARN_VOLUME) }.getOrNull()
    private val vibrator: Vibrator? = if (Build.VERSION.SDK_INT >= 31) {
        (context.getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager).defaultVibrator
    } else {
        @Suppress("DEPRECATION") context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
    }
    private var alarm: Job? = null

    fun play(outcome: Outcome) {
        when (outcome) {
            Outcome.COUNTED -> tone(ToneGenerator.TONE_PROP_BEEP, 80)
            Outcome.LINE_COMPLETE -> { tone(ToneGenerator.TONE_PROP_ACK, 160); vibrate(longArrayOf(0, 40)) }
            Outcome.DUPLICATE -> {}
            Outcome.UNKNOWN -> { tone(ToneGenerator.TONE_SUP_ERROR, 600); vibrate(longArrayOf(0, 300)) }
            Outcome.BLOCKED, Outcome.LOCKED, Outcome.INVALID -> { tone(ToneGenerator.TONE_PROP_NACK, 300); vibrate(longArrayOf(0, 200)) }
            Outcome.OVER, Outcome.NOT_IN_ORDER -> startAlarm()
            Outcome.REMOVED, Outcome.MISTAKE, Outcome.APPLIED -> { stopAlarm(); tone(ToneGenerator.TONE_PROP_BEEP2, 120) }
        }
    }

    /**
     * Extra / not-in-order warning: a short "pip-pip-pip" with a light double buzz, then a few
     * quiet reminders while the dialog is still open, then silence (the dialog stays on screen).
     */
    fun startAlarm() {
        alarm?.cancel()
        alarm = scope.launch {
            repeat(1 + REMINDERS) { i ->
                if (!isActive) return@launch
                if (i > 0) delay(REMINDER_EVERY_MS)
                chirp()
                if (i == 0) vibrate(longArrayOf(0, 80, 90, 80))
            }
        }
    }

    fun stopAlarm() { alarm?.cancel(); alarm = null; warn?.stopTone() }

    private suspend fun chirp() {
        repeat(3) {
            runCatching { warn?.startTone(ToneGenerator.TONE_PROP_BEEP, 70) }
            delay(160)
        }
    }

    private fun tone(t: Int, ms: Int) { runCatching { tones?.startTone(t, ms) } }

    private fun vibrate(pattern: LongArray) {
        runCatching { vibrator?.vibrate(VibrationEffect.createWaveform(pattern, -1)) }
    }

    private companion object {
        const val WARN_VOLUME = 70
        const val REMINDERS = 2
        const val REMINDER_EVERY_MS = 5_000L
    }
}
