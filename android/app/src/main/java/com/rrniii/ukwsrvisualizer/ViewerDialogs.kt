package com.rrniii.ukwsrvisualizer

import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.*

@Composable
internal fun CatalogueDialog(model: VisualizerViewModel, state: UiState, onClose: () -> Unit) {
    var query by remember { mutableStateOf("") }
    var radar by
        remember(state.root) {
            mutableStateOf(
                state.root?.radars?.find {
                    it.radar == state.panels[state.active].spec.selection.radar
                } ?: state.root?.radars?.firstOrNull()
            )
        }
    var year by remember(radar) { mutableStateOf(radar?.years?.maxOrNull() ?: "") }
    var days by remember { mutableStateOf<List<Day>>(emptyList()) }
    var status by remember { mutableStateOf("") }
    var dateFilter by remember { mutableStateOf("") }
    LaunchedEffect(radar, year) {
        val r = radar
        if (r != null && year.isNotEmpty()) {
            days = emptyList()
            status = "Loading year coverage…"
            try {
                days = model.days(r, year)
                status = "${days.size} published days"
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                status = e.message ?: "Coverage failed"
            }
        }
    }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Find radar data") },
        text = {
            Column(
                Modifier.heightIn(max = 570.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                DropChoice(
                    "Archive",
                    state.era.label,
                    DataEra.entries.map { it.label },
                    { label -> model.refresh(DataEra.entries.first { it.label == label }) },
                )
                OutlinedTextField(
                    query,
                    { query = it },
                    label = { Text("Search radar") },
                    singleLine = true,
                )
                DropChoice(
                    "Radar",
                    radar?.radar ?: "Choose",
                    state.root
                        ?.radars
                        ?.filter { it.radar.contains(query, true) }
                        ?.map { it.radar }
                        .orEmpty(),
                    { name -> radar = state.root?.radars?.find { it.radar == name } },
                )
                DropChoice("Year", year, radar?.years?.sortedDescending().orEmpty(), { year = it })
                OutlinedTextField(
                    dateFilter,
                    { dateFilter = it },
                    label = { Text("Filter date · YYYYMMDD") },
                    singleLine = true,
                )
                Text(status, fontSize = 12.sp)
                LazyColumn(Modifier.weight(1f, false)) {
                    items(
                        days.filter { it.date.contains(dateFilter.replace("-", "")) },
                        key = { it.date },
                    ) { day ->
                        TextButton(
                            onClick = {
                                radar?.let {
                                    model.load(
                                        state.active,
                                        Selection(
                                            era = state.era.name,
                                            radar = it.radar,
                                            date = day.date,
                                        ),
                                    )
                                }
                                onClose()
                            },
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Row(Modifier.fillMaxWidth()) {
                                Text(day.date, Modifier.weight(1f))
                                Text("${day.file_count} scans", fontSize = 12.sp)
                            }
                        }
                    }
                }
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text("Close") } },
    )
}

@Composable
internal fun AdvancedDialog(
    spec: PanelSpec,
    onClose: () -> Unit,
    onFilters: (Filters) -> Unit,
    onDisplay: (Display) -> Unit,
) {
    var f by remember { mutableStateOf(spec.filters) }
    var d by remember { mutableStateOf(spec.display) }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Display & filters") },
        text = {
            Column(
                Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                DropChoice(
                    "Palette",
                    d.palette,
                    listOf("auto", "reflectivity", "velocity", "viridis", "gray"),
                    { d = d.copy(palette = it) },
                )
                DropChoice(
                    "Background",
                    d.basemap,
                    listOf("osm", "grid"),
                    { d = d.copy(basemap = it) },
                )
                Text("Opacity ${"%.0f".format(d.opacity*100)}%")
                Slider(d.opacity, { d = d.copy(opacity = it) }, valueRange = 0.1f..1f)
                NumericPair(
                    "Display min",
                    d.min,
                    "Display max",
                    d.max,
                    { d = d.copy(min = it) },
                    { d = d.copy(max = it) },
                )
                NumericPair(
                    "Range min km",
                    f.min_range_km,
                    "Range max km",
                    f.max_range_km,
                    { f = f.copy(min_range_km = it) },
                    { f = f.copy(max_range_km = it) },
                )
                NumericPair(
                    "Azimuth from",
                    f.min_azimuth_deg,
                    "Azimuth to",
                    f.max_azimuth_deg,
                    { f = f.copy(min_azimuth_deg = it) },
                    { f = f.copy(max_azimuth_deg = it) },
                )
                NumericPair(
                    "Keep values ≥",
                    f.min_value,
                    "Keep values ≤",
                    f.max_value,
                    { f = f.copy(min_value = it) },
                    { f = f.copy(max_value = it) },
                )
                NumericPair(
                    "Height slice m",
                    f.cappi_height_m,
                    "Noise margin dB",
                    f.noise_floor_margin_db,
                    { f = f.copy(cappi_height_m = it) },
                    { f = f.copy(noise_floor_margin_db = it ?: 0.0) },
                )
                Text(
                    "Height slice retains observed gates within ±250 m; it does not interpolate a CAPPI.",
                    fontSize = 11.sp,
                )
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(d.rings, { d = d.copy(rings = it) })
                    Text("Range rings")
                }
                Text("Advanced display cleanup", fontWeight = FontWeight.SemiBold)
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(
                        f.texture_cleanup_enabled,
                        { f = f.copy(texture_cleanup_enabled = it) },
                    )
                    Text("Isolated texture")
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(f.companion_qc_enabled, { f = f.copy(companion_qc_enabled = it) })
                    Text("Companion moment evidence")
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(f.static_clutter_enabled, { f = f.copy(static_clutter_enabled = it) })
                    Text("Static clutter evidence")
                }
                Text(
                    "These optional masks alter the view only. Compare against the decoded baseline. Learned models remain disabled.",
                    fontSize = 11.sp,
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = {
                    onFilters(f)
                    onDisplay(d)
                    onClose()
                }
            ) {
                Text("Apply")
            }
        },
        dismissButton = { TextButton(onClick = onClose) { Text("Cancel") } },
    )
}

