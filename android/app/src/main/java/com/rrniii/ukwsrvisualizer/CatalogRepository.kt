package com.rrniii.ukwsrvisualizer

import android.content.Context
import java.io.*
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.*
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.*
import okhttp3.*

fun sha256(bytes: ByteArray) =
    MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

fun fileHash(file: File): String {
    val d = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { i ->
        val b = ByteArray(65536)
        while (true) {
            val n = i.read(b)
            if (n < 0) break
            d.update(b, 0, n)
        }
    }
    return d.digest().joinToString("") { "%02x".format(it) }
}

class CatalogRepository(context: Context) {
    val rawRoot = File(context.cacheDir, "raw-hdf5").apply { mkdirs() }
    private val catalogRoot = File(context.cacheDir, "catalogue").apply { mkdirs() }
    private val lock = Mutex()
    val client =
        OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .callTimeout(3, TimeUnit.MINUTES)
            .build()
    var lastReadCached = false
        private set

    suspend inline fun <reified T> read(url: String): T = json.decodeFromString(fetchJson(url))

    suspend fun fetchJson(url: String): String =
        withContext(Dispatchers.IO) {
            require(url.startsWith("https://")) { "Catalogue URL must use HTTPS" }
            val cache = File(catalogRoot, sha256(url.toByteArray()) + ".json")
            try {
                val body =
                    client
                        .newCall(
                            Request.Builder()
                                .url(url)
                                .header(
                                    "User-Agent",
                                    "UKWSRVisualizer-Android/${BuildConfig.VERSION_NAME}",
                                )
                                .build()
                        )
                        .execute()
                        .use { r ->
                            if (!r.isSuccessful) throw HttpFailure("Catalogue HTTP ${r.code}: $url")
                            require((r.body.contentLength()) <= 8 * 1024 * 1024) {
                                "Catalogue exceeds size limit"
                            }
                            r.body.string().also {
                                require(it.length <= 8 * 1024 * 1024) {
                                    "Catalogue exceeds size limit"
                                }
                            }
                        }
                json.parseToJsonElement(body)
                atomicWrite(cache, body.toByteArray())
                lastReadCached = false
                body
            } catch (e: IOException) {
                if (e is HttpFailure || !cache.exists()) throw e
                lastReadCached = true
                cache.readText()
            }
        }

    suspend fun root(era: DataEra) = read<RootCatalog>(era.catalogUrl)

    suspend fun days(radar: Radar, year: String, era: DataEra): List<Day> {
        require(year in radar.years) { "Year unavailable" }
        val key =
            radar.coverage_keys.firstOrNull { it.contains("/$year/") }
                ?: "${era.prefix}/catalog/pvol/${radar.radar}/$year/coverage.json"
        return read<Coverage>(PUBLIC_BASE + key).days.sortedByDescending { it.date }
    }

    suspend fun day(selection: Selection): DayCatalog {
        require(selection.date.matches(Regex("[0-9]{8}"))) { "Choose a valid catalogue date" }
        val e = DataEra.valueOf(selection.era)
        val d = selection.date
        return read(
            PUBLIC_BASE +
                "${e.prefix}/catalog/pvol/${selection.radar}/${d.take(4)}/${d.substring(4,6)}/${d.takeLast(2)}/catalog.json"
        )
    }

    fun sourceUrl(volume: Volume) =
        volume.object_url.ifEmpty {
            if (volume.object_key.isNotEmpty()) PUBLIC_BASE + volume.object_key else ""
        }

    fun sourceFile(volume: Volume) = File(rawRoot, sha256(sourceUrl(volume).toByteArray()) + ".h5")

    suspend fun download(volume: Volume): File =
        withContext(Dispatchers.IO) {
            lock.withLock {
                val url = sourceUrl(volume)
                require(url.startsWith("https://")) {
                    "No HTTPS source URL in selected catalogue record"
                }
                val target = sourceFile(volume)
                if (
                    target.exists() &&
                        target.length() > 0 &&
                        (volume.size_bytes <= 0 || target.length() == volume.size_bytes)
                ) {
                    target.setLastModified(System.currentTimeMillis())
                    return@withLock target
                }
                val part = File(target.path + ".part")
                try {
                    val call =
                        client.newCall(
                            Request.Builder()
                                .url(url)
                                .header(
                                    "User-Agent",
                                    "UKWSRVisualizer-Android/${BuildConfig.VERSION_NAME}",
                                )
                                .build()
                        )
                    val cancel =
                        currentCoroutineContext()[Job]?.invokeOnCompletion {
                            if (it is CancellationException) call.cancel()
                        }
                    try {
                        call.execute().use { response ->
                            if (!response.isSuccessful)
                                throw IOException("Source download HTTP ${response.code}")
                            require(response.body.contentLength() <= 512L * 1024 * 1024) {
                                "Selected source exceeds the 512 MiB mobile limit"
                            }
                            response.body.byteStream().use { input ->
                                part.outputStream().use { out ->
                                    val bytes = ByteArray(65536)
                                    var total = 0L
                                    while (true) {
                                        currentCoroutineContext().ensureActive()
                                        val n = input.read(bytes)
                                        if (n < 0) break
                                        total += n
                                        require(total <= 512L * 1024 * 1024) {
                                            "Source exceeds mobile limit"
                                        }
                                        out.write(bytes, 0, n)
                                    }
                                }
                            }
                        }
                    } finally {
                        cancel?.dispose()
                    }
                    if (volume.size_bytes > 0 && part.length() != volume.size_bytes)
                        throw IOException(
                            "Source size differs from catalogue (${part.length()} / ${volume.size_bytes})"
                        )
                    part.inputStream().use { input ->
                        val magic = ByteArray(8)
                        require(
                            input.read(magic) == 8 &&
                                magic.contentEquals(byteArrayOf(-119, 72, 68, 70, 13, 10, 26, 10))
                        ) {
                            "Downloaded object is not HDF5"
                        }
                    }
                    if (!part.renameTo(target)) throw IOException("Could not commit cached source")
                    target
                } finally {
                    part.delete()
                }
            }
        }

