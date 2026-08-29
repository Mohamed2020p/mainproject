"""
Synthetic IL2CPP fixtures.

There is no redistributable ``libil2cpp.so`` / ``global-metadata.dat`` pair we
can ship in a repository, so the test-suite builds its own.  The generator below
emits a real, self-consistent pair:

* ``global-metadata.dat`` - metadata version 24 (Unity 2019.x layout), two
  images (``mscorlib.dll`` and ``Assembly-CSharp.dll``), five types, five
  methods, two fields, one property, three parameters and one string literal.
* ``libil2cpp.so`` - a valid ELF64 image with ``.text`` / ``.data`` segments, a
  dynamic symbol table exporting ``g_CodeRegistration`` and
  ``g_MetadataRegistration``, a real ``Il2CppType`` table, per-module
  ``Il2CppCodeGenModule`` records, method pointers and field offsets.

Everything the dumper touches during a real run exists here, so the tests
exercise the actual parser rather than a mock.
"""

from __future__ import annotations

import os
import struct
from typing import Any, Dict, List, Tuple

from dumper import structs
from dumper.consts import (
    DT_GNU_HASH, DT_HASH, DT_STRTAB, DT_SYMTAB, EM_AARCH64, METADATA_SANITY,
    PT_DYNAMIC, PT_LOAD, PF_R, PF_W, PF_X, TYPE_CLASS, TYPE_I4, TYPE_STRING,
    TYPE_SZARRAY, TYPE_VALUETYPE, TYPE_VOID,
)

METADATA_VERSION = 24          # written to disk; resolved to 24.2 by the parser
METADATA_VERSION_RESOLVED = 24.2
PTR = 8

# ---------------------------------------------------------------------------
# metadata content
# ---------------------------------------------------------------------------

STRINGS = [
    "",                 # 0
    "mscorlib.dll",
    "System",
    "Object",
    "Int32",
    "String",
    "Void",
    "Assembly-CSharp.dll",
    "Game",
    "Player",
    "Main",
    "health",
    "name",
    "Health",
    "get_Health",
    "set_Health",
    "TakeDamage",
    "amount",
    ".ctor",
    "value",
    "args",
    "<Module>",
]
STRING_INDEX = {value: index for index, value in enumerate(STRINGS)}


def _s(text: str) -> int:
    return STRING_INDEX[text] * 1  # offsets are assigned in build order below


class _StringTable:
    def __init__(self) -> None:
        self.entries: List[str] = [""]
        self.index: Dict[str, int] = {"": 0}
        # offset 0 is the mandatory empty string, so real strings start at 1
        self._offset = 1

    def add(self, text: str) -> int:
        if text in self.index:
            return self.index[text]
        offset = self._offset
        self.index[text] = offset
        self.entries.append(text)
        self._offset += len(text.encode("utf-8")) + 1
        return offset

    def blob(self) -> bytes:
        out = bytearray()
        for text in self.entries:
            out += text.encode("utf-8") + b"\x00"
        return bytes(out)


