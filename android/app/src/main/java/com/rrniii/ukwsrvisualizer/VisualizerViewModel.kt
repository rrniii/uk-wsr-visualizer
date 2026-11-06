package com.rrniii.ukwsrvisualizer

import android.app.Application
import androidx.datastore.preferences.core.*
import androidx.datastore.preferences.preferencesDataStore
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.io.File
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.*
import kotlinx.serialization.json.*

private val android.content.Context.preferences by preferencesDataStore(name = "uk-wsr-visualizer")

class VisualizerViewModel(app: Application) : AndroidViewModel(app) {
    val repository = CatalogRepository(app)
    private val mutable = MutableStateFlow(UiState())
    val state = mutable.asStateFlow()
    private val jobs = arrayOfNulls<Job>(4)
    private var playback: Job? = null
    private var exportJob: Job? = null
    private var generation = 0L
    private val processingGeneration = LongArray(4)
    private val renderedFrames = arrayOfNulls<LoadedField>(4)

    fun frameRendered(index: Int, data: LoadedField) {
        renderedFrames[index] = data
    }

    private val projectRoot = File(app.filesDir, "projects").apply { mkdirs() }

    init {
        viewModelScope.launch {
            val stored = app.preferences.data.first()
            val recent = runCatching {
                json.decodeFromString<List<Selection>>(
                    stored[stringPreferencesKey("recent")] ?: "[]"
                )
            }
                .getOrDefault(emptyList())
            mutable.update { it.copy(recent = recent, projects = projectNames()) }
            val last = recent.firstOrNull()
            refreshRoot(
                last?.era?.let { runCatching { DataEra.valueOf(it) }.getOrNull() } ?: DataEra.DUAL,
                default = last,
            )
        }
    }

    fun refresh(era: DataEra = state.value.era) = viewModelScope.launch { refreshRoot(era) }

    private suspend fun refreshRoot(era: DataEra, default: Selection? = null) {
        generation++
        val expected = generation
        jobs.forEach { it?.cancel() }
        stopPlayback()
        mutable.update {
            it.copy(
                era = era,
                root = null,
                catalogueStatus = "Loading public catalogue…",
                panels = List(4) { Panel() },
            )
        }
        try {
            val root = repository.root(era)
            if (expected != generation) return
            mutable.update {
                it.copy(
                    root = root,
                    catalogueStatus =
                        "${root.radars.size} radars · ${root.generated_at}" +
                            (if (repository.lastReadCached) " · saved catalogue (offline)" else ""),
                )
            }
            val radar =
                root.radars.find { it.radar == default?.radar }
                    ?: root.radars.maxByOrNull { it.last_date }
                    ?: error("Catalogue has no radar sites")
            load(
                0,
                default ?: Selection(era = era.name, radar = radar.radar, date = radar.last_date),
            )
        } catch (e: Exception) {
            if (e is CancellationException) throw e
            mutable.update { it.copy(catalogueStatus = e.message ?: "Catalogue failed") }
        }
    }

    fun nearest(lat: Double, lon: Double) {
        val radar = Geometry.nearest(state.value.root?.radars.orEmpty(), lat, lon) ?: return
        load(
            state.value.active,
            Selection(era = state.value.era.name, radar = radar.radar, date = radar.last_date),
        )
    }

    suspend fun days(radar: Radar, year: String) = repository.days(radar, year, state.value.era)

    fun mode(mode: String) {
        stopPlayback()
        mutable.update { it.copy(mode = mode) }
        if (mode == "Compare") {
            val base = state.value.panels[0]
            if (base.data != null)
                (1..3)
                    .filter { state.value.panels[it].data == null }
                    .forEach { index -> load(index, base.spec.selection) }
        }
    }

    fun active(index: Int) {
        mutable.update { it.copy(active = index.coerceIn(0, 3)) }
    }

    fun links(links: Links) {
        mutable.update { it.copy(links = links) }
    }

    fun dismissMessage() {
        mutable.update { it.copy(message = null) }
    }

    fun message(text: String) {
        mutable.update { it.copy(message = text) }
    }

