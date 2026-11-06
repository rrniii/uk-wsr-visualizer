package com.rrniii.ukwsrvisualizer

import kotlinx.serialization.*
import org.junit.Assert.*
import org.junit.Test

class ScientificContractsTest {
    private fun field(values: FloatArray, rows: Int = 4, cols: Int = 3) =
        NativeField().apply {
            this.values = values
            this.rows = rows
            columns = cols
            sourceStates = ByteArray(values.size)
            startAzimuths = DoubleArray(rows) { it * 360.0 / rows }
            stopAzimuths = DoubleArray(rows) { (it + 1) * 360.0 / rows }
            quantity = "DBZH"
            latitude = 54.5
            longitude = -6.3
            rscaleM = 1000.0
            rstartKm = 0.0
            elevationDeg = 0.5
            heightM = 41.0
        }

    @Test
    fun irregularRayGapsRemainMissing() {
        val f = field(FloatArray(12) { 1f })
        f.startAzimuths = doubleArrayOf(10.0, 90.0, 190.0, 355.0)
        f.stopAzimuths = doubleArrayOf(11.0, 91.0, 191.0, 5.0)
        assertEquals(0, Geometry.rayAt(f, 10.5))
        assertEquals(-1, Geometry.rayAt(f, 12.0))
        assertEquals(3, Geometry.rayAt(f, 359.0))
        assertEquals(3, Geometry.rayAt(f, 1.0))
        assertEquals(-1, Geometry.rayAt(f, 5.0))
    }

    @Test
    fun sourceStatesAndValuesAreNotOverwritten() {
        val input = FloatArray(12) { it.toFloat() }
        input[0] = Float.NaN
        input[1] = Float.NaN
        val f = field(input)
        f.sourceStates[0] = 1
        f.sourceStates[1] = 2
        val result =
            RadarProcessing.apply(
                f,
                emptyMap(),
                Filters(min_value = 4.0, noise_floor_enabled = false),
            )
        assertTrue(result[2].isNaN())
        assertEquals(2f, f.values[2])
        assertEquals(1, f.sourceStates[0].toInt())
        assertEquals(2, f.sourceStates[1].toInt())
    }

    @Test
    fun missingEvidenceNeverBecomesReceiverNoise() {
        val f = field(FloatArray(12) { -20f })
        val result = RadarProcessing.apply(f, emptyMap(), Filters())
        assertArrayEquals(f.values, result, 0f)
    }

    @Test
    fun supportedReceiverNoiseRequiresMultipleMoments() {
        val f = field(FloatArray(12) { if (it < 9) -20f else 10f })
        val comp =
            mapOf(
                "CI" to FloatArray(12) { 10f },
                "SQIH" to FloatArray(12) { 0.01f },
                "RHOHV" to FloatArray(12) { 0.1f },
                "ZDR" to FloatArray(12) { 9f },
                "VRADH" to FloatArray(12) { if (it / 3 % 2 == 0) -20f else 20f },
            )
        val result = RadarProcessing.apply(f, comp, Filters())
        assertEquals(9, result.count { it.isNaN() })
        assertTrue(result.takeLast(3).all { it == 10f })
        assertTrue(f.values.all { it.isFinite() })
        val missing = RadarProcessing.apply(f, comp - "VRADH", Filters())
        assertTrue(missing.all { it.isFinite() })
    }

    @Test
    fun selectedAliasMomentsAndRowScalarsMatchMobileCleanup() {
        val reflectivity = FloatArray(12) { if (it < 9) -20f else 10f }
        val velocity = FloatArray(12) { if (it / 3 % 2 == 0) -20f else 20f }
        val companions =
            mapOf(
                "DBZH" to reflectivity,
                "CI" to FloatArray(12) { 10f },
                "SQIH" to FloatArray(12) { 0.01f },
                "RHOHV" to FloatArray(12) { 0.1f },
                "ZDR" to FloatArray(12) { 9f },
                "VRADH" to velocity,
            )
        val expected = RadarProcessing.apply(field(reflectivity), companions, Filters())
        val alias = field(reflectivity).apply { quantity = "DBZHC" }
        assertArrayEquals(
            expected,
            RadarProcessing.apply(alias, companions - "DBZH", Filters()),
            0f,
        )
        val selectedVelocity = field(velocity).apply { quantity = "VRADDH" }
        val actual = RadarProcessing.apply(selectedVelocity, companions - "VRADH", Filters())
        assertEquals(expected.map { it.isNaN() }, actual.map { it.isNaN() })
        val scalar = field(floatArrayOf(1f, 2f, Float.NaN, 4f), cols = 1)
        val expanded = MomentNames.companionValues(scalar, selectedVelocity)!!
        assertArrayEquals(
            floatArrayOf(1f, 1f, 1f, 2f, 2f, 2f, Float.NaN, Float.NaN, Float.NaN, 4f, 4f, 4f),
            expanded,
            0f,
        )
        assertEquals(4, scalar.values.size)
    }

