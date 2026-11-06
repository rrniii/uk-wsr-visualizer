package com.rrniii.ukwsrvisualizer

import android.content.*
import android.graphics.*
import android.media.*
import androidx.core.content.FileProvider
import java.io.File
import java.time.Instant
import kotlin.math.*
import kotlinx.coroutines.*
import kotlinx.serialization.*
import kotlinx.serialization.json.*

class ArtifactExporter(private val context: Context, private val repository: CatalogRepository) {
    private val directory = File(context.filesDir, "exports").apply { mkdirs() }

    fun manifest(
        data: LoadedField,
        format: String,
        artifacts: List<File>,
        extra: JsonObject = buildJsonObject {},
    ): JsonObject = buildJsonObject {
        put("version", 2)
        put("created_at", Instant.now().toString())
        put("format", format)
        put("coordinate_mode", "georeferenced_screen_view")
        put(
            "software",
            buildJsonObject {
                put("name", "UK WSR Visualizer Android")
                put("version", BuildConfig.VERSION_NAME)
                put("build", BuildConfig.VERSION_CODE)
                put("git_sha", BuildConfig.GIT_SHA)
                put("qc_revision", BuildConfig.QC_REVISION)
                put("qc_implementation", "android-native-safe-v1")
            },
        )
        put("selection", json.encodeToJsonElement(data.spec.selection))
        put("display", json.encodeToJsonElement(data.spec.display))
        put("filters", json.encodeToJsonElement(data.spec.filters))
        put(
            "source",
            buildJsonObject {
                put("url", repository.sourceUrl(data.volume))
                put("sha256", data.sourceHash)
                put("bytes", data.sourceBytes)
            },
        )
        put(
            "geometry",
            buildJsonObject {
                put("rows", data.field.rows)
                put("columns", data.field.columns)
                put(
                    "ray_azimuths",
                    if (data.field.measuredAzimuths != 0) "measured ODIM startazA/stopazA"
                    else "regular ODIM PPI convention",
                )
                put("latitude", data.field.latitude)
                put("longitude", data.field.longitude)
                put("rstart_km", data.field.rstartKm)
                put("rscale_m", data.field.rscaleM)
                put("beam_width_deg", data.field.beamWidthDeg)
            },
        )
        put(
            "source_states",
            buildJsonObject {
                put("nodata", data.field.sourceStates.count { it.toInt() == 1 })
                put("undetect", data.field.sourceStates.count { it.toInt() == 2 })
                put("nonfinite", data.field.sourceStates.count { it.toInt() == 3 })
                put("display_masked", data.maskedCount)
            },
        )
        put(
            "citation",
            buildJsonObject {
                put("software_url", "https://github.com/rrniii/uk-wsr-visualizer")
                put("software_doi", "pending")
                put(
                    "source",
                    "Met Office UK weather-surveillance radar; consult source-data citation registry",
                )
                put("acknowledgement", "Data access and processing supported by JASMIN")
                put("basemap", "© OpenStreetMap contributors where displayed")
            },
        )
        put(
            "artifacts",
            buildJsonArray {
                artifacts.forEach { file ->
                    add(
                        buildJsonObject {
                            put("filename", file.name)
                            put("bytes", file.length())
                            put("sha256", fileHash(file))
                        }
                    )
                }
            },
        )
        extra.forEach { (k, v) -> put(k, v) }
    }

    private fun stem(data: LoadedField) =
        listOf(
                data.spec.selection.radar,
                data.spec.selection.date,
                data.spec.selection.pulse,
                data.spec.selection.time,
                data.field.quantity,
                data.field.dataset,
            )
            .joinToString("-")
            .replace(Regex("[^a-zA-Z0-9_-]"), "_")