def build_metadata() -> bytes:
    """Return a complete ``global-metadata.dat`` blob."""
    strings = _StringTable()

    # -- images / assemblies ------------------------------------------------
    images = [
        {"nameIndex": strings.add("mscorlib.dll"), "assemblyIndex": 0,
         "typeStart": 0, "typeCount": 3, "exportedTypeStart": 0,
         "exportedTypeCount": 0, "entryPointIndex": -1, "token": 1,
         "customAttributeStart": 0, "customAttributeCount": 0},
        {"nameIndex": strings.add("Assembly-CSharp.dll"), "assemblyIndex": 1,
         "typeStart": 3, "typeCount": 2, "exportedTypeStart": 0,
         "exportedTypeCount": 0, "entryPointIndex": 0, "token": 1,
         "customAttributeStart": 0, "customAttributeCount": 0},
    ]

    def assembly(name: str) -> Dict[str, Any]:
        return {
            "imageIndex": 0, "token": 0x20000000,
            "referencedAssemblyStart": 0, "referencedAssemblyCount": 0,
            "aname": {
                "nameIndex": strings.add(name), "cultureIndex": strings.add(""),
                "publicKeyIndex": 0, "hash_alg": 0x8004, "hash_len": 0,
                "flags": 1, "major": 4, "minor": 0, "build": 0, "revision": 0,
                "public_key_token": b"\x00" * 8,
            },
        }

    assemblies = [assembly("mscorlib"), assembly("Assembly-CSharp")]

    # -- types --------------------------------------------------------------
    # byvalTypeIndex refers to the Il2CppType table that lives in the binary.
    typedefs = [
        _typedef(strings, "<Module>", "", parent=-1, byval=0),
        _typedef(strings, "Object", "System", parent=-1, byval=1),
        _typedef(strings, "Int32", "System", parent=1, byval=5, bitfield=1),
        _typedef(strings, "Player", "Game", parent=1, byval=4,
                 field_start=0, field_count=2, method_start=0, method_count=4,
                 property_start=0, property_count=1),
        _typedef(strings, "Main", "Game", parent=1, byval=6,
                 method_start=4, method_count=1),
    ]

    fields = [
        {"nameIndex": strings.add("health"), "typeIndex": 2, "token": 0x04000001},
        {"nameIndex": strings.add("name"), "typeIndex": 3, "token": 0x04000002},
    ]

    methods = [
        _method(strings, ".ctor", 3, 0, 0, 0, 0x06000001, 0x0886),
        _method(strings, "get_Health", 3, 2, 0, 0, 0x06000002, 0x0886),
        _method(strings, "set_Health", 3, 0, 0, 1, 0x06000003, 0x0886),
        _method(strings, "TakeDamage", 3, 0, 1, 1, 0x06000004, 0x0886),
        _method(strings, "Main", 4, 0, 2, 1, 0x06000005, 0x0896),
    ]
    methods[1]["slot"] = 1

    parameters = [
        {"nameIndex": strings.add("value"), "token": 0x08000001, "typeIndex": 2},
        {"nameIndex": strings.add("amount"), "token": 0x08000002, "typeIndex": 2},
        {"nameIndex": strings.add("args"), "token": 0x08000003, "typeIndex": 7},
    ]

    properties = [
        {"nameIndex": strings.add("Health"), "get": 1, "set": 2, "attrs": 0,
         "token": 0x17000001},
    ]

    usage_pairs = [
        {"destinationIndex": 0, "encodedSourceIndex": (5 << 29) | 0},
        {"destinationIndex": 1, "encodedSourceIndex": (3 << 29) | 1},
    ]
    usage_lists = [{"start": 0, "count": len(usage_pairs)}]
    string_literals = [{"length": len(b"Hello"), "dataIndex": 0}]
    string_literal_data = b"Hello"

    # -- layout -------------------------------------------------------------
    header_size = structs.struct_size("GLOBAL_METADATA_HEADER",
                                      METADATA_VERSION_RESOLVED, PTR)

    sections: Dict[str, bytes] = {}

    def emit(name: str, blob: bytes) -> Tuple[int, int]:
        sections[name] = blob
        return 0, len(blob)

    string_literal_blob = structs.pack_struct_array(
        string_literals, "STRING_LITERAL", METADATA_VERSION_RESOLVED, PTR)
    string_blob = strings.blob()
    images_blob = structs.pack_struct_array(
        images, "IMAGE_DEFINITION", METADATA_VERSION_RESOLVED, PTR)
    assemblies_blob = structs.pack_struct_array(
        assemblies, "ASSEMBLY_DEFINITION", METADATA_VERSION_RESOLVED, PTR)
    typedef_blob = structs.pack_struct_array(
        typedefs, "TYPE_DEFINITION", METADATA_VERSION_RESOLVED, PTR)
    method_blob = structs.pack_struct_array(
        methods, "METHOD_DEFINITION", METADATA_VERSION_RESOLVED, PTR)
    parameter_blob = structs.pack_struct_array(
        parameters, "PARAMETER_DEFINITION", METADATA_VERSION_RESOLVED, PTR)
    field_blob = structs.pack_struct_array(
        fields, "FIELD_DEFINITION", METADATA_VERSION_RESOLVED, PTR)
    property_blob = structs.pack_struct_array(
        properties, "PROPERTY_DEFINITION", METADATA_VERSION_RESOLVED, PTR)
    usage_pair_blob = structs.pack_struct_array(
        usage_pairs, "METADATA_USAGE_PAIR", METADATA_VERSION_RESOLVED, PTR)
    usage_list_blob = structs.pack_struct_array(
        usage_lists, "METADATA_USAGE_LIST", METADATA_VERSION_RESOLVED, PTR)

    ordered = [
        ("stringLiteral", string_literal_blob),
        ("stringLiteralData", string_literal_data),
        ("string", string_blob),
        ("events", b""),
        ("properties", property_blob),
        ("methods", method_blob),
        ("parameterDefaultValues", b""),
        ("fieldDefaultValues", b""),
        ("fieldAndParameterDefaultValueData", b""),
        ("fieldMarshaledSizes", b""),
        ("parameters", parameter_blob),
        ("fields", field_blob),
        ("genericParameters", b""),
        ("genericParameterConstraints", b""),
        ("genericContainers", b""),
        ("nestedTypes", b""),
        ("interfaces", b""),
        ("vtableMethods", b""),
        ("interfaceOffsets", b""),
        ("typeDefinitions", typedef_blob),
        ("images", images_blob),
        ("assemblies", assemblies_blob),
        ("metadataUsageLists", usage_list_blob),
        ("metadataUsagePairs", usage_pair_blob),
        ("fieldRefs", b""),
        ("referencedAssemblies", b""),
        ("attributesInfo", b""),
        ("attributeTypes", b""),
        ("unresolvedVirtualCallParameterTypes", b""),
        ("unresolvedVirtualCallParameterRanges", b""),
        ("windowsRuntimeTypeNames", b""),
        ("exportedTypeDefinitions", b""),
    ]

    cursor = header_size
    offsets: Dict[str, Tuple[int, int]] = {}
    for name, blob in ordered:
        offsets[name] = (cursor, len(blob))
        cursor += len(blob)

    header: Dict[str, Any] = {"sanity": METADATA_SANITY, "version": METADATA_VERSION}
    for name, (offset, size) in offsets.items():
        header[name + "Offset"] = offset
        if name in ("metadataUsageLists", "metadataUsagePairs"):
            header[name + "Count"] = (
                len(usage_lists) if name == "metadataUsageLists" else len(usage_pairs))
        else:
            header[name + "Size"] = size

    out = bytearray(structs.pack_struct(header, "GLOBAL_METADATA_HEADER",
                                        METADATA_VERSION_RESOLVED, PTR))
    assert len(out) == header_size, len(out)
    for _name, blob in ordered:
        out += blob
    return bytes(out)


