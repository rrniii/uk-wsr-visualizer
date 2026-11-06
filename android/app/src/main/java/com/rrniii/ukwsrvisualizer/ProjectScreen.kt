package com.rrniii.ukwsrvisualizer

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.io.File
import kotlinx.coroutines.*

@Composable
internal fun ProjectScreen(model: VisualizerViewModel, state: UiState) {
    val context = LocalContext.current
    var title by remember { mutableStateOf("Radar project") }
    val import =
        rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
            if (uri != null)
                runCatching {
                    context.contentResolver.openInputStream(uri)!!.use {
                        val collected = java.io.ByteArrayOutputStream()
                        val buffer = ByteArray(8192)
                        while (true) {
                            val count = it.read(buffer)
                            if (count < 0) break
                            require(collected.size() + count <= 2 * 1024 * 1024) {
                                "Project is too large"
                            }
                            collected.write(buffer, 0, count)
                        }
                        val bytes = collected.toByteArray()
                        require(bytes.size <= 2 * 1024 * 1024) { "Project is too large" }
                        model.importProject(bytes.toString(Charsets.UTF_8))
                    }
                }
                    .onFailure { model.message(it.message ?: "Could not open project") }
        }
    Column(
        Modifier.fillMaxSize().padding(20.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Projects", fontSize = 24.sp, fontWeight = FontWeight.SemiBold)
        Text(
            "Save selections and display settings. Portable JSON projects can be shared with the other UK WSR apps."
        )
        OutlinedTextField(
            title,
            { title = it },
            label = { Text("Project title") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(
                onClick = {
                    runCatching { model.saveProject(title) }
                        .onFailure { model.message(it.message ?: "Could not save") }
                }
            ) {
                Text("Save current")
            }
            OutlinedButton(
                onClick = {
                    import.launch(
                        arrayOf("application/json", "text/plain", "application/octet-stream")
                    )
                }
            ) {
                Text("Import")
            }
            OutlinedButton(
                onClick = {
                    runCatching {
                        val text = model.projectText(title)
                        val file =
                            File(
                                context.filesDir,
                                "exports/project-${System.currentTimeMillis()}.json",
                            )
                        CatalogRepository.atomicWrite(file, text.toByteArray())
                        ArtifactExporter.share(context, listOf(file))
                    }
                        .onFailure { model.message(it.message ?: "Could not share") }
                }
            ) {
                Text("Share")
            }
        }
        HorizontalDivider()
        LazyColumn {
            items(state.projects) { name ->
                ListItem(
                    headlineContent = { Text(name) },
                    supportingContent = { Text("Restore catalogue selections and filters") },
                    modifier = Modifier.clickable { model.openProject(name) },
                )
            }
        }
    }
}
