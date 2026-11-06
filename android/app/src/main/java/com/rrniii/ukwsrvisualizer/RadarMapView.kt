package com.rrniii.ukwsrvisualizer

import android.content.Context
import android.graphics.*
import android.util.LruCache
import android.view.*
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import kotlin.math.*
import kotlinx.coroutines.*
import okhttp3.*

data class Viewport(val latitude: Double, val longitude: Double, val zoom: Double)

data class Raster(
    val bitmap: Bitmap,
    val west: Double,
    val north: Double,
    val east: Double,
    val south: Double,
    val low: Double,
    val high: Double,
)

object MapMath {
    fun x(lon: Double) = (lon + 180) / 360

    fun y(lat: Double) =
        (1 - ln(tan(Math.PI / 4 + Math.toRadians(lat.coerceIn(-85.0, 85.0)) / 2)) / Math.PI) / 2

    fun lon(x: Double) = x * 360 - 180

    fun lat(y: Double) = Math.toDegrees(atan(sinh(Math.PI * (1 - 2 * y))))

    fun rangeAz(field: NativeField, lat: Double, lon: Double): Pair<Double, Double> {
        val a = Math.toRadians(field.latitude)
        val b = Math.toRadians(lat)
        val dl = Math.toRadians(lon - field.longitude)
        val h = sin((b - a) / 2).pow(2) + cos(a) * cos(b) * sin(dl / 2).pow(2)
        val range = 6371000.0 * 2 * asin(sqrt(h.coerceIn(0.0, 1.0)))
        val az =
            Geometry.wrap(
                Math.toDegrees(atan2(sin(dl) * cos(b), cos(a) * sin(b) - sin(a) * cos(b) * cos(dl)))
            )
        return range to az
    }

    fun fit(field: NativeField, width: Int, height: Int): Viewport {
        val metresPerPixel = field.maxRangeM * 2.25 / max(100, min(width, height))
        val zoom = ln(156543.03392 * cos(Math.toRadians(field.latitude)) / metresPerPixel) / ln(2.0)
        return Viewport(field.latitude, field.longitude, zoom.coerceIn(2.0, 15.0))
    }
}

object RadarRaster {
    fun limits(data: LoadedField): Pair<Double, Double> {
        val q = data.field.quantity
        val standard =
            when {
                q.startsWith("VRAD") -> -30.0 to 30.0
                q in setOf("RHOHV", "RHO", "CC", "SQIH") -> 0.5 to 1.05
                q.startsWith("ZDR") -> -1.0 to 8.0
                q == "CI" -> 0.0 to 20.0
                q.contains("PHIDP") -> -180.0 to 180.0
                q.startsWith("WRAD") -> 0.0 to 10.0
                q.startsWith("KDP") -> -2.0 to 5.0
                q.startsWith("SNR") -> -20.0 to 30.0
                q.startsWith("RATE") || q == "RRATE" -> 0.0 to 50.0
                else -> -30.0 to 60.0
            }
        val lo = data.spec.display.min ?: standard.first
        val hi = data.spec.display.max ?: standard.second
        return lo to max(lo + 0.001, hi)
    }

