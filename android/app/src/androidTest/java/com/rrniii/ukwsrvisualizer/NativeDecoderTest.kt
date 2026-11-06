package com.rrniii.ukwsrvisualizer

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import org.junit.*
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class NativeDecoderTest {
    @Test
    fun compressedOdimPreservesStatesAndMeasuredGeometry() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val file = File(instrumentation.targetContext.cacheDir, "native-contract.h5")
        instrumentation.context.assets.open("odim-states-rays.h5").use { input ->
            file.outputStream().use { input.copyTo(it) }
        }
        val before = fileHash(file)
        val records = NativeBridge.inspect(file.path)
        Assert.assertEquals(setOf("DBZH", "VRADH"), records.map { it.quantity }.toSet())
        val field = NativeBridge.read(file.path, "dataset1", "DBZH")
        Assert.assertEquals(4, field.rows)
        Assert.assertEquals(3, field.columns)
        Assert.assertEquals(2, field.sourceStates[0].toInt())
        Assert.assertEquals(1, field.sourceStates[1].toInt())
        Assert.assertTrue(field.values[0].isNaN())
        Assert.assertEquals(-31.5f, field.values[2], 0f)
        Assert.assertEquals(1, field.measuredAzimuths)
        Assert.assertArrayEquals(doubleArrayOf(10.0, 90.0, 190.0, 350.0), field.startAzimuths, 0.0)
        Assert.assertEquals(-1, Geometry.rayAt(field, 45.0))
        Assert.assertEquals(before, fileHash(file))
    }

    @Test
    fun invalidHdf5ReportsActualDecodeFailure() {
        val file =
            File(InstrumentationRegistry.getInstrumentation().targetContext.cacheDir, "broken.h5")
        file.writeText("not HDF5")
        try {
            NativeBridge.inspect(file.path)
            Assert.fail("Invalid HDF5 must fail")
        } catch (e: java.io.IOException) {
            Assert.assertTrue(e.message.orEmpty().contains("HDF5"))
        }
    }

    @Test
    fun malformedScalarAttributeArraysCannotOverwriteNativeMemory() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        fun copy(name: String): File =
            File(instrumentation.targetContext.cacheDir, name).also { file ->
                instrumentation.context.assets.open(name).use { input ->
                    file.outputStream().use { input.copyTo(it) }
                }
            }
        val gain = NativeBridge.read(copy("odim-gain-array.h5").path, "dataset1", "DBZH")
        Assert.assertEquals(
            -31f,
            gain.values[2],
            0f,
        ) // Invalid gain uses documented scalar fallback 1.
        try {
            NativeBridge.read(copy("odim-quantity-array.h5").path, "dataset1", "DBZH")
            Assert.fail("Array quantity must not be accepted as scalar")
        } catch (expected: java.io.IOException) {
            Assert.assertTrue(expected.message.orEmpty().contains("DBZH"))
        }
    }
}
