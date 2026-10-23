package com.leaktrace.android

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import com.leaktrace.android.ui.LeakTraceApp
import com.leaktrace.android.ui.theme.LeakTraceTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            LeakTraceTheme {
                LeakTraceApp()
            }
        }
    }
}
