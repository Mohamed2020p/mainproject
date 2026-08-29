"""
Declarative description of every native IL2CPP structure that the dumper has to
read.

IL2CPP changes the layout of these structures between Unity releases, so every
field carries an optional ``vmin`` / ``vmax`` pair (inclusive) describing the
range of metadata versions it exists in.  This mirrors the ``[Version(Min=x,
Max=y)]`` attribute system used by the original C# Il2CppDumper and lets a
single table serve every supported version (16 .. 31).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Primitive codes
# ---------------------------------------------------------------------------

U8 = "u8"
U16 = "u16"
U32 = "u32"
U64 = "u64"
I8 = "i8"
I16 = "i16"
I32 = "i32"
I64 = "i64"
F32 = "f32"
F64 = "f64"
PTR = "ptr"          # pointer sized: 4 bytes on 32-bit images, 8 on 64-bit
IPTR = "iptr"        # signed pointer sized
BYTES = "bytes"      # raw byte blob, needs a fixed length

PRIMITIVE_SIZE = {
    U8: 1, I8: 1,
    U16: 2, I16: 2,
    U32: 4, I32: 4, F32: 4,
    U64: 8, I64: 8, F64: 8,
}


@dataclass(frozen=True)
class Field:
    """One member of a native struct."""

    name: str
    kind: str                                  # primitive code | struct name | "bytes"
    count: int = 1                             # array length (only for BYTES)
    vmin: float = 0.0
    vmax: float = 9999.0

    def active(self, version: float) -> bool:
        return self.vmin <= version <= self.vmax


Struct = Tuple[Field, ...]


def _f(name: str, kind: str, count: int = 1,
       vmin: float = 0.0, vmax: float = 9999.0) -> Field:
    return Field(name, kind, count, vmin, vmax)


# ---------------------------------------------------------------------------
# global-metadata.dat
# ---------------------------------------------------------------------------

GLOBAL_METADATA_HEADER: Struct = (
    _f("sanity", U32),
    _f("version", I32),
    _f("stringLiteralOffset", U32),
    _f("stringLiteralSize", I32),
    _f("stringLiteralDataOffset", U32),
    _f("stringLiteralDataSize", I32),
    _f("stringOffset", U32),
    _f("stringSize", I32),
    _f("eventsOffset", U32),
    _f("eventsSize", I32),
    _f("propertiesOffset", U32),
    _f("propertiesSize", I32),
    _f("methodsOffset", U32),
    _f("methodsSize", I32),
    _f("parameterDefaultValuesOffset", U32),
    _f("parameterDefaultValuesSize", I32),
    _f("fieldDefaultValuesOffset", U32),
    _f("fieldDefaultValuesSize", I32),
    _f("fieldAndParameterDefaultValueDataOffset", U32),
    _f("fieldAndParameterDefaultValueDataSize", I32),
    _f("fieldMarshaledSizesOffset", I32),
    _f("fieldMarshaledSizesSize", I32),
    _f("parametersOffset", U32),
    _f("parametersSize", I32),
    _f("fieldsOffset", U32),
    _f("fieldsSize", I32),
    _f("genericParametersOffset", U32),
    _f("genericParametersSize", I32),
    _f("genericParameterConstraintsOffset", U32),
    _f("genericParameterConstraintsSize", I32),
    _f("genericContainersOffset", U32),
    _f("genericContainersSize", I32),
    _f("nestedTypesOffset", U32),
    _f("nestedTypesSize", I32),
    _f("interfacesOffset", U32),
    _f("interfacesSize", I32),
    _f("vtableMethodsOffset", U32),
    _f("vtableMethodsSize", I32),
    _f("interfaceOffsetsOffset", I32),
    _f("interfaceOffsetsSize", I32),
    _f("typeDefinitionsOffset", U32),
    _f("typeDefinitionsSize", I32),
    _f("rgctxEntriesOffset", U32, vmax=24.1),
    _f("rgctxEntriesCount", I32, vmax=24.1),
    _f("imagesOffset", U32),
    _f("imagesSize", I32),
    _f("assembliesOffset", U32),
    _f("assembliesSize", I32),
    _f("metadataUsageListsOffset", U32, vmin=19, vmax=24.5),
    _f("metadataUsageListsCount", I32, vmin=19, vmax=24.5),
    _f("metadataUsagePairsOffset", U32, vmin=19, vmax=24.5),
    _f("metadataUsagePairsCount", I32, vmin=19, vmax=24.5),
    _f("fieldRefsOffset", U32, vmin=19),
    _f("fieldRefsSize", I32, vmin=19),
    _f("referencedAssembliesOffset", I32, vmin=20),
    _f("referencedAssembliesSize", I32, vmin=20),
    _f("attributesInfoOffset", U32, vmin=21, vmax=27.2),
    _f("attributesInfoCount", I32, vmin=21, vmax=27.2),
    _f("attributeTypesOffset", U32, vmin=21, vmax=27.2),
    _f("attributeTypesCount", I32, vmin=21, vmax=27.2),
    _f("attributeDataOffset", U32, vmin=29),
    _f("attributeDataSize", I32, vmin=29),
    _f("attributeDataRangeOffset", U32, vmin=29),
    _f("attributeDataRangeSize", I32, vmin=29),
    _f("unresolvedVirtualCallParameterTypesOffset", I32, vmin=22),
    _f("unresolvedVirtualCallParameterTypesSize", I32, vmin=22),
    _f("unresolvedVirtualCallParameterRangesOffset", I32, vmin=22),
    _f("unresolvedVirtualCallParameterRangesSize", I32, vmin=22),
    _f("windowsRuntimeTypeNamesOffset", I32, vmin=23),
    _f("windowsRuntimeTypeNamesSize", I32, vmin=23),
    _f("windowsRuntimeStringsOffset", I32, vmin=27),
    _f("windowsRuntimeStringsSize", I32, vmin=27),
    _f("exportedTypeDefinitionsOffset", I32, vmin=24),
    _f("exportedTypeDefinitionsSize", I32, vmin=24),
)

ASSEMBLY_NAME_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("cultureIndex", U32),
    _f("hashValueIndex", I32, vmax=24.3),
    _f("publicKeyIndex", U32),
    _f("hash_alg", U32),
    _f("hash_len", I32),
    _f("flags", U32),
    _f("major", I32),
    _f("minor", I32),
    _f("build", I32),
    _f("revision", I32),
    _f("public_key_token", BYTES, count=8),
)

ASSEMBLY_DEFINITION: Struct = (
    _f("imageIndex", I32),
    _f("token", U32, vmin=24.1),
    _f("customAttributeIndex", I32, vmax=24),
    _f("referencedAssemblyStart", I32, vmin=20),
    _f("referencedAssemblyCount", I32, vmin=20),
    _f("aname", "ASSEMBLY_NAME_DEFINITION"),
)

IMAGE_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("assemblyIndex", I32),
    _f("typeStart", I32),
    _f("typeCount", U32),
    _f("exportedTypeStart", I32, vmin=24),
    _f("exportedTypeCount", U32, vmin=24),
    _f("entryPointIndex", I32),
    _f("token", U32, vmin=19),
    _f("customAttributeStart", I32, vmin=24.1),
    _f("customAttributeCount", U32, vmin=24.1),
)

TYPE_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("namespaceIndex", U32),
    _f("customAttributeIndex", I32, vmax=24),
    _f("byvalTypeIndex", I32),
    _f("byrefTypeIndex", I32, vmax=24.5),
    _f("declaringTypeIndex", I32),
    _f("parentIndex", I32),
    _f("elementTypeIndex", I32),
    _f("rgctxStartIndex", I32, vmax=24.1),
    _f("rgctxCount", I32, vmax=24.1),
    _f("genericContainerIndex", I32),
    _f("delegateWrapperFromManagedToNativeIndex", I32, vmax=22),
    _f("marshalingFunctionsIndex", I32, vmax=22),
    _f("ccwFunctionIndex", I32, vmin=21, vmax=22),
    _f("guidIndex", I32, vmin=21, vmax=22),
    _f("flags", U32),
    _f("fieldStart", I32),
    _f("methodStart", I32),
    _f("eventStart", I32),
    _f("propertyStart", I32),
    _f("nestedTypesStart", I32),
    _f("interfacesStart", I32),
    _f("vtableStart", I32),
    _f("interfaceOffsetsStart", I32),
    _f("method_count", U16),
    _f("property_count", U16),
    _f("field_count", U16),
    _f("event_count", U16),
    _f("nested_type_count", U16),
    _f("vtable_count", U16),
    _f("interfaces_count", U16),
    _f("interface_offsets_count", U16),
    _f("bitfield", U32),
    _f("token", U32, vmin=19),
)

METHOD_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("declaringType", I32),
    _f("returnType", I32),
    _f("returnParameterToken", I32, vmin=31),
    _f("parameterStart", I32),
    _f("customAttributeIndex", I32, vmax=24),
    _f("genericContainerIndex", I32),
    _f("methodIndex", I32, vmax=24.1),
    _f("invokerIndex", I32, vmax=24.1),
    _f("delegateWrapperIndex", I32, vmax=24.1),
    _f("rgctxStartIndex", I32, vmax=24.1),
    _f("rgctxCount", I32, vmax=24.1),
    _f("token", U32),
    _f("flags", U16),
    _f("iflags", U16),
    _f("slot", U16),
    _f("parameterCount", U16),
)

PARAMETER_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("token", U32),
    _f("customAttributeIndex", I32, vmax=24),
    _f("typeIndex", I32),
)

FIELD_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("typeIndex", I32),
    _f("customAttributeIndex", I32, vmax=24),
    _f("token", U32, vmin=19),
)

FIELD_DEFAULT_VALUE: Struct = (
    _f("fieldIndex", I32),
    _f("typeIndex", I32),
    _f("dataIndex", I32),
)

PARAMETER_DEFAULT_VALUE: Struct = (
    _f("parameterIndex", I32),
    _f("typeIndex", I32),
    _f("dataIndex", I32),
)

PROPERTY_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("get", I32),
    _f("set", I32),
    _f("attrs", U32),
    _f("customAttributeIndex", I32, vmax=24),
    _f("token", U32, vmin=19),
)

EVENT_DEFINITION: Struct = (
    _f("nameIndex", U32),
    _f("typeIndex", I32),
    _f("add", I32),
    _f("remove", I32),
    _f("raise", I32),
    _f("customAttributeIndex", I32, vmax=24),
    _f("token", U32, vmin=19),
)

GENERIC_CONTAINER: Struct = (
    _f("ownerIndex", I32),
    _f("type_argc", I32),
    _f("is_method", I32),
    _f("genericParameterStart", I32),
)

GENERIC_PARAMETER: Struct = (
    _f("ownerIndex", I32),
    _f("nameIndex", U32),
    _f("constraintsStart", I16),
    _f("constraintsCount", I16),
    _f("num", U16),
    _f("flags", U16),
)

FIELD_REF: Struct = (
    _f("typeIndex", I32),
    _f("fieldIndex", I32),
)

STRING_LITERAL: Struct = (
    _f("length", U32),
    _f("dataIndex", I32),
)

METADATA_USAGE_LIST: Struct = (
    _f("start", U32),
    _f("count", U32),
)

METADATA_USAGE_PAIR: Struct = (
    _f("destinationIndex", U32),
    _f("encodedSourceIndex", U32),
)

CUSTOM_ATTRIBUTE_TYPE_RANGE: Struct = (
    _f("token", U32, vmin=24.1),
    _f("start", I32),
    _f("count", I32),
)

CUSTOM_ATTRIBUTE_DATA_RANGE: Struct = (
    _f("token", U32),
    _f("startOffset", U32),
)

RGCTX_DEFINITION: Struct = (
    _f("type_pre29", I32, vmax=27.1),
    _f("type_post29", U64, vmin=29),
    _f("data", I32, vmax=27.1),
    _f("_data", U64, vmin=27.2),
)

# ---------------------------------------------------------------------------
# libil2cpp.so / GameAssembly.dll
# ---------------------------------------------------------------------------

CODE_REGISTRATION: Struct = (
    _f("methodPointersCount", IPTR, vmax=24.1),
    _f("methodPointers", PTR, vmax=24.1),
    _f("delegateWrappersFromNativeToManagedCount", PTR, vmax=21),
    _f("delegateWrappersFromNativeToManaged", PTR, vmax=21),
    _f("reversePInvokeWrapperCount", PTR, vmin=22),
    _f("reversePInvokeWrappers", PTR, vmin=22),
    _f("delegateWrappersFromManagedToNativeCount", PTR, vmax=22),
    _f("delegateWrappersFromManagedToNative", PTR, vmax=22),
    _f("marshalingFunctionsCount", PTR, vmax=22),
    _f("marshalingFunctions", PTR, vmax=22),
    _f("ccwMarshalingFunctionsCount", PTR, vmin=21, vmax=22),
    _f("ccwMarshalingFunctions", PTR, vmin=21, vmax=22),
    _f("genericMethodPointersCount", PTR),
    _f("genericMethodPointers", PTR),
    _f("genericAdjustorThunks", PTR, vmin=24.5, vmax=24.5),
    _f("genericAdjustorThunks2", PTR, vmin=27.1),
    _f("invokerPointersCount", PTR),
    _f("invokerPointers", PTR),
    _f("customAttributeCount", PTR, vmax=24.5),
    _f("customAttributeGenerators", PTR, vmax=24.5),
    _f("guidCount", PTR, vmin=21, vmax=22),
    _f("guids", PTR, vmin=21, vmax=22),
    _f("unresolvedVirtualCallCount", PTR, vmin=22),
    _f("unresolvedVirtualCallPointers", PTR, vmin=22),
    _f("unresolvedInstanceCallPointers", PTR, vmin=29.1),
    _f("unresolvedStaticCallPointers", PTR, vmin=29.1),
    _f("interopDataCount", PTR, vmin=23),
    _f("interopData", PTR, vmin=23),
    _f("windowsRuntimeFactoryCount", PTR, vmin=24.3),
    _f("windowsRuntimeFactoryTable", PTR, vmin=24.3),
    _f("codeGenModulesCount", PTR, vmin=24.2),
    _f("codeGenModules", PTR, vmin=24.2),
)

METADATA_REGISTRATION: Struct = (
    _f("genericClassesCount", IPTR),
    _f("genericClasses", PTR),
    _f("genericInstsCount", IPTR),
    _f("genericInsts", PTR),
    _f("genericMethodTableCount", IPTR),
    _f("genericMethodTable", PTR),
    _f("typesCount", IPTR),
    _f("types", PTR),
    _f("methodSpecsCount", IPTR),
    _f("methodSpecs", PTR),
    _f("methodReferencesCount", IPTR, vmax=16),
    _f("methodReferences", PTR, vmax=16),
    _f("fieldOffsetsCount", IPTR),
    _f("fieldOffsets", PTR),
    _f("typeDefinitionsSizesCount", IPTR),
    _f("typeDefinitionsSizes", PTR),
    _f("metadataUsagesCount", PTR, vmin=19),
    _f("metadataUsages", PTR, vmin=19),
)

IL2CPP_TYPE: Struct = (
    _f("datapoint", PTR),
    _f("bits", U32),
)

GENERIC_CLASS: Struct = (
    _f("typeDefinitionIndex", IPTR, vmax=24.5),
    _f("type", PTR, vmin=27),
    _f("class_inst", PTR),
    _f("method_inst", PTR),
    _f("cached_class", PTR),
)

GENERIC_INST: Struct = (
    _f("type_argc", IPTR),
    _f("type_argv", PTR),
)

ARRAY_TYPE: Struct = (
    _f("etype", PTR),
    _f("rank", U8),
    _f("numsizes", U8),
    _f("numlobounds", U8),
    _f("sizes", PTR),
    _f("lobounds", PTR),
)

GENERIC_METHOD_INDICES: Struct = (
    _f("methodIndex", I32),
    _f("invokerIndex", I32),
    _f("adjustorThunk", I32, vmin=24.5, vmax=24.5),
    _f("adjustorThunk2", I32, vmin=27.1),
)

GENERIC_METHOD_FUNCTIONS_DEFINITIONS: Struct = (
    _f("genericMethodIndex", I32),
    _f("indices", "GENERIC_METHOD_INDICES"),
)

METHOD_SPEC: Struct = (
    _f("methodDefinitionIndex", I32),
    _f("classIndexIndex", I32),
    _f("methodIndexIndex", I32),
)

CODEGEN_MODULE: Struct = (
    _f("moduleName", PTR),
    _f("methodPointerCount", IPTR),
    _f("methodPointers", PTR),
    _f("adjustorThunkCount", IPTR, vmin=24.5, vmax=24.5),
    _f("adjustorThunks", PTR, vmin=24.5, vmax=24.5),
    _f("adjustorThunkCount2", IPTR, vmin=27.1),
    _f("adjustorThunks2", PTR, vmin=27.1),
    _f("invokerIndices", PTR),
    _f("reversePInvokeWrapperCount", PTR),
    _f("reversePInvokeWrapperIndices", PTR),
    _f("rgctxRangesCount", IPTR),
    _f("rgctxRanges", PTR),
    _f("rgctxsCount", IPTR),
    _f("rgctxs", PTR),
    _f("debuggerMetadata", PTR),
    _f("customAttributeCacheGenerator", PTR, vmin=27, vmax=27.2),
    _f("moduleInitializer", PTR, vmin=27),
    _f("staticConstructorTypeIndices", PTR, vmin=27),
    _f("metadataRegistration", PTR, vmin=27),
    _f("codeRegistaration", PTR, vmin=27),
)

RANGE: Struct = (
    _f("start", I32),
    _f("length", I32),
)

TOKEN_RANGE_PAIR: Struct = (
    _f("token", U32),
    _f("range", "RANGE"),
)


# Registry so that nested structs can be referenced by name.
REGISTRY: Dict[str, Struct] = {
    "GLOBAL_METADATA_HEADER": GLOBAL_METADATA_HEADER,
    "ASSEMBLY_NAME_DEFINITION": ASSEMBLY_NAME_DEFINITION,
    "ASSEMBLY_DEFINITION": ASSEMBLY_DEFINITION,
    "IMAGE_DEFINITION": IMAGE_DEFINITION,
    "TYPE_DEFINITION": TYPE_DEFINITION,
    "METHOD_DEFINITION": METHOD_DEFINITION,
    "PARAMETER_DEFINITION": PARAMETER_DEFINITION,
    "FIELD_DEFINITION": FIELD_DEFINITION,
    "FIELD_DEFAULT_VALUE": FIELD_DEFAULT_VALUE,
    "PARAMETER_DEFAULT_VALUE": PARAMETER_DEFAULT_VALUE,
    "PROPERTY_DEFINITION": PROPERTY_DEFINITION,
    "EVENT_DEFINITION": EVENT_DEFINITION,
    "GENERIC_CONTAINER": GENERIC_CONTAINER,
    "GENERIC_PARAMETER": GENERIC_PARAMETER,
    "FIELD_REF": FIELD_REF,
    "STRING_LITERAL": STRING_LITERAL,
    "METADATA_USAGE_LIST": METADATA_USAGE_LIST,
    "METADATA_USAGE_PAIR": METADATA_USAGE_PAIR,
    "CUSTOM_ATTRIBUTE_TYPE_RANGE": CUSTOM_ATTRIBUTE_TYPE_RANGE,
    "CUSTOM_ATTRIBUTE_DATA_RANGE": CUSTOM_ATTRIBUTE_DATA_RANGE,
    "RGCTX_DEFINITION": RGCTX_DEFINITION,
    "CODE_REGISTRATION": CODE_REGISTRATION,
    "METADATA_REGISTRATION": METADATA_REGISTRATION,
    "IL2CPP_TYPE": IL2CPP_TYPE,
    "GENERIC_CLASS": GENERIC_CLASS,
    "GENERIC_INST": GENERIC_INST,
    "ARRAY_TYPE": ARRAY_TYPE,
    "GENERIC_METHOD_INDICES": GENERIC_METHOD_INDICES,
    "GENERIC_METHOD_FUNCTIONS_DEFINITIONS": GENERIC_METHOD_FUNCTIONS_DEFINITIONS,
    "METHOD_SPEC": METHOD_SPEC,
    "CODEGEN_MODULE": CODEGEN_MODULE,
    "RANGE": RANGE,
    "TOKEN_RANGE_PAIR": TOKEN_RANGE_PAIR,
}


def struct_size(name: str, version: float, ptr_size: int = 8) -> int:
    """Byte size of ``name`` for a given metadata version / pointer width."""
    size = 0
    for field in REGISTRY[name]:
        if not field.active(version):
            continue
        if field.kind == BYTES:
            size += field.count
        elif field.kind == PTR:
            size += ptr_size
        elif field.kind == IPTR:
            size += ptr_size
        elif field.kind in REGISTRY:
            size += struct_size(field.kind, version, ptr_size)
        else:
            size += PRIMITIVE_SIZE[field.kind]
    return size


def read_struct(data: bytes, offset: int, name: str, version: float,
                ptr_size: int = 8) -> Dict[str, Any]:
    """Decode one instance of struct ``name`` located at ``offset``."""
    out: Dict[str, Any] = {}
    pos = offset
    end = len(data)
    for field in REGISTRY[name]:
        if not field.active(version):
            continue
        kind = field.kind
        if kind == BYTES:
            out[field.name] = data[pos:pos + field.count]
            pos += field.count
        elif kind == PTR:
            out[field.name] = _uint(data, pos, ptr_size)
            pos += ptr_size
        elif kind == IPTR:
            v = _uint(data, pos, ptr_size)
            out[field.name] = _sign(v, ptr_size * 8)
            pos += ptr_size
        elif kind in REGISTRY:
            sz = struct_size(kind, version, ptr_size)
            out[field.name] = read_struct(data, pos, kind, version, ptr_size)
            pos += sz
        else:
            sz = PRIMITIVE_SIZE[kind]
            v = _uint(data, pos, sz)
            if kind in (I8, I16, I32, I64):
                v = _sign(v, sz * 8)
            elif kind == F32:
                import struct as _s
                v = _s.unpack("<f", data[pos:pos + 4])[0]
            elif kind == F64:
                import struct as _s
                v = _s.unpack("<d", data[pos:pos + 8])[0]
            out[field.name] = v
            pos += sz
        if pos > end:
            raise EOFError(
                f"struct {name}: read past end of buffer at {field.name}"
            )
    return out


def read_struct_array(data: bytes, offset: int, name: str, count: int,
                      version: float, ptr_size: int = 8
                      ) -> List[Dict[str, Any]]:
    if count <= 0:
        return []
    size = struct_size(name, version, ptr_size)
    out = []
    for i in range(count):
        out.append(read_struct(data, offset + i * size, name, version, ptr_size))
    return out


def _uint(data: bytes, offset: int, size: int) -> int:
    return int.from_bytes(data[offset:offset + size], "little")


def _sign(value: int, bits: int) -> int:
    if value >= (1 << (bits - 1)):
        value -= (1 << bits)
    return value


# ---------------------------------------------------------------------------
# Writer side (used by the test fixture generator and by tools that need to
# re-serialise metadata, e.g. after editing names in place).
# ---------------------------------------------------------------------------
def pack_struct(values: Dict[str, Any], name: str, version: float,
                ptr_size: int = 8) -> bytes:
    """Encode ``values`` into the byte layout of struct ``name``."""
    out = bytearray()
    for field in REGISTRY[name]:
        if not field.active(version):
            continue
        kind = field.kind
        value = values.get(field.name, 0)
        if kind == BYTES:
            raw = bytes(value)[:field.count]
            out += raw + b"\x00" * (field.count - len(raw))
        elif kind in (PTR, IPTR):
            out += (int(value) & ((1 << (ptr_size * 8)) - 1)).to_bytes(ptr_size, "little")
        elif kind in REGISTRY:
            out += pack_struct(value or {}, kind, version, ptr_size)
        else:
            size = PRIMITIVE_SIZE[kind]
            if kind in (F32, F64):
                import struct as _s
                out += _s.pack("<f" if kind == F32 else "<d", float(value))
            else:
                out += (int(value) & ((1 << (size * 8)) - 1)).to_bytes(size, "little")
    return bytes(out)


def pack_struct_array(items: List[Dict[str, Any]], name: str, version: float,
                      ptr_size: int = 8) -> bytes:
    return b"".join(pack_struct(item, name, version, ptr_size) for item in items)