def _typedef(strings: _StringTable, name: str, namespace: str, *, parent: int,
             byval: int, field_start: int = 0, field_count: int = 0,
             method_start: int = 0, method_count: int = 0,
             property_start: int = 0, property_count: int = 0,
             bitfield: int = 0) -> Dict[str, Any]:
    return {
        "nameIndex": strings.add(name),
        "namespaceIndex": strings.add(namespace),
        "byvalTypeIndex": byval,
        "declaringTypeIndex": -1,
        "parentIndex": parent,
        "elementTypeIndex": -1,
        "genericContainerIndex": -1,
        "flags": 0x00100001,           # public | sealed
        "fieldStart": field_start,
        "methodStart": method_start,
        "eventStart": 0,
        "propertyStart": property_start,
        "nestedTypesStart": 0,
        "interfacesStart": 0,
        "vtableStart": 0,
        "interfaceOffsetsStart": 0,
        "method_count": method_count,
        "property_count": property_count,
        "field_count": field_count,
        "event_count": 0,
        "nested_type_count": 0,
        "vtable_count": 0,
        "interfaces_count": 0,
        "interface_offsets_count": 0,
        "bitfield": bitfield,
        "token": 0x02000001,
    }


def _method(strings: _StringTable, name: str, declaring: int, return_type: int,
            parameter_start: int, parameter_count: int, token: int,
            flags: int) -> Dict[str, Any]:
    return {
        "nameIndex": strings.add(name),
        "declaringType": declaring,
        "returnType": return_type,
        "parameterStart": parameter_start,
        "genericContainerIndex": -1,
        "token": token,
        "flags": flags,
        "iflags": 0,
        "slot": 0xFFFF,
        "parameterCount": parameter_count,
    }


