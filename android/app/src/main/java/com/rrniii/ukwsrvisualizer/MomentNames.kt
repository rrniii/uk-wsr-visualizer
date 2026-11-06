package com.rrniii.ukwsrvisualizer

/** Names accepted by the existing mobile cleanup contract. Source names stay unchanged. */
object MomentNames {
    private val groups =
        mapOf(
            "DBZH" to
                listOf("DBZH", "DBZ", "DBZV", "DBZHC", "DBZVC", "TH", "TV", "CZ", "DZ", "AZ", "Z"),
            "CI" to listOf("CI", "APD", "CLUTTER_INDICATOR"),
            "SQIH" to listOf("SQIH", "SQI", "QIND"),
            "RHOHV" to listOf("RHOHV", "RHO", "CC"),
            "ZDR" to listOf("ZDR", "ZDRH", "ZDRV"),
            "PHIDP" to listOf("PHIDP", "UPHIDP", "PHI"),
            "VRADH" to listOf("VRADH", "VRADDH", "VRAD", "VRADV", "VEL", "VELH", "VELV"),
            "WRADH" to listOf("WRADH", "WRAD", "WRADV", "WIDTH", "SW", "SWRAD"),
        )

    fun reflectivity(quantity: String) =
        quantity.trim().uppercase() in groups.getValue("DBZH") ||
            quantity.contains("reflectivity", ignoreCase = true)

    fun canonicalFields(fields: Map<String, FloatArray>): Map<String, FloatArray> {
        val normalized = fields.mapKeys { it.key.trim().uppercase() }
        return groups
            .mapNotNull { (key, aliases) ->
                aliases.firstNotNullOfOrNull { normalized[it] }?.let { key to it }
            }
            .toMap()
    }

    fun companionValues(source: NativeField, selected: NativeField): FloatArray? {
        if (
            source.rows != selected.rows ||
                !source.startAzimuths.contentEquals(selected.startAzimuths) ||
                !source.stopAzimuths.contentEquals(selected.stopAzimuths)
        )
            return null
        return when {
            source.columns == selected.columns -> source.values
            source.columns == 1 && source.values.size == source.rows ->
                FloatArray(selected.rows * selected.columns) {
                    source.values[it / selected.columns]
                }
            else -> null
        }
    }
}
