package dev.annati.il2cppdumper.dumper

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Declarative IL2CPP structure tables + reader.
 *
 * This is a Kotlin port of the Python dumper's `dumper/structs.py`.  Each field
 * carries a [minV]/[maxV] metadata-version window, mirroring the reference
 * `[Version(Min=x, Max=y)]` attribute system, so one table serves every version.
 *
 * On-device we run in *metadata* mode: names, flags and structure are recovered;
 * the native binary's type table is not analysed (see [DumpWriter]).
 */
object Structs {

    const val METADATA_SANITY = -89056337 // 0xFAB11BAF as a signed 32-bit int

    private const val U32 = 1
    private const val I32 = 2
    private const val U16 = 3
    private const val I16 = 4
    private const val U8 = 5
    private const val BYTES8 = 6

    class Field(val name: String, val kind: Int, val minV: Double = 0.0, val maxV: Double = 9999.0)
    fun f(name: String, kind: Int, minV: Double = 0.0, maxV: Double = 9999.0) = Field(name, kind, minV, maxV)

    val HEADER = arrayOf(
        f("sanity", U32), f("version", I32),
        f("stringLiteralOffset", U32), f("stringLiteralSize", I32),
        f("stringLiteralDataOffset", U32), f("stringLiteralDataSize", I32),
        f("stringOffset", U32), f("stringSize", I32),
        f("eventsOffset", U32), f("eventsSize", I32),
        f("propertiesOffset", U32), f("propertiesSize", I32),
        f("methodsOffset", U32), f("methodsSize", I32),
        f("parameterDefaultValuesOffset", U32), f("parameterDefaultValuesSize", I32),
        f("fieldDefaultValuesOffset", U32), f("fieldDefaultValuesSize", I32),
        f("fieldAndParameterDefaultValueDataOffset", U32), f("fieldAndParameterDefaultValueDataSize", I32),
        f("fieldMarshaledSizesOffset", I32), f("fieldMarshaledSizesSize", I32),
        f("parametersOffset", U32), f("parametersSize", I32),
        f("fieldsOffset", U32), f("fieldsSize", I32),
        f("genericParametersOffset", U32), f("genericParametersSize", I32),
        f("genericParameterConstraintsOffset", U32), f("genericParameterConstraintsSize", I32),
        f("genericContainersOffset", U32), f("genericContainersSize", I32),
        f("nestedTypesOffset", U32), f("nestedTypesSize", I32),
        f("interfacesOffset", U32), f("interfacesSize", I32),
        f("vtableMethodsOffset", U32), f("vtableMethodsSize", I32),
        f("interfaceOffsetsOffset", I32), f("interfaceOffsetsSize", I32),
        f("typeDefinitionsOffset", U32), f("typeDefinitionsSize", I32),
        f("rgctxEntriesOffset", U32, 0.0, 24.1), f("rgctxEntriesCount", I32, 0.0, 24.1),
        f("imagesOffset", U32), f("imagesSize", I32),
        f("assembliesOffset", U32), f("assembliesSize", I32),
        f("metadataUsageListsOffset", U32, 19.0, 24.5), f("metadataUsageListsCount", I32, 19.0, 24.5),
        f("metadataUsagePairsOffset", U32, 19.0, 24.5), f("metadataUsagePairsCount", I32, 19.0, 24.5),
        f("fieldRefsOffset", U32, 19.0), f("fieldRefsSize", I32, 19.0),
        f("referencedAssembliesOffset", I32, 20.0), f("referencedAssembliesSize", I32, 20.0),
        f("attributesInfoOffset", U32, 21.0, 27.2), f("attributesInfoCount", I32, 21.0, 27.2),
        f("attributeTypesOffset", U32, 21.0, 27.2), f("attributeTypesCount", I32, 21.0, 27.2),
        f("attributeDataOffset", U32, 29.0), f("attributeDataSize", I32, 29.0),
        f("attributeDataRangeOffset", U32, 29.0), f("attributeDataRangeSize", I32, 29.0),
        f("unresolvedVirtualCallParameterTypesOffset", I32, 22.0), f("unresolvedVirtualCallParameterTypesSize", I32, 22.0),
        f("unresolvedVirtualCallParameterRangesOffset", I32, 22.0), f("unresolvedVirtualCallParameterRangesSize", I32, 22.0),
        f("windowsRuntimeTypeNamesOffset", I32, 23.0), f("windowsRuntimeTypeNamesSize", I32, 23.0),
        f("windowsRuntimeStringsOffset", I32, 27.0), f("windowsRuntimeStringsSize", I32, 27.0),
        f("exportedTypeDefinitionsOffset", I32, 24.0), f("exportedTypeDefinitionsSize", I32, 24.0),
    )