    fun load(index: Int, selection: Selection) {
        jobs[index]?.cancel()
        renderedFrames[index] = null
        processingGeneration[index]++
        val gen = generation
        val original = state.value.panels[index]
        mutable.update {
            it.copy(
                panels =
                    it.panels.mapIndexed { i, p ->
                        if (i == index)
                            p.copy(
                                spec = p.spec.copy(selection = selection),
                                data = if (state.value.playing) p.data else null,
                                busy = true,
                                error = null,
                            )
                        else p
                    }
            )
        }
        jobs[index] = viewModelScope.launch {
            try {
                val day = repository.day(selection)
                ensureActive()
                mutable.update {
                    it.copy(
                        panels =
                            it.panels.mapIndexed { i, p ->
                                if (i == index) p.copy(volumes = day.files) else p
                            }
                    )
                }
                val pulse =
                    selection.pulse.ifEmpty {
                        day.files.firstOrNull()?.pulse ?: error("No scans in selected day")
                    }
                require(day.files.any { it.pulse == pulse }) {
                    "Requested pulse is unavailable; no substitute was loaded"
                }
                val volume =
                    if (selection.time.isEmpty())
                        day.files.filter { it.pulse == pulse }.maxByOrNull { it.time }
                    else
                        day.files.firstOrNull { it.pulse == pulse && it.time == selection.time }
                            ?: error("Requested time is unavailable")
                val selected = selection.copy(pulse = pulse, time = volume!!.time)
                val (data, fields) = repository.load(original.spec.copy(selection = selected))
                ensureActive()
                if (gen != generation) return@launch
                mutable.update {
                    it.copy(
                        panels =
                            it.panels.mapIndexed { i, p ->
                                if (i == index)
                                    Panel(data.spec, data, fields, day.files, false, null)
                                else p
                            }
                    )
                }
                remember(data.spec.selection)
                repository.prune(
                    state.value.panels
                        .mapNotNull { it.data?.volume?.let(repository::sourceFile)?.path }
                        .toSet()
                )
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                mutable.update {
                    it.copy(
                        panels =
                            it.panels.mapIndexed { i, p ->
                                if (i == index)
                                    p.copy(
                                        data = null,
                                        busy = false,
                                        error = e.message ?: "Source load failed",
                                    )
                                else p
                            }
                    )
                }
            }
        }
    }

    private suspend fun remember(selection: Selection) {
        mutable.update {
            it.copy(
                recent = (listOf(selection) + it.recent.filter { r -> r != selection }).take(20)
            )
        }
        getApplication<Application>().preferences.edit {
            it[stringPreferencesKey("recent")] = json.encodeToString(state.value.recent)
        }
    }

    fun step(delta: Int) {
        val s = state.value
        val panel = s.panels[s.active]
        val times =
            panel.volumes
                .filter { it.pulse == panel.spec.selection.pulse }
                .map { it.time }
                .distinct()
                .sorted()
        if (times.isEmpty()) return
        val current = times.indexOf(panel.spec.selection.time)
        val next = (current + delta).coerceIn(0, times.lastIndex)
        chooseTime(times[next])
    }

    fun chooseTime(time: String) {
        val s = state.value
        val indices = if (s.mode == "Compare" && s.links.time) (0..3).toList() else listOf(s.active)
        indices.forEach { i -> load(i, s.panels[i].spec.selection.copy(time = time)) }
    }

    fun choosePulse(pulse: String) {
        val s = state.value
        load(
            s.active,
            s.panels[s.active].spec.selection.copy(pulse = pulse, time = "", dataset = ""),
        )
    }

    fun chooseField(field: FieldRecord) {
        val s = state.value
        val selection = s.panels[s.active].spec.selection
        for (i in 0 until if (s.mode == "Compare") 4 else 1) {
            if (i != s.active && !s.links.variable && !s.links.elevation) continue
            val old = s.panels[i].spec.selection
            val q = if (i == s.active || s.links.variable) field.quantity else old.quantity
            val ds =
                if (i == s.active || s.links.elevation) field.dataset.removePrefix("dataset")
                else old.dataset
            load(i, old.copy(quantity = q, dataset = ds))
        }
    }

