package com.leaktrace.android.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class LeakTraceDestinationTest {

    @Test
    fun startDestinationIsHome() {
        assertEquals(LeakTraceDestination.Home, LeakTraceDestination.start)
    }

    @Test
    fun routesAreUnique() {
        val routes = LeakTraceDestination.entries.map { it.route }
        assertEquals(routes.size, routes.toSet().size)
    }

    @Test
    fun fromRouteResolvesEveryDestination() {
        LeakTraceDestination.entries.forEach { destination ->
            assertEquals(destination, LeakTraceDestination.fromRoute(destination.route))
        }
    }

    @Test
    fun fromRouteReturnsNullForUnknownRoute() {
        assertNull(LeakTraceDestination.fromRoute("does-not-exist"))
        assertNull(LeakTraceDestination.fromRoute(null))
    }
}