    val IMAGE = arrayOf(
        f("nameIndex", U32), f("assemblyIndex", I32), f("typeStart", I32), f("typeCount", U32),
        f("exportedTypeStart", I32, 24.0), f("exportedTypeCount", U32, 24.0),
        f("entryPointIndex", I32), f("token", U32, 19.0),
        f("customAttributeStart", I32, 24.1), f("customAttributeCount", U32, 24.1),
    )

    val ASSEMBLY_NAME = arrayOf(
        f("nameIndex", U32), f("cultureIndex", U32), f("hashValueIndex", I32, 0.0, 24.3),
        f("publicKeyIndex", U32), f("hash_alg", U32), f("hash_len", I32), f("flags", U32),
        f("major", I32), f("minor", I32), f("build", I32), f("revision", I32),
        f("public_key_token", BYTES8),
    )

    val ASSEMBLY = arrayOf(
        f("imageIndex", I32), f("token", U32, 24.1), f("customAttributeIndex", I32, 0.0, 24.0),
        f("referencedAssemblyStart", I32, 20.0), f("referencedAssemblyCount", I32, 20.0),
        f("aname", I32), // marker - read inline as nested below
    )

    val TYPE_DEF = arrayOf(
        f("nameIndex", U32), f("namespaceIndex", U32), f("customAttributeIndex", I32, 0.0, 24.0),
        f("byvalTypeIndex", I32), f("byrefTypeIndex", I32, 0.0, 24.5),
        f("declaringTypeIndex", I32), f("parentIndex", I32), f("elementTypeIndex", I32),
        f("rgctxStartIndex", I32, 0.0, 24.1), f("rgctxCount", I32, 0.0, 24.1),
        f("genericContainerIndex", I32),
        f("delegateWrapperFromManagedToNativeIndex", I32, 0.0, 22.0),
        f("marshalingFunctionsIndex", I32, 0.0, 22.0),
        f("ccwFunctionIndex", I32, 21.0, 22.0), f("guidIndex", I32, 21.0, 22.0),
        f("flags", U32),
        f("fieldStart", I32), f("methodStart", I32), f("eventStart", I32), f("propertyStart", I32),
        f("nestedTypesStart", I32), f("interfacesStart", I32), f("vtableStart", I32), f("interfaceOffsetsStart", I32),
        f("method_count", U16), f("property_count", U16), f("field_count", U16), f("event_count", U16),
        f("nested_type_count", U16), f("vtable_count", U16), f("interfaces_count", U16), f("interface_offsets_count", U16),
        f("bitfield", U32), f("token", U32, 19.0),
    )

    val METHOD_DEF = arrayOf(
        f("nameIndex", U32), f("declaringType", I32), f("returnType", I32),
        f("returnParameterToken", I32, 31.0), f("parameterStart", I32),
        f("customAttributeIndex", I32, 0.0, 24.0), f("genericContainerIndex", I32),
        f("methodIndex", I32, 0.0, 24.1), f("invokerIndex", I32, 0.0, 24.1),
        f("delegateWrapperIndex", I32, 0.0, 24.1), f("rgctxStartIndex", I32, 0.0, 24.1),
        f("rgctxCount", I32, 0.0, 24.1), f("token", U32),
        f("flags", U16), f("iflags", U16), f("slot", U16), f("parameterCount", U16),
    )

