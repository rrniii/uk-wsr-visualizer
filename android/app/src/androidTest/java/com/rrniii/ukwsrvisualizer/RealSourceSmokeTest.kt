package com.rrniii.ukwsrvisualizer

import android.graphics.Bitmap
import android.graphics.Canvas
import android.media.MediaMetadataRetriever
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import org.junit.*
import org.junit.runner.RunWith

/** Explicit opt-in live-source/export check; deterministic fixtures remain the normal CI gate. */
@RunWith(AndroidJUnit4::class)
class RealSourceSmokeTest {
    @Test
    fun publishedSourceRendersAndExportsWithResume() = runBlocking {
        Assume.assumeTrue(InstrumentationRegistry.getArguments().getString("runLive") == "true")
        withTimeout(240_000) {
            val context = InstrumentationRegistry.getInstrumentation().targetContext
            val repository = CatalogRepository(context)
            val root = repository.root(DataEra.DUAL)
            Assert.assertTrue(root.radars.any { it.radar == "castor-bay" })
            val spec =
                PanelSpec(
                    Selection(
                        radar = "castor-bay",
                        date = "20261104",
                        pulse = "lp",
                        time = "0000",
                        quantity = "DBZH",
                        dataset = "1",
                    ),
                    Filters(noise_floor_enabled = false),
                )
            val loaded = repository.load(spec).first
            Assert.assertEquals(360, loaded.field.rows)
            Assert.assertTrue(loaded.field.values.count { it.isFinite() } > 10000)
            Assert.assertEquals(loaded.volume.size_bytes, loaded.sourceBytes)
            val before = fileHash(repository.sourceFile(loaded.volume))
            val raster = RadarRaster.make(loaded, 512)
            val pixels = IntArray(512 * 512)
            raster.bitmap.getPixels(pixels, 0, 512, 0, 0, 512, 512)
            Assert.assertTrue(
                "Real PPI must contain radar pixels",
                pixels.count { it ushr 24 != 0 } > 5000,
            )
            val screenshot = Bitmap.createBitmap(720, 720, Bitmap.Config.ARGB_8888)
            RadarRaster.draw(
                Canvas(screenshot),
                720,
                720,
                loaded,
                raster,
                MapMath.fit(loaded.field, 720, 720),
                header = true,
            )
            val exporter = ArtifactExporter(context, repository)
            val png = exporter.png(loaded, screenshot)
            Assert.assertTrue(png.first().length() > 1000)
            val manifest = json.parseToJsonElement(png.last().readText()).jsonObject
            Assert.assertEquals(
                loaded.sourceHash,
                manifest["source"]!!.jsonObject["sha256"]!!.jsonPrimitive.content,
            )
            try {
                repository.load(
                    spec.copy(
                        selection = spec.selection.copy(quantity = "NOT_A_FIELD", dataset = "")
                    )
                )
                Assert.fail("Missing requested field must not substitute")
            } catch (expected: java.io.IOException) {
                Assert.assertTrue(expected.message.orEmpty().contains("unavailable"))
            }
            val times = listOf("0000", "0005", "0010")
            val cacheRoot = File(context.cacheDir, "video-frames")
            cacheRoot.deleteRecursively()
            val job = launch {
                exporter.video(loaded, times) {
                    if (it.startsWith("Frame 2/"))
                        throw CancellationException("Exercise cancellation")
                }
            }
            job.join()
            Assert.assertTrue(job.isCancelled)
            val saved = cacheRoot.walkTopDown().first { it.name == "0000.png" }
            val timestamp = saved.lastModified()
            Assert.assertFalse(
                File(context.filesDir, "exports").listFiles().orEmpty().any {
                    it.extension == "partial"
                }
            )
            val video = exporter.video(loaded, times) {}
            Assert.assertEquals("A resumed frame must be reused", timestamp, saved.lastModified())
            val meta = json.parseToJsonElement(video.last().readText()).jsonObject
            Assert.assertEquals(3, meta["encoded_frames"]!!.jsonPrimitive.int)
            Assert.assertEquals(
                times,
                meta["frames"]!!.jsonArray.map { it.jsonObject["time"]!!.jsonPrimitive.content },
            )
            Assert.assertEquals(0, meta["skipped_frames"]!!.jsonArray.size)
            val retriever = MediaMetadataRetriever()
            try {
                retriever.setDataSource(video.first().path)
                Assert.assertEquals(
                    "720",
                    retriever.extractMetadata(MediaMetadataRetriever.METADATA_KEY_VIDEO_WIDTH),
                )
                Assert.assertNotNull(retriever.getFrameAtTime(200_000))
                val duration =
                    retriever
                        .extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)!!
                        .toLong()
                Assert.assertTrue("Unexpected duration $duration", duration in 400..800)
            } finally {
                retriever.release()
            }
            Assert.assertEquals(before, fileHash(repository.sourceFile(loaded.volume)))
            File(context.filesDir, "live-smoke-result.json")
                .writeText(
                    buildJsonObject {
                        put("source_sha256", before)
                        put("radar_pixels", pixels.count { it ushr 24 != 0 })
                        put("png", png.first().name)
                        put("mp4", video.first().name)
                        put("encoded_frames", 3)
                        put("resume_verified", true)
                        put("source_unchanged", true)
                    }
                        .toString()
                )
        }
    }
}