    fun color(value: Float, low: Double, high: Double, palette: String, quantity: String): Int {
        if (!value.isFinite() || MomentNames.reflectivity(quantity) && value < low)
            return Color.TRANSPARENT
        val t = ((value - low) / (high - low)).coerceIn(0.0, 1.0).toFloat()
        if (palette == "gray")
            return Color.rgb((t * 255).toInt(), (t * 255).toInt(), (t * 255).toInt())
        val ramp =
            when {
                palette == "velocity" || palette == "auto" && quantity.startsWith("VRAD") ->
                    intArrayOf(0xff265db0.toInt(), 0xfff8fafc.toInt(), 0xffbe303c.toInt())
                palette == "viridis" ->
                    intArrayOf(
                        0xff440154.toInt(),
                        0xff3b528b.toInt(),
                        0xff21918c.toInt(),
                        0xff5ec962.toInt(),
                        0xfffde725.toInt(),
                    )
                else ->
                    intArrayOf(
                        0xff6f87a8.toInt(),
                        0xff1b8cbe.toInt(),
                        0xff47b857.toInt(),
                        0xffe1df35.toInt(),
                        0xfff28c23.toInt(),
                        0xffd92d35.toInt(),
                        0xff8e3a9c.toInt(),
                    )
            }
        val p = t * (ramp.size - 1)
        val a = p.toInt().coerceAtMost(ramp.size - 2)
        val f = p - a
        fun channel(fn: (Int) -> Int) = (fn(ramp[a]) * (1 - f) + fn(ramp[a + 1]) * f).roundToInt()
        return Color.rgb(channel(Color::red), channel(Color::green), channel(Color::blue))
    }

    suspend fun make(data: LoadedField, size: Int = 1024): Raster =
        withContext(Dispatchers.Default) {
            val field = data.field
            val delta = field.maxRangeM / 6371000 * 180 / Math.PI
            val longitudeDelta = delta / max(0.1, cos(Math.toRadians(abs(field.latitude) + delta)))
            val west = MapMath.x(field.longitude - longitudeDelta)
            val east = MapMath.x(field.longitude + longitudeDelta)
            val north = MapMath.y(field.latitude + delta)
            val south = MapMath.y(field.latitude - delta)
            val (low, high) = limits(data)
            val pixels = IntArray(size * size)
            val azIndex = IntArray(36000) { Geometry.rayAt(field, it / 100.0 + 0.005) }
            val xs = DoubleArray(size) { MapMath.lon(west + (it + 0.5) / size * (east - west)) }
            for (y in 0 until size) {
                currentCoroutineContext().ensureActive()
                val lat = MapMath.lat(north + (y + 0.5) / size * (south - north))
                for (x in 0 until size) {
                    val (range, az) = MapMath.rangeAz(field, lat, xs[x])
                    val c = floor((range - field.rstartKm * 1000) / field.rscaleM).toInt()
                    if (c in 0 until field.columns) {
                        val r = azIndex[(az * 100).toInt().coerceIn(0, 35999)]
                        if (r >= 0)
                            pixels[y * size + x] =
                                color(
                                    data.values[r * field.columns + c],
                                    low,
                                    high,
                                    data.spec.display.palette,
                                    field.quantity,
                                )
                    }
                }
            }
            Raster(
                Bitmap.createBitmap(pixels, size, size, Bitmap.Config.ARGB_8888),
                west,
                north,
                east,
                south,
                low,
                high,
            )
        }