    suspend fun load(spec: PanelSpec): Pair<LoadedField, List<FieldRecord>> =
        withContext(Dispatchers.IO) {
            val day = day(spec.selection)
            val record =
                day.files.firstOrNull {
                    it.pulse == spec.selection.pulse && it.time == spec.selection.time
                } ?: throw IOException("Requested scan is unavailable; no substitute was loaded")
            val file = download(record)
            currentCoroutineContext().ensureActive()
            val fields = NativeBridge.inspect(file.path)
            val wanted =
                when {
                    spec.selection.quantity.isEmpty() && spec.selection.dataset.isEmpty() ->
                        fields.firstOrNull { it.quantity == "DBZH" } ?: fields.firstOrNull()
                    spec.selection.dataset.isEmpty() ->
                        fields.firstOrNull { it.quantity == spec.selection.quantity }
                    else ->
                        fields.firstOrNull {
                            it.dataset.removePrefix("dataset") ==
                                spec.selection.dataset.removePrefix("dataset") &&
                                it.quantity == spec.selection.quantity
                        }
                }
                    ?: throw IOException(
                        "Requested variable/elevation is unavailable; no substitute was loaded"
                    )
            val actual =
                spec.copy(
                    selection =
                        spec.selection.copy(
                            dataset = wanted.dataset.removePrefix("dataset"),
                            quantity = wanted.quantity,
                        )
                )
            val field = NativeBridge.read(file.path, wanted.dataset, wanted.quantity)
            require(field.latitude.isFinite() && field.longitude.isFinite() && field.rscaleM > 0) {
                "Source has invalid radar geometry"
            }
            val companions = mutableMapOf<String, FloatArray>()
            val names =
                setOf("DBZH", "CI", "SQIH", "RHOHV", "ZDR", "PHIDP", "UPHIDP", "VRADH", "WRADH")
            if (actual.filters.noise_floor_enabled)
                for (f in fields.filter { it.dataset == wanted.dataset && it.quantity in names }) {
                    currentCoroutineContext().ensureActive()
                    val decoded =
                        if (f.quantity == field.quantity) field
                        else NativeBridge.read(file.path, f.dataset, f.quantity)
                    if (
                        decoded.rows == field.rows &&
                            decoded.columns == field.columns &&
                            decoded.startAzimuths.contentEquals(field.startAzimuths) &&
                            decoded.stopAzimuths.contentEquals(field.stopAzimuths)
                    )
                        companions[f.quantity] = decoded.values
                }
            val filtered = RadarProcessing.apply(field, companions, actual.filters)
            LoadedField(
                actual,
                record,
                field,
                companions,
                fileHash(file),
                file.length(),
                filtered,
                field.values.indices.count {
                    field.values[it].isFinite() && !filtered[it].isFinite()
                },
            ) to fields
        }

    suspend fun clearRaw() =
        withContext(Dispatchers.IO) {
            lock.withLock { rawRoot.listFiles()?.forEach { it.delete() } }
        }

    suspend fun prune(preserved: Set<String>) =
        withContext(Dispatchers.IO) {
            lock.withLock {
                val files =
                    rawRoot
                        .listFiles()
                        ?.filter { it.extension == "h5" }
                        ?.sortedBy { it.lastModified() } ?: emptyList()
                var size = files.sumOf { it.length() }
                val oldest = System.currentTimeMillis() - 7L * 24 * 60 * 60 * 1000
                files.forEach { f ->
                    if (
                        f.path !in preserved &&
                            (f.lastModified() < oldest || size > 8L * 1024 * 1024 * 1024)
                    ) {
                        val length = f.length()
                        if (f.delete()) size -= length
                    }
                }
            }
        }

    class HttpFailure(message: String) : IOException(message)

    companion object {
        fun atomicWrite(file: File, bytes: ByteArray) {
            file.parentFile?.mkdirs()
            val temp = File(file.path + "." + java.util.UUID.randomUUID() + ".tmp")
            temp.outputStream().use {
                it.write(bytes)
                it.flush()
            }
            check(temp.renameTo(file)) { "Could not save ${file.name}" }
        }
    }
}
