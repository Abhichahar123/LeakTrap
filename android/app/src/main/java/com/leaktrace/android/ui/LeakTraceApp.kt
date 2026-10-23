package com.leaktrace.android.ui

import androidx.compose.runtime.Composable
import androidx.navigation.compose.rememberNavController
import com.leaktrace.android.ui.navigation.LeakTraceNavHost

@Composable
fun LeakTraceApp() {
    val navController = rememberNavController()
    LeakTraceNavHost(navController = navController)
}
