package com.rrniii.ukwsrvisualizer

import kotlin.math.*

/**
 * Preservation-first mobile baseline, ported from the pinned native iOS implementation. Missing
 * companions never imply noise. Experimental learned models are not activated.
 */
object RadarProcessing {
    fun percentile(values: List<Double>, percent: Double): Double {
        if (values.isEmpty()) return Double.NaN
        val s = values.sorted()
        val p = percent.coerceIn(0.0, 100.0) / 100 * (s.size - 1)
        val i = floor(p).toInt()
        val j = min(i + 1, s.lastIndex)
        return s[i] + (s[j] - s[i]) * (p - i)
    }

    fun apply(
        field: NativeField,
        companions: Map<String, FloatArray>,
        settings: Filters,
    ): FloatArray {
        val out = field.values.copyOf()
        val rows = field.rows
        val cols = field.columns
        fun spatial(i: Int): Boolean {
            val r = i / cols
            val c = i % cols
            val range = Geometry.rangeM(field, c) / 1000
            val az = Geometry.azimuthAt(field, r)
            if (
                settings.min_range_km?.let { range < it } == true ||
                    settings.max_range_km?.let { range > it } == true
            )
                return false
            val lo = settings.min_azimuth_deg
            val hi = settings.max_azimuth_deg
            if ((lo != null || hi != null) && abs((hi ?: 360.0) - (lo ?: 0.0)) < 360) {
                val a = Geometry.wrap(lo ?: 0.0)
                val b = Geometry.wrap(hi ?: 360.0)
                if (if (a <= b) az < a || az > b else az < a && az > b) return false
            }
            if (
                settings.cappi_height_m?.let {
                    abs(Geometry.beamHeight(field, range * 1000) - it) > 250
                } == true
            )
                return false
            return true
        }
        val spatial = BooleanArray(out.size) { spatial(it) }
        for (i in out.indices) if (
            !spatial[i] ||
                settings.min_value?.let { out[i] < it } == true ||
                settings.max_value?.let { out[i] > it } == true
        )
            out[i] = Float.NaN
        if (!settings.noise_floor_enabled) return out
        val reflectivity =
            if (field.quantity in setOf("DBZH", "DBZ", "TH", "DBZV", "TV")) field.values
            else companions["DBZH"] ?: return out
        val gate =
            FloatArray(reflectivity.size) { if (spatial[it]) reflectivity[it] else Float.NaN }
        val comp = companions.mapValues { (_, v) ->
            FloatArray(v.size) { if (spatial[it]) v[it] else Float.NaN }
        }
        val finite = gate.filter { it.isFinite() }
        if (finite.isEmpty()) return out
        val global = finite.min()
        val profile =
            DoubleArray(cols) { c ->
                var values =
                    (0 until rows).mapNotNull { r ->
                        gate[r * cols + c].takeIf { it.isFinite() }?.toDouble()
                    }
                val above = values.filter { it > global + 1e-3 }
                if (above.size >= max(3, values.size / 20)) values = above
                percentile(values, settings.noise_floor_percentile)
            }
        val window =
            settings.noise_floor_window_bins.coerceAtLeast(1).let {
                if (it % 2 == 0) it + 1 else it
            }
        val smooth =
            DoubleArray(cols) { c ->
                percentile(
                    (max(0, c - window / 2)..min(cols - 1, c + window / 2))
                        .map { profile[it] }
                        .filter { it.isFinite() },
                    50.0,
                )
            }
        // Same nearest finite fill used for edge/missing profile bins on mobile.
        val known = smooth.indices.filter { smooth[it].isFinite() }
        if (known.isEmpty()) return out
        for (c in smooth.indices) if (!smooth[c].isFinite()) {
            val before = known.lastOrNull { it < c }
            val after = known.firstOrNull { it > c }
            smooth[c] =
                when {
                    before == null -> smooth[after!!]
                    after == null -> smooth[before]
                    else ->
                        smooth[before] +
                            (smooth[after] - smooth[before]) * (c - before).toDouble() /
                                (after - before)
                }
        }
        fun value(name: String, i: Int) =
            comp[name]?.getOrNull(i)?.takeIf { it.isFinite() }?.toDouble()
        fun texture(values: FloatArray?, r: Int, c: Int, angular: Boolean = false): Double? {
            values ?: return null
            val center = values[r * cols + c]
            if (!center.isFinite()) return null
            val neighbours =
                listOf(
                    ((r + rows - 1) % rows) * cols + c,
                    ((r + 1) % rows) * cols + c,
                    r * cols + max(0, c - 1),
                    r * cols + min(cols - 1, c + 1),
                )
            val diffs =
                neighbours
                    .filter { it != r * cols + c }
                    .mapNotNull { i ->
                        values[i]
                            .takeIf { it.isFinite() }
                            ?.let { v ->
                                val d = abs(v - center).toDouble()
                                if (angular) min(d % 360, 360 - d % 360) else d
                            }
                    }
            return if (diffs.size < 2) null else percentile(diffs, 75.0)
        }
        for (r in 0 until rows) for (c in 0 until cols) {
            val i = r * cols + c
            if (!out[i].isFinite() || !gate[i].isFinite()) continue
            val threshold = smooth[c] + settings.noise_floor_margin_db
            var remove = false
            if (
                settings.receiver_noise_enabled &&
                    gate[i] <= threshold + 0.25 &&
                    (value("CI", i)?.let { it >= 6 } == true) &&
                    (value("SQIH", i)?.let { it <= 0.05 } == true)
            ) {
                var bad = 0
                if (texture(comp["PHIDP"] ?: comp["UPHIDP"], r, c, true)?.let { it >= 60 } == true)
                    bad++
                if (texture(comp["VRADH"], r, c)?.let { it >= 9 } == true) bad++
                if (value("RHOHV", i)?.let { it <= 0.2 } == true) bad++
                if (value("ZDR", i)?.let { it <= -3 || it >= 8 } == true) bad++
                remove = bad >= 3
            }
            if (settings.static_clutter_enabled) {
                var supported = 0
                for (dr in -1..1) for (dc in -1..1) if (c + dc in 0 until cols) {
                    val n = ((r + dr + rows) % rows) * cols + c + dc
                    if (
                        gate[n].isFinite() &&
                            gate[n] >= 5 &&
                            value("CI", n)?.let { it <= 2 } == true &&
                            value("VRADH", n)?.let { abs(it) <= 1 } == true
                    )
                        supported++
                }
                remove = remove || supported >= 3
            }
            var score = 0
            if (settings.texture_cleanup_enabled) {
                val tex = texture(gate, r, c)
                var similar = 0
                for (n in
                    listOf(
                        ((r + rows - 1) % rows) * cols + c,
                        ((r + 1) % rows) * cols + c,
                        r * cols + max(0, c - 1),
                        r * cols + min(cols - 1, c + 1),
                    )) if (n != i && gate[n].isFinite() && abs(gate[n] - gate[i]) <= 6) similar++
                if (tex != null && similar <= 1) {
                    if (tex >= 10 && gate[i] <= min(threshold + 14, 30.0)) remove = true
                    if (tex >= 18) score++
                }
            }
            if (settings.companion_qc_enabled) {
                value("SQIH", i)?.let {
                    score += if (it < 0.2) 3 else if (it < 0.45) 2 else if (it < 0.65) 1 else 0
                }
                if (value("ZDR", i)?.let { it < -3 || it > 8 } == true) score++
                texture(comp["PHIDP"] ?: comp["UPHIDP"], r, c, true)?.let {
                    score += if (it > 60) 2 else if (it > 30) 1 else 0
                }
                texture(comp["VRADH"], r, c)?.let {
                    score += if (it > 18) 2 else if (it > 9) 1 else 0
                }
                if (value("WRADH", i)?.let { it > 8 } == true) score++
                if ((gate[i] <= threshold + 6 && score >= 3) || score >= 4) remove = true
            }
            if (remove) out[i] = Float.NaN
        }
        return out
    }
}
