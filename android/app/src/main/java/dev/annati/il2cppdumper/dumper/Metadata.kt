package dev.annati.il2cppdumper.dumper

import java.io.File

/**
 * Parsed `global-metadata.dat` (metadata mode).
 *
 * Developed by Mohamed Annati.
 */
class Metadata(data: ByteArray) {

    private val buf = Structs.little(data)
    var version: Double
    var header: Map<String, Any>

    val imageDefs: List<Map<String, Any>>
    val typeDefs: List<Map<String, Any>>
    val methodDefs: List<Map<String, Any>>
    val parameterDefs: List<Map<String, Any>>
    val fieldDefs: List<Map<String, Any>>
    val propertyDefs: List<Map<String, Any>>
    val eventDefs: List<Map<String, Any>>
    val genericContainers: List<Map<String, Any>>
    val genericParameters: List<Map<String, Any>>
    val stringLiterals: List<Map<String, Any>>
    val interfaceIndices: IntArray
    val nestedTypeIndices: IntArray

    private val stringCache = HashMap<Long, String>()

    init {
        val sanity = buf.getInt(0)
        if (sanity != Structs.METADATA_SANITY) {
            throw IllegalArgumentException(
                "Not a valid global-metadata.dat (bad magic). It may be encrypted.")
        }
        var v = buf.getInt(4)
        if (v < 16 || v > 31) throw IllegalArgumentException("Unsupported metadata version $v")
        version = v.toDouble()

        header = Structs.read(buf, 0, Structs.HEADER, version)

        if (v == 24) {
            val slOffset = l("stringLiteralOffset")
            if (slOffset == 264L) {
                version = 24.2
            } else {
                val images = readImages(24.0)
                if (images.any { (it["token"] as Long) != 1L }) version = 24.1
            }
            // HEADER layout is version-gated - re-read with the resolved version.
            header = Structs.read(buf, 0, Structs.HEADER, version)
        }

        imageDefs = readImages(version)

        typeDefs = Structs.readArray(buf, l("typeDefinitionsOffset").toInt(),
            l("typeDefinitionsSize").toInt(), Structs.TYPE_DEF, version)
        methodDefs = Structs.readArray(buf, l("methodsOffset").toInt(),
            l("methodsSize").toInt(), Structs.METHOD_DEF, version)
        parameterDefs = Structs.readArray(buf, l("parametersOffset").toInt(),
            l("parametersSize").toInt(), Structs.PARAM_DEF, version)
        fieldDefs = Structs.readArray(buf, l("fieldsOffset").toInt(),
            l("fieldsSize").toInt(), Structs.FIELD_DEF, version)
        propertyDefs = Structs.readArray(buf, l("propertiesOffset").toInt(),
            l("propertiesSize").toInt(), Structs.PROPERTY_DEF, version)
        eventDefs = Structs.readArray(buf, l("eventsOffset").toInt(),
            l("eventsSize").toInt(), Structs.EVENT_DEF, version)
        genericContainers = Structs.readArray(buf, l("genericContainersOffset").toInt(),
            l("genericContainersSize").toInt(), Structs.GENERIC_CONTAINER, version)
        genericParameters = Structs.readArray(buf, l("genericParametersOffset").toInt(),
            l("genericParametersSize").toInt(), Structs.GENERIC_PARAMETER, version)
        stringLiterals = Structs.readArray(buf, l("stringLiteralOffset").toInt(),
            l("stringLiteralSize").toInt(), Structs.STRING_LITERAL, version)

        interfaceIndices = Structs.intArray(buf, l("interfacesOffset").toInt(), l("interfacesSize").toInt())
        nestedTypeIndices = Structs.intArray(buf, l("nestedTypesOffset").toInt(), l("nestedTypesSize").toInt())
    }

    private fun readImages(v: Double) = Structs.readArray(
        buf, (lAt(v, "imagesOffset")).toInt(), (lAt(v, "imagesSize")).toInt(), Structs.IMAGE, v)

    private fun l(key: String): Long = header[key] as? Long ?: 0L
    private fun lAt(v: Double, key: String): Long {
        val h = Structs.read(buf, 0, Structs.HEADER, v)
        return h[key] as? Long ?: 0L
    }

    fun string(index: Long): String {
        stringCache[index]?.let { return it }
        val start = (l("stringOffset") + index).toInt()
        val end = indexOfZero(start)
        val value = String(buf.array(), start, (end - start).coerceAtLeast(0), Charsets.UTF_8)
        stringCache[index] = value
        return value
    }

    fun stringLiteral(index: Int): String {
        val literal = stringLiterals[index]
        val length = (literal["length"] as Long).toInt()
        val dataIndex = (literal["dataIndex"] as Long).toInt()
        val start = (l("stringLiteralDataOffset") + dataIndex).toInt()
        return String(buf.array(), start, length.coerceAtMost(buf.limit() - start), Charsets.UTF_8)
    }

    private fun indexOfZero(from: Int): Int {
        val arr = buf.array()
        var i = from
        while (i < arr.size && arr[i].toInt() != 0) i++
        return i
    }

    val typeName: (Map<String, Any>) -> String = { typeDef ->
        val prefix = if ((typeDef["namespaceIndex"] as Long) != 0L)
            string(typeDef["namespaceIndex"] as Long) + "." else ""
        prefix + string(typeDef["nameIndex"] as Long)
    }

    fun summary(): Map<String, Int> = mapOf(
        "images" to imageDefs.size,
        "types" to typeDefs.size,
        "methods" to methodDefs.size,
        "fields" to fieldDefs.size,
        "properties" to propertyDefs.size,
        "events" to eventDefs.size,
        "stringLiterals" to stringLiterals.size,
    )

    companion object {
        fun fromFile(path: String): Metadata = Metadata(File(path).readBytes())
    }
}