    fun filters(filters: Filters) {
        val index = state.value.active
        val processing = ++processingGeneration[index]
        val p = state.value.panels[index]
        val spec = p.spec.copy(filters = filters)
        val data = p.data
        if (data == null) {
            mutable.update {
                it.copy(
                    panels =
                        it.panels.mapIndexed { i, v -> if (i == index) v.copy(spec = spec) else v }
                )
            }
            return
        }
        // Enabling cleanup can require companions absent from a baseline load.
        if (filters.noise_floor_enabled && data.companions.isEmpty()) {
            mutable.update {
                it.copy(
                    panels =
                        it.panels.mapIndexed { i, v -> if (i == index) v.copy(spec = spec) else v }
                )
            }
            load(index, spec.selection)
            return
        }
        viewModelScope.launch {
            val result =
                withContext(Dispatchers.Default) {
                    val values = RadarProcessing.apply(data.field, data.companions, filters)
                    data.copy(
                        spec = spec,
                        values = values,
                        maskedCount =
                            data.field.values.indices.count {
                                data.field.values[it].isFinite() && !values[it].isFinite()
                            },
                    )
                }
            mutable.update {
                it.copy(
                    panels =
                        it.panels.mapIndexed { i, v ->
                            if (
                                i == index &&
                                    processingGeneration[index] == processing &&
                                    v.data?.volume == data.volume
                            )
                                v.copy(
                                    spec = spec.copy(display = v.spec.display),
                                    data = result.copy(spec = spec.copy(display = v.spec.display)),
                                )
                            else v
                        }
                )
            }
        }
    }

    fun display(display: Display) {
        val index = state.value.active
        mutable.update {
            it.copy(
                panels =
                    it.panels.mapIndexed { i, p ->
                        if (i == index) {
                            val spec = p.spec.copy(display = display)
                            p.copy(spec = spec, data = p.data?.copy(spec = spec))
                        } else p
                    }
            )
        }
    }

    fun play() {
        if (playback != null) {
            stopPlayback()
            return
        }
        mutable.update { it.copy(playing = true) }
        playback = viewModelScope.launch {
            try {
                while (isActive) {
                    val current = state.value
                    val panel = current.panels[current.active]
                    val times =
                        panel.volumes
                            .filter { it.pulse == panel.spec.selection.pulse }
                            .map { it.time }
                            .distinct()
                            .sorted()
                    if (times.isEmpty()) break
                    chooseTime(times[(times.indexOf(panel.spec.selection.time) + 1) % times.size])
                    jobs.filterNotNull().joinAll()
                    val indices =
                        if (current.mode == "Compare" && current.links.time) (0..3).toList()
                        else listOf(current.active)
                    val visible =
                        withTimeoutOrNull(20_000) {
                            while (
                                indices.any { index ->
                                    val data = state.value.panels[index].data
                                    data != null && renderedFrames[index] !== data
                                }
                            ) delay(30)
                            true
                        } ?: false
                    if (!visible) {
                        message("Playback paused because a frame did not finish rendering")
                        break
                    }
                    delay(500)
                }
            } finally {
                playback = null
                mutable.update { it.copy(playing = false) }
            }
        }
    }

    private fun stopPlayback() {
        playback?.cancel()
        playback = null
        mutable.update { it.copy(playing = false) }
    }

    fun clearCache() {
        stopPlayback()
        jobs.forEach { it?.cancel() }
        mutable.update {
            it.copy(panels = it.panels.map { p -> p.copy(data = null, busy = false, error = null) })
        }
        viewModelScope.launch {
            repository.clearRaw()
            message("Raw cache cleared. Select a scan to download it again.")
        }
    }

    private fun projectNames() =
        projectRoot
            .listFiles()
            ?.filter { it.extension == "json" }
            ?.map { it.nameWithoutExtension }
            ?.sorted()
            .orEmpty()