# ---------------------------------------------------------------------------
# libil2cpp.so
# ---------------------------------------------------------------------------

def _il2cpp_type(kind: int, datapoint: int = 0, attrs: int = 0) -> Dict[str, Any]:
    return {"datapoint": datapoint, "bits": attrs | (kind << 16)}


def build_binary(text_base: int = 0x1000, data_base: int = 0x10000) -> bytes:
    """Return a complete ``libil2cpp.so`` blob."""
    text = bytearray(b"\xC0\x03\x5F\xD6" * 0x40)      # ret; ret; ...
    data = bytearray()

    def va(offset: int) -> int:
        return data_base + offset

    def put(blob: bytes, align: int = 8) -> int:
        while len(data) % align:
            data.append(0)
        offset = len(data)
        data.extend(blob)
        return offset

    # --- module name strings ------------------------------------------------
    name_mscorlib = va(put(b"mscorlib.dll\x00", 1))
    name_csharp = va(put(b"Assembly-CSharp.dll\x00", 1))

    # --- method pointers (live in .text) ------------------------------------
    def code_pointer(index: int) -> int:
        return text_base + index * 0x20

    csharp_methods = [code_pointer(i) for i in range(5)]
    csharp_method_array = va(put(struct.pack("<5Q", *csharp_methods)))
    mscorlib_method_array = va(put(struct.pack("<0Q")))

    # --- Il2CppType table ---------------------------------------------------
    type_specs = [
        _il2cpp_type(TYPE_VOID),                                     # 0
        _il2cpp_type(TYPE_CLASS, 1),                                 # 1  System.Object
        _il2cpp_type(TYPE_I4),                                       # 2  int
        _il2cpp_type(TYPE_STRING),                                   # 3  string
        _il2cpp_type(TYPE_CLASS, 3),                                 # 4  Game.Player
        _il2cpp_type(TYPE_VALUETYPE, 2),                             # 5  System.Int32
        _il2cpp_type(TYPE_CLASS, 4),                                 # 6  Game.Main
        _il2cpp_type(TYPE_SZARRAY, 0),                               # 7  string[]
    ]
    # type 7's datapoint must be the address of the element Il2CppType (index 3)
    type_blob_start = len(data)
    while len(data) % 8:
        data.append(0)
    type_blob_start = len(data)
    type_addresses = []
    for index, spec in enumerate(type_specs):
        type_addresses.append(va(len(data)))
        data += struct.pack("<QI", spec["datapoint"], spec["bits"])
    # patch SZARRAY datapoint now that we know type 3's address
    struct.pack_into("<Q", data, type_addresses[7] - data_base, type_addresses[3])

    types_array = va(put(struct.pack("<8Q", *type_addresses)))

    # --- code gen modules ----------------------------------------------------
    module_size = structs.struct_size("CODEGEN_MODULE", METADATA_VERSION_RESOLVED, PTR)
    module_mscorlib = {
        "moduleName": name_mscorlib, "methodPointerCount": 0,
        "methodPointers": mscorlib_method_array, "invokerIndices": 0,
        "reversePInvokeWrapperCount": 0, "reversePInvokeWrapperIndices": 0,
        "rgctxRangesCount": 0, "rgctxRanges": 0, "rgctxsCount": 0, "rgctxs": 0,
        "debuggerMetadata": 0,
    }
    module_csharp = dict(module_mscorlib)
    module_csharp.update({"moduleName": name_csharp, "methodPointerCount": 5,
                          "methodPointers": csharp_method_array})
    module_mscorlib_va = va(put(structs.pack_struct(
        module_mscorlib, "CODEGEN_MODULE", METADATA_VERSION_RESOLVED, PTR)))
    module_csharp_va = va(put(structs.pack_struct(
        module_csharp, "CODEGEN_MODULE", METADATA_VERSION_RESOLVED, PTR)))
    code_gen_modules_array = va(put(struct.pack("<2Q", module_mscorlib_va,
                                                module_csharp_va)))

    # --- field offsets --------------------------------------------------------
    player_offsets = va(put(struct.pack("<2i", 16, 24)))
    field_offsets_array = va(put(struct.pack("<5Q", 0, 0, 0, player_offsets, 0)))

    # --- metadata usages ------------------------------------------------------
    usage_targets = va(put(struct.pack("<2Q", va(0), va(0))))

    # --- generic insts / method table (empty but valid) -----------------------
    empty = va(put(struct.pack("<0Q")))

    # --- registrations --------------------------------------------------------
    code_registration = {
        "reversePInvokeWrapperCount": 0, "reversePInvokeWrappers": empty,
        "genericMethodPointersCount": 0, "genericMethodPointers": empty,
        "genericAdjustorThunks": empty,
        "invokerPointersCount": 0, "invokerPointers": empty,
        "customAttributeCount": 0, "customAttributeGenerators": empty,
        "unresolvedVirtualCallCount": 0, "unresolvedVirtualCallPointers": empty,
        "interopDataCount": 0, "interopData": empty,
        "windowsRuntimeFactoryCount": 0, "windowsRuntimeFactoryTable": empty,
        "codeGenModulesCount": 2, "codeGenModules": code_gen_modules_array,
    }
    metadata_registration = {
        "genericClassesCount": 0, "genericClasses": empty,
        "genericInstsCount": 0, "genericInsts": empty,
        "genericMethodTableCount": 0, "genericMethodTable": empty,
        "typesCount": 8, "types": types_array,
        "methodSpecsCount": 0, "methodSpecs": empty,
        "fieldOffsetsCount": 5, "fieldOffsets": field_offsets_array,
        "typeDefinitionsSizesCount": 5, "typeDefinitionsSizes": empty,
        "metadataUsagesCount": 2, "metadataUsages": usage_targets,
    }
    code_reg_va = va(put(structs.pack_struct(
        code_registration, "CODE_REGISTRATION", METADATA_VERSION_RESOLVED, PTR)))
    meta_reg_va = va(put(structs.pack_struct(
        metadata_registration, "METADATA_REGISTRATION", METADATA_VERSION_RESOLVED, PTR)))

    # --- dynamic symbols -------------------------------------------------------
    symbol_names = [b"\x00", b"g_CodeRegistration\x00", b"g_MetadataRegistration\x00"]
    dynstr = b"".join(symbol_names)
    dynstr_va = va(put(dynstr, 1))
    symbols = [
        struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0),
        struct.pack("<IBBHQQ", 1, 4, 0, 3, code_reg_va, 112),
        struct.pack("<IBBHQQ", len(symbol_names[0]) + len(symbol_names[1]),
                    4, 0, 3, meta_reg_va, 128),
    ]
    symtab_va = va(put(b"".join(symbols)))
    # DT_HASH: nbucket, nchain, bucket[], chain[]
    hash_blob = struct.pack("<II", 2, 3) + struct.pack("<2I", 1, 2) + struct.pack("<3I", 0, 0, 1)
    hash_va = va(put(hash_blob, 4))

    # --- dynamic section -------------------------------------------------------
    dynamic_entries = [
        (DT_HASH, hash_va),
        (DT_STRTAB, dynstr_va),
        (DT_SYMTAB, symtab_va),
        (11, 24),          # DT_SYMENT
        (10, len(dynstr)), # DT_STRSZ
        (0, 0),            # DT_NULL
    ]
    dynamic_offset = len(data)
    while len(data) % 8:
        data.append(0)
    dynamic_offset = len(data)
    for tag, value in dynamic_entries:
        data += struct.pack("<qQ", tag, value)
    dynamic_va = va(dynamic_offset)
    dynamic_size = len(data) - dynamic_offset

    # pad the data segment to a page
    while len(data) % 0x1000:
        data.append(0)

    return _assemble_elf(bytes(text), bytes(data), text_base, data_base,
                         dynamic_va, dynamic_size)


