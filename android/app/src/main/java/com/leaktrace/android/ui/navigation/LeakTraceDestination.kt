package com.leaktrace.android.ui.navigation

/**
 * Top-level screens reachable in the app. Later phases add their destinations here.
 */
enum class LeakTraceDestination(val route: String) {
    Home("home"),
    About("about");

    companion object {
        val start: LeakTraceDestination = Home

        fun fromRoute(route: String?): LeakTraceDestination? = entries.firstOrNull { it.route == route }
    }
}
