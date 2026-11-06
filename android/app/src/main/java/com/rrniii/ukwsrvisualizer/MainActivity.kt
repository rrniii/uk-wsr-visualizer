package com.rrniii.ukwsrvisualizer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.graphics.Color
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.*

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(
                colorScheme =
                    lightColorScheme(
                        primary = Color(0xff087d77),
                        secondary = Color(0xff366179),
                        secondaryContainer = Color(0xffdceeea),
                        onSecondaryContainer = Color(0xff064944),
                        primaryContainer = Color(0xffdceeea),
                        background = Color(0xfff6f8f8),
                        surface = Color.White,
                    )
            ) {
                val model: VisualizerViewModel = viewModel { VisualizerViewModel(application) }
                VisualizerApp(model)
            }
        }
    }
}
