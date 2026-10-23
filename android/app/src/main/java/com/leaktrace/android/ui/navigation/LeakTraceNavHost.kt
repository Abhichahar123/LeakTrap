package com.leaktrace.android.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import com.leaktrace.android.ui.about.AboutScreen
import com.leaktrace.android.ui.home.HomeScreen

@Composable
fun LeakTraceNavHost(
    navController: NavHostController,
    modifier: Modifier = Modifier,
) {
    NavHost(
        navController = navController,
        startDestination = LeakTraceDestination.start.route,
        modifier = modifier,
    ) {
        composable(LeakTraceDestination.Home.route) {
            HomeScreen(
                onOpenAbout = {
                    navController.navigate(LeakTraceDestination.About.route) { launchSingleTop = true }
                },
            )
        }
        composable(LeakTraceDestination.About.route) {
            AboutScreen(onNavigateBack = { navController.popBackStack() })
        }
    }
}
