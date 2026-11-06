package com.rrniii.ukwsrvisualizer

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.LocationManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.*

@Composable
internal fun VisualizerApp(model: VisualizerViewModel) {
    val state by model.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var catalogue by remember { mutableStateOf(false) }
    var recent by remember { mutableStateOf(false) }
    var advanced by remember { mutableStateOf(false) }
    var export by remember { mutableStateOf(false) }
    val maps = remember { mutableMapOf<Int, RadarMapView>() }
    var sharedViewport by remember { mutableStateOf<Viewport?>(null) }
    val current = state.panels[state.active]
    fun locate() {
        try {
            val manager = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
            val best =
                manager
                    .getProviders(true)
                    .mapNotNull { runCatching { manager.getLastKnownLocation(it) }.getOrNull() }
                    .maxByOrNull { it.time }
            if (best != null) model.nearest(best.latitude, best.longitude)
            else model.message("Location is not available yet. Select a radar from the catalogue.")
        } catch (_: SecurityException) {
            model.message("Location permission is unavailable; select a radar manually.")
        }
    }
    val permission =
        rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) locate()
            else model.message("Location declined. Manual catalogue selection remains available.")
        }
    LaunchedEffect(state.root) {
        if (
            state.root != null &&
                state.recent.isEmpty() &&
                ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                ) == PackageManager.PERMISSION_GRANTED
        )
            locate()
    }
    Scaffold(
        topBar = {
            Column(
                Modifier.background(MaterialTheme.colorScheme.surface)
                    .statusBarsPadding()
                    .padding(horizontal = 16.dp, vertical = 10.dp)
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            "UK WSR",
                            fontSize = 24.sp,
                            fontWeight = FontWeight.Bold,
                            color = MaterialTheme.colorScheme.primary,
                        )
                        Text("RADAR VISUALIZER", fontSize = 10.sp, letterSpacing = 2.sp)
                    }
                    TextButton(onClick = { model.refresh() }) { Text("Refresh") }
                    TextButton(
                        onClick = {
                            model.message(
                                "UK WSR Visualizer Android ${BuildConfig.VERSION_NAME} (${BuildConfig.VERSION_CODE})\nSource ${BuildConfig.GIT_SHA}\nQC: preservation-first safe baseline. Source PVOLs stay unchanged.\nMet Office radar data accessed through NCAS/JASMIN.\n© OpenStreetMap contributors.\nSoftware: BSD-3-Clause; see repository citation and dependency notices."
                            )
                        }
                    ) {
                        Text("About")
                    }
                }
                Text(
                    state.catalogueStatus,
                    fontSize = 11.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 2,
                )
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("View", "Compare", "Projects").forEach { mode ->
                        FilterChip(
                            selected = state.mode == mode,
                            onClick = { model.mode(mode) },
                            label = { Text(mode) },
                            modifier = Modifier.weight(1f),
                        )
                    }
                }
            }
        }
    ) { insets ->
        BoxWithConstraints(Modifier.padding(insets).fillMaxSize()) {
            val wide = maxWidth >= 840.dp
            if (state.mode == "Projects") ProjectScreen(model, state)
            else {
                val controls: @Composable () -> Unit = {
                    Controls(
                        model,
                        state,
                        onCatalogue = { catalogue = true },
                        onRecent = { recent = true },
                        onAdvanced = { advanced = true },
                        onExport = { export = true },
                        onNearest = {
                            if (
                                ContextCompat.checkSelfPermission(
                                    context,
                                    Manifest.permission.ACCESS_COARSE_LOCATION,
                                ) == PackageManager.PERMISSION_GRANTED
                            )
                                locate()
                            else permission.launch(Manifest.permission.ACCESS_COARSE_LOCATION)
                        },
                    )
                }
                val plots: @Composable () -> Unit = {
                    Column(Modifier.fillMaxSize()) {
                        val count = if (state.mode == "Compare") 4 else 1
                        for (row in 0 until if (count == 4) 2 else 1) Row(
                            Modifier.weight(1f).fillMaxWidth()
                        ) {
                            for (col in 0 until if (count == 4) 2 else 1) {
                                val index = row * 2 + col
                                val p = state.panels[index]
                                Column(
                                    Modifier.weight(1f)
                                        .fillMaxHeight()
                                        .padding(3.dp)
                                        .border(
                                            if (state.active == index) 2.dp else 1.dp,
                                            if (state.active == index)
                                                MaterialTheme.colorScheme.primary
                                            else Color(0xffdce3e5),
                                            RoundedCornerShape(8.dp),
                                        )
                                        .clickable { model.active(index) }
                                ) {
                                    Row(
                                        Modifier.fillMaxWidth()
                                            .background(
                                                if (state.active == index) Color(0xffe3f2ef)
                                                else Color(0xfff5f7f7)
                                            )
                                            .padding(horizontal = 8.dp, vertical = 3.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        TextButton(
                                            onClick = { model.active(index) },
                                            contentPadding = PaddingValues(0.dp),
                                        ) {
                                            Text(
                                                if (count == 4)
                                                    "${'A'+index} · ${p.spec.selection.radar.ifEmpty{"Choose scan"}}"
                                                else
                                                    p.spec.selection.radar.ifEmpty {
                                                        "Choose scan"
                                                    },
                                                maxLines = 1,
                                            )
                                        }
                                        Spacer(Modifier.weight(1f))
                                        TextButton(
                                            onClick = { maps[index]?.fit() },
                                            contentPadding = PaddingValues(0.dp),
                                        ) {
                                            Text("Fit", fontSize = 11.sp)
                                        }
                                    }
                                    if (p.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                                    if (p.error != null)
                                        Text(
                                            p.error,
                                            Modifier.padding(8.dp),
                                            color = MaterialTheme.colorScheme.error,
                                            fontSize = 12.sp,
                                        )
                                    var readout by remember(index) { mutableStateOf("") }
                                    AndroidView(
                                        factory = { ctx ->
                                            RadarMapView(ctx).apply {
                                                contentDescription = "Radar panel ${'A'+index}"
                                                onIdentify = { text ->
                                                    model.active(index)
                                                    readout = text
                                                }
                                                onViewport = { v ->
                                                    if (state.links.view) sharedViewport = v
                                                }
                                                maps[index] = this
                                            }
                                        },
                                        update = { view ->
                                            view.onRendered = { model.frameRendered(index, it) }
                                            view.show(p.data)
                                            view.onViewport = { v ->
                                                if (state.links.view) sharedViewport = v
                                            }
                                            if (state.links.view)
                                                sharedViewport?.let(view::setViewport)
                                        },
                                        modifier = Modifier.fillMaxWidth().weight(1f),
                                        onRelease = {
                                            it.release()
                                            maps.remove(index)
                                        },
                                    )
                                    Text(
                                        p.data?.let {
                                            "${it.spec.selection.date} ${it.spec.selection.time} UTC · ${it.spec.selection.pulse.uppercase()} · ${it.field.quantity} %.2f°"
                                                .format(it.field.elevationDeg)
                                        } ?: "Source data only · no simulated fallback",
                                        Modifier.padding(6.dp),
                                        fontSize = 10.sp,
                                        maxLines = 2,
                                    )
                                    if (readout.isNotEmpty())
                                        Text(
                                            readout,
                                            Modifier.padding(horizontal = 6.dp, vertical = 3.dp),
                                            fontSize = 10.sp,
                                            maxLines = 3,
                                        )
                                }
                            }
                        }
                    }
                }
                if (wide)
                    Row(Modifier.fillMaxSize()) {
                        Box(
                            Modifier.width(310.dp)
                                .fillMaxHeight()
                                .verticalScroll(rememberScrollState())
                                .padding(12.dp)
                        ) {
                            controls()
                        }
                        Box(Modifier.weight(1f).fillMaxHeight()) { plots() }
                    }
                else
                    Column(Modifier.fillMaxSize()) {
                        Box(Modifier.weight(if (state.mode == "Compare") 0.65f else 0.6f)) {
                            plots()
                        }
                        Box(
                            Modifier.weight(if (state.mode == "Compare") 0.35f else 0.4f)
                                .fillMaxWidth()
                                .verticalScroll(rememberScrollState())
                                .padding(12.dp)
                        ) {
                            controls()
                        }
                    }
            }
        }
    }
    if (catalogue) CatalogueDialog(model, state, onClose = { catalogue = false })
    if (recent)
        AlertDialog(
            onDismissRequest = { recent = false },
            title = { Text("Recent selections") },
            text = {
                LazyColumn {
                    items(state.recent) { selection ->
                        TextButton(
                            onClick = {
                                model.load(state.active, selection)
                                recent = false
                            }
                        ) {
                            Text(selection.label)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { recent = false }) { Text("Close") } },
        )
    if (advanced)
        AdvancedDialog(
            current.spec,
            onClose = { advanced = false },
            onFilters = model::filters,
            onDisplay = model::display,
        )
    if (export)
        ExportDialog(
            current,
            onClose = { export = false },
            onPNG = {
                export = false
                scope.launch {
                    runCatching {
                        val data = current.data ?: error("Render a scan first")
                        val image = maps[state.active]?.snapshot() ?: error("No rendered map")
                        val files = ArtifactExporter(context, model.repository).png(data, image)
                        ArtifactExporter.share(context, files)
                    }
                        .onFailure { model.message(it.message ?: "PNG export failed") }
                }
            },
            onSource = {
                export = false
                scope.launch {
                    runCatching {
                        ArtifactExporter.share(
                            context,
                            ArtifactExporter(context, model.repository)
                                .source(current.data ?: error("Render a scan first")),
                        )
                    }
                        .onFailure { model.message(it.message ?: "Source export failed") }
                }
            },
            onMetadata = {
                export = false
                scope.launch {
                    current.data?.let {
                        ArtifactExporter.share(
                            context,
                            ArtifactExporter(context, model.repository).metadata(it),
                        )
                    }
                }
            },
            onVideo = { times ->
                export = false
                current.data?.let {
                    model.export(it, times) { files -> ArtifactExporter.share(context, files) }
                }
            },
        )
    state.message?.let { text ->
        AlertDialog(
            onDismissRequest = model::dismissMessage,
            title = { Text("UK WSR") },
            text = { Text(text) },
            confirmButton = { TextButton(onClick = model::dismissMessage) { Text("OK") } },
        )
    }
    state.exportProgress?.let { text ->
        AlertDialog(
            onDismissRequest = {},
            title = { Text("Exporting MP4") },
            text = {
                Column {
                    LinearProgressIndicator(Modifier.fillMaxWidth())
                    Spacer(Modifier.height(12.dp))
                    Text(text)
                    Text(
                        "Keep the app open. Completed frames are saved so the same export can resume.",
                        fontSize = 12.sp,
                    )
                }
            },
            confirmButton = { TextButton(onClick = model::cancelExport) { Text("Cancel") } },
        )
    }
}
