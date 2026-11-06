package com.rrniii.ukwsrvisualizer

import kotlin.math.*
import kotlinx.serialization.*
import kotlinx.serialization.json.*

val json = Json {
    ignoreUnknownKeys = true
    encodeDefaults = true
    prettyPrint = true
    allowSpecialFloatingPointValues = false
}
const val PUBLIC_BASE = "https://ncas-radar-o.s3-ext.jc.rl.ac.uk/uk-wsr-visualizer-public/"

enum class DataEra(val label: String, val prefix: String) {
    DUAL("Dual polarisation", "ukmo-nimrod"),
    EARLY("Earlier archive", "ukmo-nimrod-pre-dual-pol");

    val catalogUrl
        get() = "$PUBLIC_BASE$prefix/catalog/pvol/catalog.json"
}

@Serializable
data class Spatial(
    val latitude: Double? = null,
    val longitude: Double? = null,
    val height_m: Double? = null,
)

@Serializable
data class Radar(
    val radar: String,
    val years: List<String> = emptyList(),
    val first_date: String = "",
    val last_date: String = "",
    val coverage_keys: List<String> = emptyList(),
    val spatial: Spatial? = null,
)

@Serializable
data class RootCatalog(val generated_at: String = "", val radars: List<Radar> = emptyList())

@Serializable
data class Day(
    val date: String,
    val catalog_key: String,
    val file_count: Int = 0,
    val pulse_counts: Map<String, Int> = emptyMap(),
)

@Serializable data class Coverage(val days: List<Day> = emptyList())

@Serializable
data class Volume(
    val pulse: String = "",
    val time: String = "",
    val filename: String = "",
    val object_url: String = "",
    val object_key: String = "",
    val size_bytes: Long = 0,
)

@Serializable
data class DayCatalog(
    val date: String = "",
    val radar: String = "",
    val files: List<Volume> = emptyList(),
)

@Serializable
data class Selection(
    val era: String = DataEra.DUAL.name,
    val radar: String = "",
    val date: String = "",
    val pulse: String = "lp",
    val time: String = "",
    val quantity: String = "",
    val dataset: String = "",
) {
    val label
        get() = "$radar · $date ${time.take(2)}:${time.drop(2)} UTC · ${pulse.uppercase()}"
}

@Serializable
data class Filters(
    val min_range_km: Double? = null,
    val max_range_km: Double? = null,
    val min_azimuth_deg: Double? = null,
    val max_azimuth_deg: Double? = null,
    val min_value: Double? = null,
    val max_value: Double? = null,
    val cappi_height_m: Double? = null,
    val noise_floor_enabled: Boolean = true,
    val noise_floor_margin_db: Double = 0.0,
    val noise_floor_percentile: Double = 10.0,
    val noise_floor_window_bins: Int = 11,
    val texture_cleanup_enabled: Boolean = false,
    val companion_qc_enabled: Boolean = false,
    val static_clutter_enabled: Boolean = false,
    val receiver_noise_enabled: Boolean = true,
    val qc_runtime_mode: String = "safe",
    val background_model_enabled: Boolean = false,
)

@Serializable
data class Display(
    val palette: String = "auto",
    val min: Double? = null,
    val max: Double? = null,
    val opacity: Float = 0.88f,
    val basemap: String = "osm",
    val rings: Boolean = true,
)

@Serializable
data class Links(
    val view: Boolean = true,
    val time: Boolean = true,
    val variable: Boolean = false,
    val elevation: Boolean = false,
)

@Serializable
data class PanelSpec(
    val selection: Selection = Selection(),
    val filters: Filters = Filters(),
    val display: Display = Display(),
)

@Serializable
data class Project(
    val type: String = "uk-wsr-visualizer-project",
    val version: Int = 1,
    val exported_at: String = "",
    val application: String = "uk-wsr-visualizer",
    val session: JsonObject,
)

data class LoadedField(
    val spec: PanelSpec,
    val volume: Volume,
    val field: NativeField,
    val companions: Map<String, FloatArray>,
    val sourceHash: String,
    val sourceBytes: Long,
    val values: FloatArray,
    val maskedCount: Int,
)

data class Panel(
    val spec: PanelSpec = PanelSpec(),
    val data: LoadedField? = null,
    val fields: List<FieldRecord> = emptyList(),
    val volumes: List<Volume> = emptyList(),
    val busy: Boolean = false,
    val error: String? = null,
)

data class UiState(
    val root: RootCatalog? = null,
    val era: DataEra = DataEra.DUAL,
    val catalogueStatus: String = "Loading public catalogue…",
    val panels: List<Panel> = List(4) { Panel() },
    val active: Int = 0,
    val mode: String = "View",
    val links: Links = Links(),
    val recent: List<Selection> = emptyList(),
    val projects: List<String> = emptyList(),
    val message: String? = null,
    val exportProgress: String? = null,
    val playing: Boolean = false,
)

object Geometry {
    fun wrap(angle: Double) = ((angle % 360) + 360) % 360

    fun azimuthAt(field: NativeField, row: Int): Double =
        wrap(
            field.startAzimuths[row] + wrap(field.stopAzimuths[row] - field.startAzimuths[row]) / 2
        )

    fun rayAt(field: NativeField, azimuth: Double): Int {
        val a = wrap(azimuth)
        for (r in 0 until field.rows) {
            val measuredWidth = wrap(field.stopAzimuths[r] - field.startAzimuths[r])
            // AVERAGE scans encode a measured centre in both attributes.
            val width = if (measuredWidth < 1e-8) field.beamWidthDeg else measuredWidth
            val start =
                if (measuredWidth < 1e-8) field.startAzimuths[r] - width / 2
                else field.startAzimuths[r]
            if (width > 0 && width <= 180 && wrap(a - start) < width) return r
        }
        return -1
    }

    fun rangeM(field: NativeField, col: Int) = field.rstartKm * 1000 + (col + 0.5) * field.rscaleM

    fun beamHeight(field: NativeField, range: Double): Double {
        val re = 6371000.0 * 4 / 3
        return sqrt(
            range * range + re * re + 2 * range * re * sin(Math.toRadians(field.elevationDeg))
        ) - re + (field.heightM.takeIf { it.isFinite() } ?: 0.0)
    }

    fun distanceKm(lat1: Double, lon1: Double, lat2: Double, lon2: Double): Double {
        val dlat = Math.toRadians(lat2 - lat1)
        val dlon = Math.toRadians(lon2 - lon1)
        val h =
            sin(dlat / 2).pow(2) +
                cos(Math.toRadians(lat1)) * cos(Math.toRadians(lat2)) * sin(dlon / 2).pow(2)
        return 6371 * 2 * asin(sqrt(h.coerceIn(0.0, 1.0)))
    }

    fun nearest(radars: List<Radar>, lat: Double, lon: Double): Radar? =
        radars
            .filter { it.spatial?.latitude != null && it.spatial.longitude != null }
            .minByOrNull { distanceKm(lat, lon, it.spatial!!.latitude!!, it.spatial.longitude!!) }
}