@Composable
private fun NumericPair(
    a: String,
    av: Double?,
    b: String,
    bv: Double?,
    onA: (Double?) -> Unit,
    onB: (Double?) -> Unit,
) {
    var x by remember { mutableStateOf(av?.toString() ?: "") }
    var y by remember { mutableStateOf(bv?.toString() ?: "") }
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        OutlinedTextField(
            x,
            {
                x = it
                onA(it.toDoubleOrNull()?.takeIf { v -> v.isFinite() })
            },
            label = { Text(a, fontSize = 11.sp) },
            singleLine = true,
            modifier = Modifier.weight(1f),
        )
        OutlinedTextField(
            y,
            {
                y = it
                onB(it.toDoubleOrNull()?.takeIf { v -> v.isFinite() })
            },
            label = { Text(b, fontSize = 11.sp) },
            singleLine = true,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
internal fun ExportDialog(
    panel: Panel,
    onClose: () -> Unit,
    onPNG: () -> Unit,
    onSource: () -> Unit,
    onMetadata: () -> Unit,
    onVideo: (List<String>) -> Unit,
) {
    val all =
        panel.volumes
            .filter { it.pulse == panel.spec.selection.pulse }
            .map { it.time }
            .distinct()
            .sorted()
    var start by remember { mutableStateOf(panel.spec.selection.time) }
    var end by remember {
        mutableStateOf(
            all.getOrElse((all.indexOf(start) + 11).coerceAtLeast(0)) { all.lastOrNull() ?: start }
        )
    }
    val selected = all.filter { it >= start && it <= end }
    AlertDialog(
        onDismissRequest = onClose,
        title = { Text("Export & provenance") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onPNG, modifier = Modifier.fillMaxWidth()) {
                    Text("Share current map PNG")
                }
                OutlinedButton(onClick = onSource, modifier = Modifier.fillMaxWidth()) {
                    Text("Share original HDF5")
                }
                OutlinedButton(onClick = onMetadata, modifier = Modifier.fillMaxWidth()) {
                    Text("Share metadata / citation")
                }
                HorizontalDivider()
                Text("MP4 animation · 5 frames/s")
                Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                    DropChoice("From UTC", start, all, { start = it }, Modifier.weight(1f))
                    DropChoice("To UTC", end, all, { end = it }, Modifier.weight(1f))
                }
                Text(
                    "${selected.size} frames · ${"%.1f".format(selected.size/5.0)} seconds",
                    fontSize = 12.sp,
                )
                TextButton(
                    onClick = {
                        start = all.firstOrNull() ?: start
                        end = all.lastOrNull() ?: end
                    }
                ) {
                    Text("Use full published day")
                }
                Button(
                    onClick = { onVideo(selected) },
                    enabled = selected.isNotEmpty(),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Create / resume MP4")
                }
                Text(
                    "Exports include source hashes, UTC times and display settings. MP4 uses a fixed map grid; unavailable frames are listed in its manifest.",
                    fontSize = 11.sp,
                )
            }
        },
        confirmButton = { TextButton(onClick = onClose) { Text("Close") } },
    )
}