    val PARAM_DEF = arrayOf(
        f("nameIndex", U32), f("token", U32), f("customAttributeIndex", I32, 0.0, 24.0), f("typeIndex", I32),
    )

    val FIELD_DEF = arrayOf(
        f("nameIndex", U32), f("typeIndex", I32), f("customAttributeIndex", I32, 0.0, 24.0), f("token", U32, 19.0),
    )

    val PROPERTY_DEF = arrayOf(
        f("nameIndex", U32), f("get", I32), f("set", I32), f("attrs", U32),
        f("customAttributeIndex", I32, 0.0, 24.0), f("token", U32, 19.0),
    )

    val EVENT_DEF = arrayOf(
        f("nameIndex", U32), f("typeIndex", I32), f("add", I32), f("remove", I32), f("raise", I32),
        f("customAttributeIndex", I32, 0.0, 24.0), f("token", U32, 19.0),
    )

    val GENERIC_CONTAINER = arrayOf(
        f("ownerIndex", I32), f("type_argc", I32), f("is_method", I32), f("genericParameterStart", I32),
    )

    val GENERIC_PARAMETER = arrayOf(
        f("ownerIndex", I32), f("nameIndex", U32), f("constraintsStart", I16), f("constraintsCount", I16),
        f("num", U16), f("flags", U16),
    )

    val STRING_LITERAL = arrayOf(f("length", U32), f("dataIndex", I32))

    fun sizeOf(table: Array<Field>, version: Double): Int {
        var size = 0
        for (field in table) {
            if (version < field.minV || version > field.maxV) continue
            size += kindSize(field.kind)
        }
        return size
    }

    private fun kindSize(kind: Int): Int = when (kind) {
        U8 -> 1; I16, U16 -> 2; BYTES8 -> 8; else -> 4
    }

    /** Read one struct at [offset] into an ordered map of name -> value. */
    fun read(buf: ByteBuffer, offset: Int, table: Array<Field>, version: Double): LinkedHashMap<String, Any> {
        val out = LinkedHashMap<String, Any>()
        buf.position(offset)
        for (field in table) {
            if (version < field.minV || version > field.maxV) continue
            out[field.name] = when (field.kind) {
                U32 -> buf.int.toLong() and 0xFFFFFFFFL
                I32 -> buf.int.toLong()
                U16 -> (buf.short.toInt() and 0xFFFF).toLong()
                I16 -> buf.short.toInt().toLong()
                U8 -> (buf.get().toInt() and 0xFF).toLong()
                BYTES8 -> {
                    val b = ByteArray(8); buf.get(b); b
                }
                else -> 0L
            }
        }
        return out
    }

    fun readArray(buf: ByteBuffer, offset: Int, sizeOrCount: Int, table: Array<Field>,
                  version: Double, byCount: Boolean = false): List<LinkedHashMap<String, Any>> {
        if (offset <= 0 || sizeOrCount <= 0) return emptyList()
        val unit = sizeOf(table, version)
        if (unit == 0) return emptyList()
        val count = if (byCount) sizeOrCount else sizeOrCount / unit
        val out = ArrayList<LinkedHashMap<String, Any>>(count.coerceAtMost(2_000_000))
        for (i in 0 until count) {
            out.add(read(buf, offset + i * unit, table, version))
        }
        return out
    }

    fun intArray(buf: ByteBuffer, offset: Int, size: Int): IntArray {
        if (offset <= 0 || size <= 0) return IntArray(0)
        val count = size / 4
        buf.position(offset)
        val out = IntArray(count)
        for (i in 0 until count) out[i] = buf.int
        return out
    }

    fun little(data: ByteArray): ByteBuffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
}