    fun projectText(title: String): String {
        val s = state.value
        val p = s.panels[s.active]
        require(p.data != null) { "Render a scan before saving a project" }
        val selection = p.spec.selection
        val now = Instant.now().toString()
        val state = buildJsonObject {
            put("radar", selection.radar)
            put("start", selection.date)
            put("end", selection.date)
            put("pulse", selection.pulse)
            put("time", selection.time)
            put("quantity", selection.quantity)
            put("dataset", selection.dataset)
            put("opacity", p.spec.display.opacity)
            put("palette", p.spec.display.palette)
            put("basemap", p.spec.display.basemap)
            put("filters", json.encodeToJsonElement(p.spec.filters))
            put(
                "displayRange",
                buildJsonObject {
                    p.spec.display.min?.let { put("min", it) }
                    p.spec.display.max?.let { put("max", it) }
                },
            )
            put("panelCount", if (s.mode == "Compare") 4 else 1)
            put("comparisonLinks", json.encodeToJsonElement(s.links))
            put(
                "panelSelections",
                buildJsonArray {
                    s.panels.take(if (s.mode == "Compare") 4 else 1).forEach { panel ->
                        val q = panel.spec.selection
                        add(
                            buildJsonObject {
                                put("itemKey", "${q.radar}:${q.date}")
                                put("radar", q.radar)
                                put("date", q.date)
                                put("pulse", q.pulse)
                                put("time", q.time)
                                put("quantity", q.quantity)
                                put("dataset", q.dataset)
                            }
                        )
                    }
                },
            )
            put(
                "android_panels",
                json.encodeToJsonElement(
                    s.panels.take(if (s.mode == "Compare") 4 else 1).map { it.spec }
                ),
            )
            put("data_era", selection.era)
        }
        return json.encodeToString(
            Project(
                exported_at = now,
                session =
                    buildJsonObject {
                        put("session_id", UUID.randomUUID().toString())
                        put("title", title)
                        put("version", 1)
                        put("created_at", now)
                        put("updated_at", now)
                        put("notes", JsonArray(emptyList()))
                        put("state", state)
                    },
            )
        )
    }

    fun saveProject(title: String): String {
        val safe = title.replace(Regex("[^a-zA-Z0-9 _-]"), "").trim().ifEmpty { "Radar project" }
        val text = projectText(safe)
        CatalogRepository.atomicWrite(File(projectRoot, "$safe.json"), text.toByteArray())
        mutable.update { it.copy(projects = projectNames(), message = "Saved $safe") }
        return text
    }

    fun openProject(name: String) = importProject(File(projectRoot, "$name.json").readText())

    fun importProject(text: String) {
        runCatching {
            val restored = ProjectCodec.decode(text)
            jobs.forEach { it?.cancel() }
            mutable.update {
                it.copy(
                    mode = if (restored.panels.size > 1) "Compare" else "View",
                    links = restored.links,
                    panels =
                        List(4) { i ->
                            Panel(spec = restored.panels.getOrElse(i) { restored.panels.first() })
                        },
                    active = 0,
                )
            }
            restored.panels.forEachIndexed { i, spec -> load(i, spec.selection) }
        }
            .onFailure { message("Project import failed: ${it.message}") }
    }

    fun export(data: LoadedField, times: List<String>, onDone: (List<File>) -> Unit) {
        exportJob?.cancel()
        stopPlayback()
        exportJob = viewModelScope.launch {
            try {
                mutable.update { it.copy(exportProgress = "Preparing MP4…") }
                val result =
                    ArtifactExporter(getApplication(), repository).video(data, times) { message ->
                        mutable.update { it.copy(exportProgress = message) }
                    }
                mutable.update { it.copy(exportProgress = null) }
                onDone(result)
            } catch (e: Exception) {
                mutable.update { it.copy(exportProgress = null) }
                if (e !is CancellationException) message("Export failed: ${e.message}")
            }
        }
    }

    fun cancelExport() {
        exportJob?.cancel()
        mutable.update {
            it.copy(
                exportProgress = null,
                message = "Export cancelled; no incomplete video was published",
            )
        }
    }
}