def _assemble_elf(text: bytes, data: bytes, text_base: int, data_base: int,
                  dynamic_va: int, dynamic_size: int) -> bytes:
    ehdr_size = 64
    phdr_size = 56
    phnum = 3
    header_block = ehdr_size + phdr_size * phnum

    text_file = 0x1000
    data_file = text_file + ((len(text) + 0xFFF) & ~0xFFF)
    section_block_offset = data_file + len(data)

    shstrtab_strings = [b"\x00", b".text\x00", b".data\x00", b".dynamic\x00",
                        b".dynsym\x00", b".dynstr\x00", b".shstrtab\x00"]
    shstrtab = b"".join(shstrtab_strings)
    # .shstrtab follows the seven 64-byte section headers
    shstrtab_offset = section_block_offset + 7 * 64

    # sh_name is the byte offset of the section name inside .shstrtab
    name_offset: Dict[str, int] = {}
    cursor = 0
    for raw in shstrtab_strings:
        name_offset[raw] = cursor
        cursor += len(raw)
    n = lambda key: name_offset[key]          # noqa: E731

    section_headers = [
        struct.pack("<IIQQQQIIQQ", 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
        struct.pack("<IIQQQQIIQQ", n(b".text\x00"), 1, 6, text_base, text_file,
                    len(text), 0, 0, 16, 0),
        struct.pack("<IIQQQQIIQQ", n(b".data\x00"), 1, 3, data_base, data_file,
                    len(data), 0, 0, 32, 0),
        struct.pack("<IIQQQQIIQQ", n(b".dynamic\x00"), 6, 0, dynamic_va,
                    data_file + (dynamic_va - data_base), dynamic_size, 5, 0, 8, 0),
        struct.pack("<IIQQQQIIQQ", n(b".dynsym\x00"), 2, 0, 0, 0, 0, 4, 5, 8, 0),
        struct.pack("<IIQQQQIIQQ", n(b".dynstr\x00"), 3, 0, 0, 0, 0, 4, 0, 1, 0),
        struct.pack("<IIQQQQIIQQ", n(b".shstrtab\x00"), 3, 0, 0, shstrtab_offset,
                    len(shstrtab), 0, 0, 1, 0),
    ]
    section_blob = b"".join(section_headers) + shstrtab

    image = bytearray(ehdr_size)      # e_ident + ELF header, filled in below
    # program headers start immediately after the ELF header
    image += struct.pack("<IIQQQQQQ", PT_LOAD, PF_R | PF_X, text_file, text_base,
                         text_base, len(text), len(text), 0x1000)
    image += struct.pack("<IIQQQQQQ", PT_LOAD, PF_R | PF_W, data_file, data_base,
                         data_base, len(data), len(data), 0x1000)
    image += struct.pack("<IIQQQQQQ", PT_DYNAMIC, PF_R | PF_W,
                         data_file + (dynamic_va - data_base), dynamic_va,
                         dynamic_va, dynamic_size, dynamic_size, 8)
    assert len(image) == header_block, len(image)
    image += b"\x00" * (text_file - len(image))
    image += text
    image += b"\x00" * (data_file - len(image))
    image += data
    image += b"\x00" * (section_block_offset - len(image))
    image += section_blob

    ehdr = bytearray(16)
    ehdr[0:4] = b"\x7fELF"
    ehdr[4] = 2                 # ELFCLASS64
    ehdr[5] = 1                 # little endian
    ehdr[6] = 1                 # EV_CURRENT
    ehdr[7] = 0                 # ELFOSABI_SYSV
    header = struct.pack("<HHIQQQIHHHHHH",
                         3,               # ET_DYN
                         EM_AARCH64,
                         1,               # e_version
                         text_base,       # e_entry
                         ehdr_size,       # e_phoff
                         section_block_offset,  # e_shoff
                         0,               # e_flags
                         ehdr_size,       # e_ehsize
                         phdr_size,       # e_phentsize
                         phnum,           # e_phnum
                         64,              # e_shentsize
                         len(section_headers),
                         6)               # e_shstrndx
    image[0:16] = ehdr
    image[16:16 + len(header)] = header
    return bytes(image)


def write_fixture(directory: str) -> Tuple[str, str]:
    """Write both fixture files into ``directory`` and return their paths."""
    os.makedirs(directory, exist_ok=True)
    metadata_path = os.path.join(directory, "global-metadata.dat")
    binary_path = os.path.join(directory, "libil2cpp.so")
    with open(metadata_path, "wb") as handle:
        handle.write(build_metadata())
    with open(binary_path, "wb") as handle:
        handle.write(build_binary())
    return binary_path, metadata_path
