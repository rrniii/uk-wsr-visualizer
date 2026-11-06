package com.rrniii.ukwsrvisualizer

class NativeField {
    @JvmField var values = floatArrayOf()
    @JvmField var sourceStates = byteArrayOf()
    @JvmField var startAzimuths = doubleArrayOf()
    @JvmField var stopAzimuths = doubleArrayOf()
    @JvmField var rows = 0
    @JvmField var columns = 0
    @JvmField var measuredAzimuths = 0
    @JvmField var latitude = Double.NaN
    @JvmField var longitude = Double.NaN
    @JvmField var heightM = Double.NaN
    @JvmField var elevationDeg = Double.NaN
    @JvmField var rstartKm = 0.0
    @JvmField var rscaleM = 1000.0
    @JvmField var beamWidthDeg = 1.0
    @JvmField var dataset = ""
    @JvmField var quantity = ""
    val maxRangeM
        get() = rstartKm * 1000 + columns * rscaleM
}

data class FieldRecord(
    val dataset: String,
    val quantity: String,
    val rows: Int,
    val columns: Int,
    val elevation: Double,
) {
    val key
        get() = "$dataset/$quantity"

    val label
        get() = "$quantity · %.2f°".format(elevation)
}

object NativeBridge {
    init {
        System.loadLibrary("ukwsr")
    }

    @Synchronized
    fun inspect(path: String): List<FieldRecord> =
        inspectNative(path).map { line ->
            val p = line.split('\t')
            require(p.size == 5) { "Invalid native field metadata" }
            FieldRecord(p[0], p[1], p[2].toInt(), p[3].toInt(), p[4].toDoubleOrNull() ?: Double.NaN)
        }

    @Synchronized
    fun read(path: String, dataset: String = "", quantity: String = ""): NativeField =
        readNative(path, dataset, quantity)

    private external fun inspectNative(path: String): Array<String>

    private external fun readNative(path: String, dataset: String, quantity: String): NativeField
}
