package com.rrniii.ukwsrvisualizer

import kotlinx.serialization.*
import kotlinx.serialization.json.*

data class RestoredProject(val panels: List<PanelSpec>, val links: Links)

object ProjectCodec {
    private fun JsonObject.text(key: String, default: String = "") =
        get(key)?.jsonPrimitive?.contentOrNull?.takeIf { it.isNotBlank() } ?: default

    private fun JsonObject.number(key: String) =
        get(key)?.jsonPrimitive?.contentOrNull?.toDoubleOrNull()?.takeIf { it.isFinite() }

    private fun JsonObject.flag(key: String, default: Boolean) =
        get(key)?.jsonPrimitive?.contentOrNull?.toBooleanStrictOrNull() ?: default

    private fun normalizeFilters(value: JsonObject): Filters {
        val clean = buildJsonObject {
            value.forEach { (key, v) ->
                val raw = (v as? JsonPrimitive)?.contentOrNull ?: return@forEach
                if (raw.isBlank()) return@forEach
                when {
                    key.endsWith("_enabled") -> raw.toBooleanStrictOrNull()?.let { put(key, it) }
                    key == "noise_floor_window_bins" ->
                        raw.toDoubleOrNull()?.toInt()?.let { put(key, it) }
                    key in
                        setOf("qc_runtime_mode", "noise_floor_method", "noise_floor_operation") ->
                        put(key, raw)
                    else -> raw.toDoubleOrNull()?.takeIf { it.isFinite() }?.let { put(key, it) }
                }
            }
        }
        // An omitted desktop noise switch means off, not the new-app default.
        return json
            .decodeFromJsonElement<Filters>(clean)
            .copy(
                noise_floor_enabled = value.flag("noise_floor_enabled", false),
                qc_runtime_mode = "safe",
                background_model_enabled = false,
            )
    }

    fun decode(text: String): RestoredProject {
        require(text.length <= 2 * 1024 * 1024) { "Project is too large" }
        val top = json.parseToJsonElement(text).jsonObject
        val session = top["session"]?.jsonObject ?: top
        if (top.containsKey("type"))
            require(
                top.text("type") == "uk-wsr-visualizer-project" &&
                    (top.number("version") ?: 1.0) == 1.0
            ) {
                "Unsupported project format"
            }
        val state = session["state"]?.jsonObject ?: error("Project has no state")
        val sourceEra = state.text("data_era", DataEra.DUAL.name)
        require(sourceEra in DataEra.entries.map { it.name }) { "Unknown source archive" }
        val base =
            Selection(
                era = sourceEra,
                radar = state.text("radar"),
                date = state.text("start").replace("-", ""),
                pulse = state.text("pulse", "lp"),
                time = state.text("time"),
                quantity = state.text("quantity"),
                dataset = state.text("dataset").removePrefix("dataset"),
            )
        val filters = normalizeFilters(state["filters"]?.jsonObject ?: buildJsonObject {})
        val range = state["displayRange"]?.jsonObject ?: buildJsonObject {}
        val display =
            Display(
                palette = state.text("palette", "auto"),
                opacity = (state.number("opacity") ?: 0.88).toFloat().coerceIn(0f, 1f),
                min = range.number("min"),
                max = range.number("max"),
                basemap = if (state.text("basemap") in setOf("grid", "dark")) "grid" else "osm",
            )
        val count = (state.number("panelCount") ?: 1.0).toInt()
        require(count == 1 || count == 4) { "Unsupported project panel count" }
        val native = state["android_panels"]
        val panels =
            if (native != null) json.decodeFromJsonElement<List<PanelSpec>>(native)
            else {
                val selections = state["panelSelections"]?.jsonArray.orEmpty()
                val displays = state["panelDisplays"]?.jsonArray.orEmpty()
                List(count) { index ->
                    val p = selections.getOrNull(index)?.jsonObject ?: buildJsonObject {}
                    val item = p.text("itemKey").split(':')
                    val radar =
                        p.text("radar", item.getOrNull(0)?.takeIf { it.isNotBlank() } ?: base.radar)
                    val date =
                        p.text(
                                "date",
                                item.getOrNull(1)?.takeIf { it.matches(Regex("[0-9]{8}")) }
                                    ?: base.date,
                            )
                            .replace("-", "")
                    val pd = displays.getOrNull(index)?.jsonObject ?: buildJsonObject {}
                    val selected =
                        base.copy(
                            radar = radar,
                            date = date,
                            pulse = p.text("pulse", base.pulse),
                            time = p.text("time", base.time),
                            quantity = p.text("quantity", base.quantity),
                            dataset = p.text("dataset", base.dataset).removePrefix("dataset"),
                        )
                    PanelSpec(
                        selected,
                        filters,
                        display.copy(
                            palette = pd.text("palette", display.palette),
                            min = pd.number("displayMin") ?: display.min,
                            max = pd.number("displayMax") ?: display.max,
                        ),
                    )
                }
            }
        require(panels.size in setOf(1, 4)) { "Invalid project panel count" }
        panels.forEach {
            require(
                it.selection.date.matches(Regex("[0-9]{8}")) &&
                    it.selection.radar.matches(Regex("[a-zA-Z0-9_-]+"))
            ) {
                "Invalid project radar/date"
            }
        }
        val link = state["comparisonLinks"]?.jsonObject ?: buildJsonObject {}
        return RestoredProject(
            panels.map {
                it.copy(
                    filters =
                        it.filters.copy(qc_runtime_mode = "safe", background_model_enabled = false)
                )
            },
            Links(
                view = link.flag("view", true),
                time = link.flag("time", true),
                variable = link.flag("variable", false),
                elevation = link.flag("elevation", false),
            ),
        )
    }
}
