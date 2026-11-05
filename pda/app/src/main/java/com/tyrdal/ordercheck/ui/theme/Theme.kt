package com.tyrdal.ordercheck.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import com.tyrdal.ordercheck.R

val Vazirmatn = FontFamily(
    Font(R.font.vazirmatn_regular, FontWeight.Normal),
    Font(R.font.vazirmatn_medium, FontWeight.Medium),
    Font(R.font.vazirmatn_bold, FontWeight.Bold),
)

object Palette {
    val Teal = Color(0xFF0F766E)
    val TealDark = Color(0xFF0B3B38)
    val Ok = Color(0xFF15803D)
    val OkBg = Color(0xFFDCFCE7)
    val Warn = Color(0xFFB45309)
    val WarnBg = Color(0xFFFEF3C7)
    val Bad = Color(0xFFB91C1C)
    val BadBg = Color(0xFFFEE2E2)
    val Extra = Color(0xFF7E22CE)
    val ExtraBg = Color(0xFFF3E8FF)
    val Muted = Color(0xFF64748B)
    val Surface = Color(0xFFF4F6F8)
}

private val base = Typography()
private fun TextStyle.v() = copy(fontFamily = Vazirmatn)

val AppTypography = Typography(
    headlineSmall = base.headlineSmall.v().copy(fontWeight = FontWeight.Bold),
    titleLarge = base.titleLarge.v().copy(fontWeight = FontWeight.Bold, fontSize = 21.sp),
    titleMedium = base.titleMedium.v().copy(fontWeight = FontWeight.Bold, fontSize = 17.sp),
    titleSmall = base.titleSmall.v(),
    bodyLarge = base.bodyLarge.v().copy(fontSize = 17.sp),
    bodyMedium = base.bodyMedium.v().copy(fontSize = 15.sp),
    bodySmall = base.bodySmall.v().copy(fontSize = 13.sp),
    labelLarge = base.labelLarge.v().copy(fontSize = 16.sp, fontWeight = FontWeight.Bold),
    labelMedium = base.labelMedium.v(),
    labelSmall = base.labelSmall.v(),
    displaySmall = base.displaySmall.v().copy(fontWeight = FontWeight.Bold),
)

@Composable
fun OrderCheckTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Palette.Teal, onPrimary = Color.White, primaryContainer = Color(0xFFCCFBF1),
            secondary = Palette.TealDark, background = Palette.Surface, surface = Color.White,
            error = Palette.Bad,
        ),
        typography = AppTypography,
        content = content,
    )
}
