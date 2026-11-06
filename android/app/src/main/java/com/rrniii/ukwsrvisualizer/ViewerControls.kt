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
internal fun Controls(
    model: VisualizerViewModel,
    state: UiState,
    onCatalogue: () -> Unit,
    onRecent: () -> Unit,
    onAdvanced: () -> Unit,
    onExport: () -> Unit,
    onNearest: () -> Unit,
) {
    val p = state.panels[state.active]
    Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Button(onClick = onCatalogue, modifier = Modifier.weight(1f)) {
                Text("Find radar data")
            }
            OutlinedButton(onClick = onRecent) { Text("Recent") }
        }
        TextButton(onClick = onNearest, contentPadding = PaddingValues(0.dp)) {
            Text("Nearest radar · latest available")
        }
        if (state.mode == "Compare") {
            Text("Panel ${'A'+state.active}", fontWeight = FontWeight.SemiBold)
            Row(Modifier.horizontalScroll(rememberScrollState())) {
                FilterChip(
                    state.links.time,
                    { model.links(state.links.copy(time = !state.links.time)) },
                    { Text("Link time") },
                )
                Spacer(Modifier.width(5.dp))
                FilterChip(
                    state.links.view,
                    { model.links(state.links.copy(view = !state.links.view)) },
                    { Text("Link map") },
                )
                Spacer(Modifier.width(5.dp))
                FilterChip(
                    state.links.variable,
                    { model.links(state.links.copy(variable = !state.links.variable)) },
                    { Text("Link field") },
                )
                Spacer(Modifier.width(5.dp))
                FilterChip(
                    state.links.elevation,
                    { model.links(state.links.copy(elevation = !state.links.elevation)) },
                    { Text("Link sweep") },
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            DropChoice(
                "Pulse",
                p.spec.selection.pulse.uppercase(),
                p.volumes.map { it.pulse }.distinct(),
                { model.choosePulse(it) },
                Modifier.weight(0.35f),
            )
            DropChoice(
                "Time UTC",
                p.spec.selection.time.ifEmpty { "Select" },
                p.volumes
                    .filter { it.pulse == p.spec.selection.pulse }
                    .map { it.time }
                    .distinct()
                    .sorted(),
                model::chooseTime,
                Modifier.weight(0.65f),
            )
        }
        DropChoice(
            "Variable / elevation",
            p.fields
                .find {
                    it.quantity == p.spec.selection.quantity &&
                        it.dataset.removePrefix("dataset") == p.spec.selection.dataset
                }
                ?.label ?: "Auto after download",
            p.fields.map { it.label },
            { label -> p.fields.find { it.label == label }?.let(model::chooseField) },
            Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            OutlinedButton(
                onClick = { model.step(-1) },
                modifier = Modifier.weight(1f),
                enabled = p.volumes.isNotEmpty(),
            ) {
                Text("Previous")
            }
            Button(
                onClick = model::play,
                modifier = Modifier.weight(1f),
                enabled = p.volumes.isNotEmpty(),
            ) {
                Text(if (state.playing) "Pause" else "Play")
            }
            OutlinedButton(
                onClick = { model.step(1) },
                modifier = Modifier.weight(1f),
                enabled = p.volumes.isNotEmpty(),
            ) {
                Text("Next")
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Switch(
                p.spec.filters.noise_floor_enabled,
                { model.filters(p.spec.filters.copy(noise_floor_enabled = it)) },
            )
            Column(Modifier.padding(start = 8.dp)) {
                Text("Optional cleanup")
                Text(
                    if (p.spec.filters.noise_floor_enabled) "Preservation-first baseline"
                    else "Unmodified decoded values",
                    fontSize = 11.sp,
                )
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onAdvanced, modifier = Modifier.weight(1f)) {
                Text("Display & filters")
            }
            Button(onClick = onExport, enabled = p.data != null, modifier = Modifier.weight(1f)) {
                Text("Export")
            }
        }
        TextButton(onClick = model::clearCache, contentPadding = PaddingValues(0.dp)) {
            Text("Clear downloaded radar cache")
        }
        p.data?.let { data ->
            Text(
                "${data.field.rows} rays × ${data.field.columns} gates · ${data.maskedCount} display-masked\n${if(data.field.measuredAzimuths!=0)"Measured ray geometry" else "Regular ODIM ray geometry"} · raw source preserved",
                fontSize = 11.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
internal fun DropChoice(
    label: String,
    value: String,
    options: List<String>,
    choose: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var expanded by remember { mutableStateOf(false) }
    Box(modifier) {
        OutlinedButton(
            onClick = { expanded = true },
            modifier = Modifier.fillMaxWidth(),
            enabled = options.isNotEmpty(),
            contentPadding = PaddingValues(horizontal = 9.dp, vertical = 5.dp),
        ) {
            Column(Modifier.fillMaxWidth()) {
                Text(label, fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(value, maxLines = 1, fontSize = 13.sp)
            }
        }
        DropdownMenu(expanded, { expanded = false }, modifier = Modifier.heightIn(max = 360.dp)) {
            options.forEach { option ->
                DropdownMenuItem(
                    text = { Text(option) },
                    onClick = {
                        choose(option)
                        expanded = false
                    },
                )
            }
        }
    }
}