    @Test
    fun azimuthFilterUsesMeasuredAngles() {
        val f = field(FloatArray(12) { 10f })
        f.startAzimuths = doubleArrayOf(190.0, 10.0, 90.0, 350.0)
        f.stopAzimuths = doubleArrayOf(191.0, 11.0, 91.0, 351.0)
        val result =
            RadarProcessing.apply(
                f,
                emptyMap(),
                Filters(min_azimuth_deg = 9.0, max_azimuth_deg = 12.0, noise_floor_enabled = false),
            )
        assertEquals(3, result.count { it.isFinite() })
        assertTrue(result.slice(3..5).all { it == 10f })
    }

    @Test
    fun nearestRadarUsesPublishedCoordinates() {
        val list =
            listOf(
                Radar("far", spatial = Spatial(51.0, 0.0)),
                Radar("near", spatial = Spatial(54.5, -6.3)),
                Radar("unknown"),
            )
        assertEquals("near", Geometry.nearest(list, 54.51, -6.31)?.radar)
    }

    @Test
    fun catalogAndProjectIgnoreForwardCompatibleFields() {
        val root =
            json.decodeFromString<RootCatalog>(
                """{"radars":[{"radar":"site","years":["2026"],"new_field":true}],"unknown":1}"""
            )
        assertEquals("site", root.radars.single().radar)
        val spec =
            PanelSpec(
                Selection(radar = "site", date = "20261104", time = "0000"),
                Filters(noise_floor_enabled = false),
            )
        assertEquals(spec, json.decodeFromString<PanelSpec>(json.encodeToString(spec)))
    }

    @Test
    fun percentileMatchesReferenceInterpolation() {
        assertEquals(2.5, RadarProcessing.percentile(listOf(0.0, 10.0), 25.0), 0.0)
        assertTrue(RadarProcessing.percentile(emptyList(), 10.0).isNaN())
    }

    @Test
    fun fullCircleAndWrappedAzimuthSelectionsAreDistinct() {
        val f = field(FloatArray(12) { 10f })
        assertEquals(
            12,
            RadarProcessing.apply(
                    f,
                    emptyMap(),
                    Filters(
                        min_azimuth_deg = 0.0,
                        max_azimuth_deg = 360.0,
                        noise_floor_enabled = false,
                    ),
                )
                .count { it.isFinite() },
        )
        assertEquals(
            6,
            RadarProcessing.apply(
                    f,
                    emptyMap(),
                    Filters(
                        min_azimuth_deg = 300.0,
                        max_azimuth_deg = 60.0,
                        noise_floor_enabled = false,
                    ),
                )
                .count { it.isFinite() },
        )
    }

    @Test
    fun averageAzimuthCentresUseBeamWidthWithoutFillingSectorGaps() {
        val f = field(FloatArray(12) { 1f })
        f.startAzimuths = doubleArrayOf(0.5, 1.51, 90.0, 180.0)
        f.stopAzimuths = f.startAzimuths.copyOf()
        f.beamWidthDeg = 1.0
        assertEquals(0, Geometry.rayAt(f, 0.25))
        assertEquals(1, Geometry.rayAt(f, 1.7))
        assertEquals(-1, Geometry.rayAt(f, 30.0))
    }

    @Test
    fun actualDesktopSessionRestoresEachPanelAndStringScalars() {
        val text = javaClass.getResource("/desktop-session.json")!!.readText()
        val restored = ProjectCodec.decode(text)
        assertEquals(4, restored.panels.size)
        assertEquals("20140918", restored.panels[0].selection.date)
        assertEquals("20261104", restored.panels[1].selection.date)
        assertEquals("VRADH", restored.panels[2].selection.quantity)
        assertEquals("2", restored.panels[2].selection.dataset)
        assertEquals(0.85f, restored.panels[0].display.opacity)
        assertFalse(restored.links.time)
        assertFalse(restored.panels[0].filters.background_model_enabled)
        val stringFilters =
            text
                .replace("\"noise_floor_enabled\": true", "\"noise_floor_enabled\": \"true\"")
                .replace("\"noise_floor_margin_db\": 0", "\"noise_floor_margin_db\": \"1.5\"")
        val parsed = ProjectCodec.decode(stringFilters)
        assertTrue(parsed.panels[0].filters.noise_floor_enabled)
        assertEquals(1.5, parsed.panels[0].filters.noise_floor_margin_db, 0.0)
    }
}