    suspend fun png(data: LoadedField, bitmap: Bitmap): List<File> =
        withContext(Dispatchers.IO) {
            val target = File(directory, stem(data) + "-${System.currentTimeMillis()}.png")
            target.outputStream().use {
                check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) { "PNG encoder failed" }
            }
            val meta = File(target.path + ".manifest.json")
            CatalogRepository.atomicWrite(
                meta,
                json.encodeToString(manifest(data, "png", listOf(target))).toByteArray(),
            )
            listOf(target, meta)
        }

    suspend fun source(data: LoadedField): List<File> =
        withContext(Dispatchers.IO) {
            val source = repository.download(data.volume)
            val dest = File(directory, stem(data) + ".h5")
            source.copyTo(dest, overwrite = true)
            require(fileHash(dest) == data.sourceHash) { "Source checksum changed" }
            val meta = File(dest.path + ".manifest.json")
            CatalogRepository.atomicWrite(
                meta,
                json.encodeToString(manifest(data, "hdf5", listOf(dest))).toByteArray(),
            )
            listOf(dest, meta)
        }

    suspend fun metadata(data: LoadedField): List<File> =
        withContext(Dispatchers.IO) {
            val target = File(directory, stem(data) + ".manifest.json")
            CatalogRepository.atomicWrite(
                target,
                json.encodeToString(manifest(data, "metadata", emptyList())).toByteArray(),
            )
            listOf(target)
        }

    suspend fun video(
        initial: LoadedField,
        times: List<String>,
        progress: (String) -> Unit,
    ): List<File> =
        withContext(Dispatchers.Default) {
            require(times.isNotEmpty() && times.size <= 600) { "Select 1–600 frames" }
            val width = 720
            val height = 720
            val fps = 5
            val plan =
                json.encodeToString(initial.spec) +
                    times.joinToString() +
                    width +
                    BuildConfig.GIT_SHA
            val cache =
                File(context.cacheDir, "video-frames/${sha256(plan.toByteArray())}").apply {
                    mkdirs()
                }
            val target = File(directory, stem(initial) + "-${System.currentTimeMillis()}.mp4")
            val part = File(target.path + ".partial")
            val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
            val colorFormats =
                codec.codecInfo.getCapabilitiesForType(MediaFormat.MIMETYPE_VIDEO_AVC).colorFormats
            val colorFormat =
                listOf(
                        MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Flexible,
                        MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420Planar,
                        MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar,
                    )
                    .firstOrNull { it in colorFormats }
                    ?: error("Device has no supported H.264 input format")
            val format =
                MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height).apply {
                    setInteger(MediaFormat.KEY_COLOR_FORMAT, colorFormat)
                    setInteger(MediaFormat.KEY_BIT_RATE, 3_000_000)
                    setInteger(MediaFormat.KEY_FRAME_RATE, fps)
                    setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 1)
                }
            var muxer: MediaMuxer? = null
            var started = false
            var track = -1
            var codecStarted = false
            var completed = false
            val info = MediaCodec.BufferInfo()
            val records = mutableListOf<JsonElement>()
            val skipped = mutableListOf<String>()
            var encoded = 0
            try {
                codec.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
                codec.start()
                codecStarted = true
                muxer = MediaMuxer(part.path, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
                fun drain(wait: Boolean): Boolean {
                    while (true) {
                        val output = codec.dequeueOutputBuffer(info, if (wait) 10_000 else 0)
                        when {
                            output == MediaCodec.INFO_TRY_AGAIN_LATER -> return false
                            output == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                                check(!started)
                                track = muxer!!.addTrack(codec.outputFormat)
                                muxer!!.start()
                                started = true
                            }
                            output >= 0 -> {
                                val buffer = codec.getOutputBuffer(output)!!
                                if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0)
                                    info.size = 0
                                if (info.size > 0) {
                                    check(started)
                                    buffer.position(info.offset)
                                    buffer.limit(info.offset + info.size)
                                    muxer!!.writeSampleData(track, buffer, info)
                                }
                                val done = info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0
                                codec.releaseOutputBuffer(output, false)
                                if (done) return true
                            }
                        }
                    }
                }
                for ((position, time) in times.withIndex()) {
                    currentCoroutineContext().ensureActive()
                    progress("Frame ${position+1}/${times.size} · $time UTC")
                    val image = File(cache, "$time.png")
                    val evidence = File(cache, "$time.json")
                    var bitmap: Bitmap? = null
                    try {
                        if (image.exists() && evidence.exists()) {
                            bitmap = BitmapFactory.decodeFile(image.path)
                            records += json.parseToJsonElement(evidence.readText())
                        } else {
                            val data =
                                repository
                                    .load(
                                        initial.spec.copy(
                                            selection = initial.spec.selection.copy(time = time)
                                        )
                                    )
                                    .first
                            val raster = RadarRaster.make(data, 720)
                            bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
                            // Fixed radar-centred geography for every frame; basemap omitted from
                            // video.
                            RadarRaster.draw(
                                Canvas(bitmap),
                                width,
                                height,
                                data.copy(
                                    spec =
                                        data.spec.copy(
                                            display = data.spec.display.copy(basemap = "grid")
                                        )
                                ),
                                raster,
                                MapMath.fit(data.field, width, height),
                                header = true,
                            )
                            image.outputStream().use {
                                check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it))
                            }
                            val record = buildJsonObject {
                                put("time", time)
                                put("source_url", repository.sourceUrl(data.volume))
                                put("source_sha256", data.sourceHash)
                                put("source_bytes", data.sourceBytes)
                            }
                            CatalogRepository.atomicWrite(
                                evidence,
                                json.encodeToString(record).toByteArray(),
                            )
                            records += record
                            raster.bitmap.recycle()
                        }
                    } catch (e: Exception) {
                        if (e is CancellationException) throw e
                        skipped += "$time: ${e.message}"
                        continue
                    }
                    require(bitmap != null) { "Saved export frame is unreadable" }
                    var input = -1
                    while (input < 0) {
                        currentCoroutineContext().ensureActive()
                        drain(false)
                        input = codec.dequeueInputBuffer(10_000)
                    }
                    val count = writeYuv(codec, input, bitmap, colorFormat, width, height)
                    codec.queueInputBuffer(input, 0, count, encoded * 1_000_000L / fps, 0)
                    encoded++
                    bitmap.recycle()
                    drain(false)
                }
                require(encoded > 0) { "No selected frame could be rendered" }
                var input = -1
                while (input < 0) {
                    currentCoroutineContext().ensureActive()
                    drain(false)
                    input = codec.dequeueInputBuffer(10_000)
                }
                codec.queueInputBuffer(
                    input,
                    0,
                    0,
                    encoded * 1_000_000L / fps,
                    MediaCodec.BUFFER_FLAG_END_OF_STREAM,
                )
                val deadline = System.nanoTime() + 60_000_000_000L
                while (!drain(true)) {
                    currentCoroutineContext().ensureActive()
                    check(System.nanoTime() < deadline) { "Video encoder did not finish" }
                }
                muxer.stop()
                started = false
                muxer.release()
                muxer = null
                codec.stop()
                codecStarted = false
                require(part.length() > 0 && part.renameTo(target)) {
                    "Could not publish completed video"
                }
                val extra = buildJsonObject {
                    put("coordinate_mode", "georeferenced_grid_view")
                    put("frame_rate", fps)
                    put("requested_frames", times.size)
                    put("encoded_frames", encoded)
                    put("duration_seconds", encoded.toDouble() / fps)
                    put("frames", JsonArray(records))
                    put("skipped_frames", json.encodeToJsonElement(skipped))
                }
                val meta = File(target.path + ".manifest.json")
                CatalogRepository.atomicWrite(
                    meta,
                    json
                        .encodeToString(manifest(initial, "mp4", listOf(target), extra))
                        .toByteArray(),
                )
                completed = true
                listOf(target, meta)
            } finally {
                if (started) runCatching { muxer?.stop() }
                runCatching { muxer?.release() }
                if (codecStarted) runCatching { codec.stop() }
                codec.release()
                part.delete()
                if (!completed) target.delete()
            }
        }

    private fun writeYuv(
        codec: MediaCodec,
        index: Int,
        bitmap: Bitmap,
        format: Int,
        width: Int,
        height: Int,
    ): Int {
        val pixels = IntArray(width * height)
        bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
        val size = width * height
        fun yuv(color: Int): IntArray {
            val r = Color.red(color)
            val g = Color.green(color)
            val b = Color.blue(color)
            return intArrayOf(
                ((66 * r + 129 * g + 25 * b + 128 shr 8) + 16).coerceIn(0, 255),
                ((-38 * r - 74 * g + 112 * b + 128 shr 8) + 128).coerceIn(0, 255),
                ((112 * r - 94 * g - 18 * b + 128 shr 8) + 128).coerceIn(0, 255),
            )
        }
        val image = codec.getInputImage(index)
        if (image != null) {
            val planes = image.planes
            for (row in 0 until height) for (col in 0 until width) {
                val p = yuv(pixels[row * width + col])
                planes[0]
                    .buffer
                    .put(row * planes[0].rowStride + col * planes[0].pixelStride, p[0].toByte())
                if (row % 2 == 0 && col % 2 == 0) {
                    planes[1]
                        .buffer
                        .put(
                            row / 2 * planes[1].rowStride + col / 2 * planes[1].pixelStride,
                            p[1].toByte(),
                        )
                    planes[2]
                        .buffer
                        .put(
                            row / 2 * planes[2].rowStride + col / 2 * planes[2].pixelStride,
                            p[2].toByte(),
                        )
                }
            }
        } else {
            val buffer = codec.getInputBuffer(index)!!
            buffer.clear()
            val bytes = ByteArray(size * 3 / 2)
            var chroma = 0
            for (row in 0 until height) for (col in 0 until width) {
                val p = yuv(pixels[row * width + col])
                bytes[row * width + col] = p[0].toByte()
                if (row % 2 == 0 && col % 2 == 0) {
                    if (format == MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar) {
                        bytes[size + chroma * 2] = p[1].toByte()
                        bytes[size + chroma * 2 + 1] = p[2].toByte()
                    } else {
                        bytes[size + chroma] = p[1].toByte()
                        bytes[size + size / 4 + chroma] = p[2].toByte()
                    }
                    chroma++
                }
            }
            buffer.put(bytes)
        }
        return size * 3 / 2
    }

    companion object {
        fun share(context: Context, files: List<File>) {
            val uris =
                ArrayList(
                    files.map {
                        FileProvider.getUriForFile(context, context.packageName + ".files", it)
                    }
                )
            val intent =
                Intent(Intent.ACTION_SEND_MULTIPLE).apply {
                    type =
                        if (files.size == 1 && files.first().extension == "png") "image/png"
                        else "application/octet-stream"
                    putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
                    addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                }
            context.startActivity(Intent.createChooser(intent, "Share UK WSR artifacts"))
        }
    }
}
