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

    /** Repeats until the checker answers the extra / not-in-order dialog. */
    fun startAlarm() {
        alarm?.cancel()
        alarm = scope.launch {
            var n = 0
            while (isActive && n < 20) {
                tone(ToneGenerator.TONE_CDMA_HIGH_PBX_L, 700)
                vibrate(longArrayOf(0, 500))
                delay(1500)
                n++
            }
        }
    }

    fun stopAlarm() { alarm?.cancel(); alarm = null; tones?.stopTone() }

    private fun tone(t: Int, ms: Int) { runCatching { tones?.startTone(t, ms) } }

    private fun vibrate(pattern: LongArray) {
        runCatching { vibrator?.vibrate(VibrationEffect.createWaveform(pattern, -1)) }
    }
}