    fun draw(
        canvas: Canvas,
        width: Int,
        height: Int,
        data: LoadedField,
        raster: Raster,
        view: Viewport,
        tiles: ((Canvas, Viewport, Int, Int) -> Unit)? = null,
        header: Boolean = false,
    ) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        canvas.drawColor(Color.rgb(231, 237, 239))
        val scale = 256 * 2.0.pow(view.zoom)
        val left = MapMath.x(view.longitude) * scale - width / 2
        val top = MapMath.y(view.latitude) * scale - height / 2
        tiles?.invoke(canvas, view, width, height)
        paint.alpha = (data.spec.display.opacity.coerceIn(0f, 1f) * 255).roundToInt()
        paint.isFilterBitmap = false
        canvas.drawBitmap(
            raster.bitmap,
            null,
            RectF(
                (raster.west * scale - left).toFloat(),
                (raster.north * scale - top).toFloat(),
                (raster.east * scale - left).toFloat(),
                (raster.south * scale - top).toFloat(),
            ),
            paint,
        )
        paint.alpha = 255
        val cx = (MapMath.x(data.field.longitude) * scale - left).toFloat()
        val cy = (MapMath.y(data.field.latitude) * scale - top).toFloat()
        if (data.spec.display.rings) {
            paint.style = Paint.Style.STROKE
            paint.color = 0x60708080
            paint.strokeWidth = 1.5f
            val unit = scale / (40075016.686 * cos(Math.toRadians(data.field.latitude)))
            for (km in 50..500 step 50) if (km * 1000 <= data.field.maxRangeM) {
                val radius = (km * 1000 * unit).toFloat()
                canvas.drawCircle(cx, cy, radius, paint)
            }
            canvas.drawLine(cx - 8, cy, cx + 8, cy, paint)
            canvas.drawLine(cx, cy - 8, cx, cy + 8, paint)
            paint.style = Paint.Style.FILL
        }
        val legendWidth = min(220f, width * 0.44f)
        val lx = width - legendWidth - 14
        val ly = height - 42f
        paint.color = 0xeefafafa.toInt()
        canvas.drawRoundRect(lx - 7, ly - 19, width - 7f, height - 5f, 5f, 5f, paint)
        for (i in 0 until legendWidth.toInt()) {
            paint.color =
                color(
                    (raster.low + (raster.high - raster.low) * i / legendWidth).toFloat(),
                    raster.low,
                    raster.high,
                    data.spec.display.palette,
                    data.field.quantity,
                )
            canvas.drawRect(lx + i, ly, lx + i + 1, ly + 9, paint)
        }
        paint.color = Color.DKGRAY
        paint.textSize = 12f
        canvas.drawText(
            "${data.field.quantity}  %.1f — %.1f".format(raster.low, raster.high),
            lx,
            ly - 4,
            paint,
        )
        if (data.spec.display.basemap == "osm") {
            paint.color = 0xeefafafa.toInt()
            canvas.drawRect(3f, height - 23f, 176f, height - 3f, paint)
            paint.color = Color.DKGRAY
            paint.textSize = 11f
            canvas.drawText("© OpenStreetMap contributors", 7f, height - 9f, paint)
        }
        if (header) {
            paint.color = 0xeeffffff.toInt()
            canvas.drawRect(0f, 0f, width.toFloat(), 58f, paint)
            paint.color = Color.DKGRAY
            paint.textSize = 16f
            canvas.drawText(data.spec.selection.label, 12f, 22f, paint)
            paint.textSize = 13f
            canvas.drawText(
                "${data.field.quantity} · %.2f° · %s"
                    .format(
                        data.field.elevationDeg,
                        if (data.spec.filters.noise_floor_enabled) "cleanup on"
                        else "decoded baseline",
                    ),
                12f,
                44f,
                paint,
            )
        }
    }
}

