package com.leaktrace.android.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val LightColors = lightColorScheme(
    primary = TraceTeal,
    onPrimary = Paper,
    secondary = LeakAmber,
    onSecondary = Paper,
    secondaryContainer = Mist,
    onSecondaryContainer = DeepTeal,
    background = Paper,
    onBackground = Ink,
    surface = Paper,
    onSurface = Ink,
)

private val DarkColors = darkColorScheme(
    primary = TraceTealLight,
    onPrimary = DeepTeal,
    secondary = LeakAmberLight,
    onSecondary = Ink,
    secondaryContainer = DeepTeal,
    onSecondaryContainer = Mist,
    background = Ink,
    onBackground = Mist,
    surface = Ink,
    onSurface = Mist,
)

// Brand colours are used deliberately instead of Material You dynamic colour so LeakTrace looks consistent.
@Composable
fun LeakTraceTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = LeakTraceTypography,
        content = content,
    )
}
