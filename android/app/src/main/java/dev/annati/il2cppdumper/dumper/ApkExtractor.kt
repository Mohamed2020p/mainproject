package dev.annati.il2cppdumper.dumper

import java.io.File
import java.util.zip.ZipFile

/**
 * Pulls `libil2cpp.so` and `global-metadata.dat` out of an APK / XAPK / AAB.
 *
 * Developed by Mohamed Annati.
 */
object ApkExtractor {

    private val ABI_ORDER = listOf("arm64-v8a", "armeabi-v7a", "x86_64", "x86")

    data class Pair(val binary: File?, val metadata: File?, val abi: String?)

    fun extract(apkPath: String, cacheDir: File): Pair {
        val so = HashMap<String, String>()
        var metadataEntry: String? = null

        ZipFile(apkPath).use { zip ->
            val entries = zip.entries()
            while (entries.hasMoreElements()) {
                val entry = entries.nextElement()
                if (entry.isDirectory) continue
                val lower = entry.name.lowercase()
                val base = lower.substringAfterLast('/')
                if (metadataEntry == null && base == "global-metadata.dat") {
                    metadataEntry = entry.name
                }
                if (base == "libil2cpp.so" && lower.count { it == '/' } >= 2) {
                    val abi = lower.split("/")[1]
                    so.putIfAbsent(abi, entry.name)
                }
            }

            if (metadataEntry == null || so.isEmpty()) {
                throw IllegalArgumentException(
                    "No libil2cpp.so / global-metadata.dat inside this archive.")
            }

            val abi = ABI_ORDER.firstOrNull { so.containsKey(it) } ?: so.keys.first()
            val outDir = File(cacheDir, "extracted").apply { mkdirs() }

            val soFile = copyEntry(zip, so[abi]!!, File(outDir, "libil2cpp.so"))
            val datFile = copyEntry(zip, metadataEntry!!, File(outDir, "global-metadata.dat"))
            return Pair(soFile, datFile, abi)
        }
    }

    private fun copyEntry(zip: ZipFile, name: String, dest: File): File {
        zip.getInputStream(zip.getEntry(name)).use { input ->
            dest.outputStream().use { input.copyTo(it) }
        }
        return dest
    }
}