class RadarMapView(context: Context) : View(context) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var renderJob: Job? = null
    private var requestedData: LoadedField? = null
    var onIdentify: ((String) -> Unit)? = null
    var onRendered: ((LoadedField) -> Unit)? = null
    var onViewport: ((Viewport) -> Unit)? = null
    var data: LoadedField? = null
        private set

    var raster: Raster? = null
        private set

    var viewport: Viewport? = null
        private set

    private val tileMemory =
        object : LruCache<String, Bitmap>(20 * 1024 * 1024) {
            override fun sizeOf(k: String, v: Bitmap) = v.byteCount
        }
    private val tileJobs = ConcurrentHashMap<String, Boolean>()
    private val tilesDir = File(context.cacheDir, "basemap-tiles").apply { mkdirs() }
    private val client =
        OkHttpClient.Builder().callTimeout(java.time.Duration.ofSeconds(20)).build()
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var downX = 0f
    private var downY = 0f
    private var lastX = 0f
    private var lastY = 0f
    private var dragging = false
    private val detector =
        ScaleGestureDetector(
            context,
            object : ScaleGestureDetector.SimpleOnScaleGestureListener() {
                override fun onScale(d: ScaleGestureDetector): Boolean {
                    val v = viewport ?: return false
                    viewport =
                        v.copy(
                            zoom =
                                (v.zoom + ln(d.scaleFactor.toDouble()) / ln(2.0)).coerceIn(
                                    2.0,
                                    17.0,
                                )
                        )
                    onViewport?.invoke(viewport!!)
                    invalidate()
                    return true
                }
            },
        )

    fun show(value: LoadedField?) {
        if (value === requestedData) return
        requestedData = value
        renderJob?.cancel()
        if (value == null) {
            data = null
            raster = null
            invalidate()
            return
        }
        // Keep the last complete map and its source identity until its replacement is ready.
        if (data == null) data = value
        renderJob = scope.launch {
            val r = RadarRaster.make(value)
            if (requestedData === value) {
                val previous = data
                if (
                    viewport == null ||
                        previous?.field?.latitude != value.field.latitude ||
                        previous.field.longitude != value.field.longitude
                ) {
                    viewport = MapMath.fit(value.field, width, height)
                }
                data = value
                raster = r
                onRendered?.invoke(value)
                invalidate()
            }
        }
        invalidate()
    }

    fun setViewport(value: Viewport) {
        if (viewport != value) {
            viewport = value
            invalidate()
        }
    }

    fun fit() {
        data?.let {
            viewport = MapMath.fit(it.field, width, height)
            onViewport?.invoke(viewport!!)
            invalidate()
        }
    }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        if (ow == 0 || oh == 0) data?.let { viewport = MapMath.fit(it.field, w, h) }
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        canvas.clipRect(0, 0, width, height)
        val d = data
        val r = raster
        val v = viewport
        if (d == null || r == null || v == null) {
            canvas.drawColor(Color.rgb(231, 237, 239))
            paint.color = Color.GRAY
            paint.textSize = 16 * resources.displayMetrics.scaledDensity
            canvas.drawText(
                if (d == null) "Select a radar scan" else "Rendering source data…",
                24f,
                height / 2f,
                paint,
            )
            return
        }
        RadarRaster.draw(
            canvas,
            width,
            height,
            d,
            r,
            v,
            if (d.spec.display.basemap == "osm") ::drawTiles else null,
        )
    }

    fun snapshot(): Bitmap {
        check(data != null && raster != null) { "Wait for a rendered frame" }
        return Bitmap.createBitmap(max(width, 1), max(height, 1), Bitmap.Config.ARGB_8888).also {
            RadarRaster.draw(
                Canvas(it),
                width,
                height,
                data!!,
                raster!!,
                viewport!!,
                if (data!!.spec.display.basemap == "osm") ::drawTiles else null,
                true,
            )
        }
    }

    private fun drawTiles(canvas: Canvas, view: Viewport, w: Int, h: Int) {
        val z = floor(view.zoom).toInt().coerceIn(0, 18)
        val scale = 2.0.pow(view.zoom - z)
        val world = 256 * 2.0.pow(view.zoom)
        val left = MapMath.x(view.longitude) * world - w / 2
        val top = MapMath.y(view.latitude) * world - h / 2
        val tileSize = 256 * scale
        val limit = 1 shl z
        for (y in floor(top / tileSize).toInt()..floor((top + h) / tileSize).toInt()) for (x in
            floor(left / tileSize).toInt()..floor((left + w) / tileSize).toInt()) if (
            y in 0 until limit
        ) {
            val tx = ((x % limit) + limit) % limit
            val key = "$z-$tx-$y"
            val b = tileMemory.get(key)
            if (b != null) {
                paint.alpha = 255
                paint.isFilterBitmap = true
                canvas.drawBitmap(
                    b,
                    null,
                    RectF(
                        (x * tileSize - left).toFloat(),
                        (y * tileSize - top).toFloat(),
                        ((x + 1) * tileSize - left).toFloat(),
                        ((y + 1) * tileSize - top).toFloat(),
                    ),
                    paint,
                )
            } else if (tileJobs.putIfAbsent(key, true) == null)
                scope.launch {
                    try {
                        val image =
                            withContext(Dispatchers.IO) {
                                val file = File(tilesDir, key + ".png")
                                if (
                                    file.exists() &&
                                        System.currentTimeMillis() - file.lastModified() <
                                            7L * 24 * 60 * 60 * 1000
                                )
                                    BitmapFactory.decodeFile(file.path)
                                else
                                    client
                                        .newCall(
                                            Request.Builder()
                                                .url("https://tile.openstreetmap.org/$z/$tx/$y.png")
                                                .header(
                                                    "User-Agent",
                                                    "UKWSRVisualizer-Android/${BuildConfig.VERSION_NAME} (https://github.com/rrniii/uk-wsr-visualizer)",
                                                )
                                                .build()
                                        )
                                        .execute()
                                        .use { response ->
                                            if (!response.isSuccessful) null
                                            else {
                                                val bytes = response.body.bytes()
                                                BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                                                    ?.also {
                                                        CatalogRepository.atomicWrite(file, bytes)
                                                    }
                                            }
                                        }
                            }
                        if (image != null) {
                            tileMemory.put(key, image)
                            invalidate()
                        }
                    } catch (_: Exception) {} finally {
                        tileJobs.remove(key)
                    }
                }
        }
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        detector.onTouchEvent(event)
        parent?.requestDisallowInterceptTouchEvent(true)
        when (event.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                downX = event.x
                downY = event.y
                lastX = event.x
                lastY = event.y
                dragging = false
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = event.x - lastX
                val dy = event.y - lastY
                if (hypot(event.x - downX, event.y - downY) > 8) dragging = true
                if (!detector.isInProgress && dragging)
                    viewport?.let { v ->
                        val scale = 256 * 2.0.pow(v.zoom)
                        viewport =
                            v.copy(
                                latitude = MapMath.lat(MapMath.y(v.latitude) - dy / scale),
                                longitude = MapMath.lon(MapMath.x(v.longitude) - dx / scale),
                            )
                        onViewport?.invoke(viewport!!)
                        invalidate()
                    }
                lastX = event.x
                lastY = event.y
            }
            MotionEvent.ACTION_UP -> {
                if (!dragging && !detector.isInProgress) identify(event.x, event.y)
                performClick()
                parent?.requestDisallowInterceptTouchEvent(false)
            }
            MotionEvent.ACTION_CANCEL -> parent?.requestDisallowInterceptTouchEvent(false)
        }
        return true
    }

    override fun performClick(): Boolean {
        super.performClick()
        return true
    }

    private fun identify(x: Float, y: Float) {
        val d = data ?: return
        val v = viewport ?: return
        val scale = 256 * 2.0.pow(v.zoom)
        val lat = MapMath.lat(MapMath.y(v.latitude) + (y - height / 2) / scale)
        val lon = MapMath.lon(MapMath.x(v.longitude) + (x - width / 2) / scale)
        val (range, az) = MapMath.rangeAz(d.field, lat, lon)
        val row = Geometry.rayAt(d.field, az)
        val col = floor((range - d.field.rstartKm * 1000) / d.field.rscaleM).toInt()
        if (row < 0 || col !in 0 until d.field.columns) {
            onIdentify?.invoke("Outside measured source coverage")
            return
        }
        val i = row * d.field.columns + col
        val state =
            when (d.field.sourceStates[i].toInt()) {
                1 -> "NODATA"
                2 -> "UNDETECT"
                3 -> "Nonfinite"
                else ->
                    if (d.values[i].isFinite()) "%.2f".format(d.values[i])
                    else "Masked (source %.2f)".format(d.field.values[i])
            }
        onIdentify?.invoke(
            "${d.field.quantity}: $state · %.1f km · %.1f° · %.4f, %.4f · beam %.0f m"
                .format(range / 1000, az, lat, lon, Geometry.beamHeight(d.field, range))
        )
    }

    fun release() {
        scope.cancel()
        client.dispatcher.cancelAll()
    }
}
