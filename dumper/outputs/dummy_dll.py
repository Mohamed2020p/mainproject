"""
``DummyDll`` - restored .NET assemblies that dnSpy / ILSpy can open.

IL2CPP throws the original assemblies away, but ``global-metadata.dat`` still
carries everything needed to rebuild their *shape*: every type, field, method,
parameter, property, event, generic parameter and interface.  This module writes
those shapes back out as real ECMA-335 (CLI) PE files.

The generated assemblies contain no IL - method RVAs are 0 - so they cannot be
executed.  They exist so a decompiler can load them, resolve references and let
you browse the API surface, which is exactly what the reference dumper's
``DummyDll`` folder is for.

Implemented metadata tables:
``Module``, ``TypeRef``, ``TypeDef``, ``Field``, ``MethodDef``, ``Param``,
``InterfaceImpl``, ``MemberRef``, ``EventMap``, ``Event``, ``PropertyMap``,
``Property``, ``MethodSemantics``, ``ModuleRef``, ``TypeSpec``, ``Assembly``,
``AssemblyRef``, ``NestedClass``, ``GenericParam``.
"""

from __future__ import annotations

import os
import struct
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import consts
from ..executor import Executor

Progress = Optional[Callable[[float, str], None]]

# ---------------------------------------------------------------------------
# table ids (ECMA-335 II.22)
# ---------------------------------------------------------------------------

T_MODULE = 0x00
T_TYPEREF = 0x01
T_TYPEDEF = 0x02
T_FIELD = 0x04
T_METHODDEF = 0x06
T_PARAM = 0x08
T_INTERFACEIMPL = 0x09
T_MEMBERREF = 0x0A
T_STANDALONESIG = 0x11
T_EVENTMAP = 0x12
T_EVENT = 0x14
T_PROPERTYMAP = 0x15
T_PROPERTY = 0x17
T_METHODSEMANTICS = 0x18
T_MODULEREF = 0x1A
T_TYPESPEC = 0x1B
T_ASSEMBLY = 0x20
T_ASSEMBLYREF = 0x23
T_NESTEDCLASS = 0x29
T_GENERICPARAM = 0x2A

TABLE_NAMES = {
    T_MODULE: "Module",
    T_TYPEREF: "TypeRef",
    T_TYPEDEF: "TypeDef",
    T_FIELD: "Field",
    T_METHODDEF: "MethodDef",
    T_PARAM: "Param",
    T_INTERFACEIMPL: "InterfaceImpl",
    T_MEMBERREF: "MemberRef",
    T_STANDALONESIG: "StandAloneSig",
    T_EVENTMAP: "EventMap",
    T_EVENT: "Event",
    T_PROPERTYMAP: "PropertyMap",
    T_PROPERTY: "Property",
    T_METHODSEMANTICS: "MethodSemantics",
    T_MODULEREF: "ModuleRef",
    T_TYPESPEC: "TypeSpec",
    T_ASSEMBLY: "Assembly",
    T_ASSEMBLYREF: "AssemblyRef",
    T_NESTEDCLASS: "NestedClass",
    T_GENERICPARAM: "GenericParam",
}

CODED_INDEXES: Dict[str, Tuple[int, Tuple[int, ...]]] = {
    "TypeDefOrRef": (2, (T_TYPEDEF, T_TYPEREF, T_TYPESPEC)),
    "HasConstant": (2, (T_FIELD, T_PARAM, T_PROPERTY)),
    "MemberRefParent": (3, (T_TYPEDEF, T_TYPEREF, T_MODULEREF, T_METHODDEF, T_TYPESPEC)),
    "HasSemantics": (1, (T_EVENT, T_PROPERTY)),
    "MethodDefOrRef": (1, (T_METHODDEF, T_MEMBERREF)),
    "ResolutionScope": (2, (T_MODULE, T_MODULEREF, T_ASSEMBLYREF, T_TYPEREF)),
    "TypeOrMethodDef": (1, (T_TYPEDEF, T_METHODDEF)),
}

# Column schemas: (kind, arg)
#   kind 'u8'|'u16'|'u32'  -> fixed width
#   kind 'str'|'blob'|'guid' -> heap index
#   kind 'tab'             -> simple table index
#   kind 'coded'           -> coded index
SCHEMAS: Dict[int, List[Tuple[str, Any]]] = {
    T_MODULE: [("u16", None), ("str", None), ("guid", None), ("guid", None), ("guid", None)],
    T_TYPEREF: [("coded", "ResolutionScope"), ("str", None), ("str", None)],
    T_TYPEDEF: [("u32", None), ("str", None), ("str", None),
                ("coded", "TypeDefOrRef"), ("tab", T_FIELD), ("tab", T_METHODDEF)],
    T_FIELD: [("u16", None), ("str", None), ("blob", None)],
    T_METHODDEF: [("u32", None), ("u16", None), ("u16", None), ("str", None),
                  ("blob", None), ("tab", T_PARAM)],
    T_PARAM: [("u16", None), ("u16", None), ("str", None)],
    T_INTERFACEIMPL: [("tab", T_TYPEDEF), ("coded", "TypeDefOrRef")],
    T_MEMBERREF: [("coded", "MemberRefParent"), ("str", None), ("blob", None)],
    T_STANDALONESIG: [("blob", None)],
    T_EVENTMAP: [("tab", T_TYPEDEF), ("tab", T_EVENT)],
    T_EVENT: [("u16", None), ("str", None), ("coded", "TypeDefOrRef")],
    T_PROPERTYMAP: [("tab", T_TYPEDEF), ("tab", T_PROPERTY)],
    T_PROPERTY: [("u16", None), ("str", None), ("blob", None)],
    T_METHODSEMANTICS: [("u16", None), ("tab", T_METHODDEF), ("coded", "HasSemantics")],
    T_MODULEREF: [("str", None)],
    T_TYPESPEC: [("blob", None)],
    T_ASSEMBLY: [("u32", None), ("u16", None), ("u16", None), ("u16", None),
                 ("u16", None), ("u32", None), ("blob", None), ("str", None),
                 ("str", None)],
    T_ASSEMBLYREF: [("u16", None), ("u16", None), ("u16", None), ("u16", None),
                    ("u32", None), ("blob", None), ("str", None), ("str", None),
                    ("blob", None)],
    T_NESTEDCLASS: [("tab", T_TYPEDEF), ("tab", T_TYPEDEF)],
    T_GENERICPARAM: [("u16", None), ("u16", None), ("coded", "TypeOrMethodDef"),
                     ("str", None)],
}


# ---------------------------------------------------------------------------
# heaps
# ---------------------------------------------------------------------------
class StringHeap:
    def __init__(self) -> None:
        self._offsets: Dict[str, int] = {"": 0}
        self._buffer = bytearray(b"\x00")

    def add(self, value: str) -> int:
        value = value or ""
        if value in self._offsets:
            return self._offsets[value]
        offset = len(self._buffer)
        self._buffer += value.encode("utf-8") + b"\x00"
        self._offsets[value] = offset
        return offset

    @property
    def data(self) -> bytes:
        return bytes(self._buffer)


class BlobHeap:
    def __init__(self) -> None:
        self._offsets: Dict[bytes, int] = {b"": 0}
        self._buffer = bytearray(b"\x00")

    def add(self, value: bytes) -> int:
        if value in self._offsets:
            return self._offsets[value]
        offset = len(self._buffer)
        self._buffer += _blob_header(len(value)) + value
        self._offsets[value] = offset
        return offset

    @property
    def data(self) -> bytes:
        return bytes(self._buffer)


class GuidHeap:
    def __init__(self) -> None:
        self._items: List[bytes] = []

    def add(self, value: bytes) -> int:
        self._items.append(value)
        return len(self._items)  # 1-based

    @property
    def data(self) -> bytes:
        return b"".join(self._items)


def _blob_header(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    if length < 0x4000:
        return struct.pack(">H", length | 0x8000)
    return struct.pack(">I", length | 0xC0000000)


def _compressed(value: int) -> bytes:
    if value < 0x80:
        return bytes([value])
    if value < 0x4000:
        return struct.pack(">H", value | 0x8000)
    return struct.pack(">I", value | 0xC0000000)


# ---------------------------------------------------------------------------
# table model
# ---------------------------------------------------------------------------
class MetadataImage:
    def __init__(self) -> None:
        self.rows: Dict[int, List[List[Tuple[str, Any]]]] = {t: [] for t in SCHEMAS}
        self.strings = StringHeap()
        self.blobs = BlobHeap()
        self.guids = GuidHeap()

    def add(self, table: int, *cells: Tuple[str, Any]) -> int:
        schema = SCHEMAS[table]
        if len(cells) != len(schema):
            raise ValueError("table %s expects %d cells, got %d"
                             % (TABLE_NAMES[table], len(schema), len(cells)))
        self.rows[table].append(list(cells))
        return len(self.rows[table]) - 1

    # -- width computation --
    def _heap_width(self, size: int) -> int:
        return 4 if size > 0xFFFF else 2

    def _column_width(self, kind: str, arg: Any) -> int:
        if kind == "u8":
            return 1
        if kind == "u16":
            return 2
        if kind == "u32":
            return 4
        if kind == "str":
            return self._heap_width(len(self.strings.data))
        if kind == "blob":
            return self._heap_width(len(self.blobs.data))
        if kind == "guid":
            return self._heap_width(len(self.guids.data))
        if kind == "tab":
            return 2 if len(self.rows[arg]) < 0x10000 else 4
        if kind == "coded":
            bits, tables = CODED_INDEXES[arg]
            biggest = max((len(self.rows[t]) for t in tables), default=0)
            return 2 if biggest < (1 << (16 - bits)) else 4
        raise ValueError("unknown column kind %r" % kind)

    def build_tables(self) -> Tuple[bytes, int, int]:
        valid = 0
        for table in self.rows:
            if self.rows[table]:
                valid |= (1 << table)

        heap_sizes = 0
        if len(self.strings.data) > 0xFFFF:
            heap_sizes |= 0x01
        if len(self.guids.data) > 0xFFFF:
            heap_sizes |= 0x02
        if len(self.blobs.data) > 0xFFFF:
            heap_sizes |= 0x04

        schema_blob = bytearray()
        rows_blob = bytearray()
        for table in sorted(SCHEMAS):
            if not (valid & (1 << table)):
                continue
            rows_blob += struct.pack("<I", len(self.rows[table]))
            for kind, arg in SCHEMAS[table]:
                schema_blob += bytes([self._type_code(kind, arg)])

        stream = bytearray()
        stream += struct.pack("<IBBBB", 0, 2, 0, heap_sizes, 1)
        stream += struct.pack("<Q", valid)
        stream += struct.pack("<Q", 0)          # sorted
        stream += bytes(rows_blob)
        stream += bytes(schema_blob)

        for table in sorted(SCHEMAS):
            if not (valid & (1 << table)):
                continue
            widths = [self._column_width(kind, arg) for kind, arg in SCHEMAS[table]]
            for row in self.rows[table]:
                for width, (kind, arg), cell in zip(widths, SCHEMAS[table], row):
                    stream += self._encode_cell(width, kind, arg, cell)
        return bytes(stream), valid, heap_sizes

    def _type_code(self, kind: str, arg: Any) -> int:
        if kind == "u8":
            return 0x04 if arg is None else 0x04
        if kind == "u16":
            return 0x06
        if kind == "u32":
            return 0x08
        if kind == "str":
            return 0x10
        if kind == "blob":
            return 0x12
        if kind == "guid":
            return 0x11
        if kind == "tab":
            table_codes = {
                T_MODULE: 0x00, T_TYPEREF: 0x01, T_TYPEDEF: 0x02, T_FIELD: 0x04,
                T_METHODDEF: 0x06, T_PARAM: 0x08, T_INTERFACEIMPL: 0x09,
                T_MEMBERREF: 0x0A, T_STANDALONESIG: 0x11, T_EVENTMAP: 0x12,
                T_EVENT: 0x14, T_PROPERTYMAP: 0x15, T_PROPERTY: 0x17,
                T_METHODSEMANTICS: 0x18, T_MODULEREF: 0x1A, T_TYPESPEC: 0x1B,
                T_ASSEMBLY: 0x20, T_ASSEMBLYREF: 0x23, T_NESTEDCLASS: 0x29,
                T_GENERICPARAM: 0x2A,
            }
            return table_codes[arg]
        if kind == "coded":
            coded_codes = {
                "TypeDefOrRef": 0x00, "HasConstant": 0x01, "MemberRefParent": 0x04,
                "HasSemantics": 0x06, "MethodDefOrRef": 0x07,
                "ResolutionScope": 0x0D, "TypeOrMethodDef": 0x0E,
            }
            return coded_codes[arg]
        raise ValueError("unknown column kind %r" % kind)

    def _encode_cell(self, width: int, kind: str, arg: Any,
                     cell: Tuple[str, Any]) -> bytes:
        if kind in ("u8", "u16", "u32"):
            value = int(cell[1])
            return value.to_bytes(width, "little")
        if kind in ("str", "blob"):
            return int(cell[1]).to_bytes(width, "little")
        if kind == "guid":
            return int(cell[1]).to_bytes(width, "little")
        if kind == "tab":
            return (int(cell[1]) + 1).to_bytes(width, "little")
        if kind == "coded":
            bits, tables = CODED_INDEXES[arg]
            table, index = cell[1]
            tag = tables.index(table)
            return ((index + 1) << bits | tag).to_bytes(width, "little")
        raise ValueError("unknown column kind %r" % kind)


# ---------------------------------------------------------------------------
# PE / CLI container
# ---------------------------------------------------------------------------
def build_managed_pe(metadata_blob: bytes, image_base: int = 0x10000000) -> bytes:
    """Wrap a CLI metadata blob into a minimal but valid managed PE32 file."""
    file_alignment = 0x200
    section_alignment = 0x2000
    header_size = 0x200
    text_va = 0x2000

    cli_size = 72
    metadata_rva = text_va + _align(cli_size, 4)
    text_size = _align(cli_size, 4) + len(metadata_blob)

    image = bytearray()
    image += _dos_header()
    image += b"PE\x00\x00"
    image += struct.pack("<HHIIIHH", 0x14C, 1, int(time.time()) & 0xFFFFFFFF,
                         0, 0, 0xE0, 0x2102)
    image += _optional_header(size_of_code=_align(text_size, file_alignment),
                              image_base=image_base,
                              section_alignment=section_alignment,
                              file_alignment=file_alignment,
                              size_of_image=_align(text_va + text_size,
                                                   section_alignment),
                              size_of_headers=header_size,
                              cli_rva=text_va, cli_size=cli_size)
    image += _section_header(b".text", text_va, _align(text_size, file_alignment),
                             header_size, 0x60000020)
    image += b"\x00" * (header_size - len(image))

    # IMAGE_COR20_HEADER: cb, runtime version, metadata directory, flags,
    # entry point token, then six unused (RVA, size) directory pairs.
    cli_header = struct.pack("<IHH" + "I" * 16,
                             72, 2, 5, metadata_rva, len(metadata_blob),
                             1,          # COMIMAGE_FLAGS_ILONLY
                             0,          # entry point token (none)
                             0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    image += cli_header
    image += b"\x00" * (_align(cli_size, 4) - len(cli_header))
    image += metadata_blob
    image += b"\x00" * (_align(len(image), file_alignment) - len(image))
    return bytes(image)


def _dos_header() -> bytes:
    header = bytearray(128)
    header[0:2] = b"MZ"
    struct.pack_into("<I", header, 0x3C, 0x80)
    return bytes(header)


def _optional_header(*, size_of_code: int, image_base: int, section_alignment: int,
                     file_alignment: int, size_of_image: int, size_of_headers: int,
                     cli_rva: int, cli_size: int) -> bytes:
    out = bytearray()
    out += struct.pack("<HBB", 0x10B, 8, 0)
    out += struct.pack("<III", size_of_code, 0, 0)          # code / init / uninit
    out += struct.pack("<I", 0)                              # entry point
    out += struct.pack("<II", 0x2000, 0x2000)                # base of code / data
    out += struct.pack("<I", image_base)
    out += struct.pack("<II", section_alignment, file_alignment)
    out += struct.pack("<HHHHHH", 4, 0, 0, 0, 4, 0)
    out += struct.pack("<I", 0)                              # Win32VersionValue
    out += struct.pack("<II", size_of_image, size_of_headers)
    out += struct.pack("<I", 0)                              # checksum
    out += struct.pack("<HH", 3, 0)                          # subsystem, dll chars
    out += struct.pack("<IIII", 0x100000, 0x1000, 0x100000, 0x1000)
    out += struct.pack("<II", 0, 16)                         # loader flags, ndirs
    directories = [(0, 0)] * 16
    directories[14] = (cli_rva, cli_size)
    for rva, size in directories:
        out += struct.pack("<II", rva, size)
    return bytes(out)


def _section_header(name: bytes, virtual_address: int, virtual_size: int,
                    pointer_to_raw: int, characteristics: int) -> bytes:
    return struct.pack("<8sIIIIIIHHI", name, virtual_size, virtual_address,
                       virtual_size, pointer_to_raw, 0, 0, 0, 0, characteristics)


def _align(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


# ---------------------------------------------------------------------------
# CLI metadata container
# ---------------------------------------------------------------------------
def build_metadata_root(image: MetadataImage, version: str = "v4.0.30319") -> bytes:
    tables_blob, _valid, _heap_sizes = image.build_tables()

    streams: List[Tuple[str, bytes]] = [
        ("#~", tables_blob),
        ("#Strings", image.strings.data),
        ("#US", b"\x00"),
        ("#GUID", image.guids.data or (b"\x00" * 16)),
        ("#Blob", image.blobs.data),
    ]

    version_bytes = version.encode("utf-8") + b"\x00"
    version_bytes += b"\x00" * (_align(len(version_bytes), 4) - len(version_bytes))

    root_header_size = 16 + len(version_bytes) + 2 + 2
    offset = root_header_size
    for name, data in streams:
        name_len = _align(len(name) + 1, 4)
        offset += 8 + name_len
    offset = _align(offset, 4)

    out = bytearray()
    out += struct.pack("<IHHI", 0x424A5342, 1, 1, 0)
    out += struct.pack("<I", len(version_bytes))
    out += version_bytes
    out += struct.pack("<HH", 0, len(streams))

    cursor = offset
    for name, data in streams:
        out += struct.pack("<iI", cursor, len(data))
        raw = name.encode("utf-8") + b"\x00"
        raw += b"\x00" * (_align(len(raw), 4) - len(raw))
        out += raw
        cursor += _align(len(data), 4)

    out += b"\x00" * (offset - len(out))
    for name, data in streams:
        out += data
        out += b"\x00" * (_align(len(data), 4) - len(data))
    return bytes(out)


_ELEMENT_TYPES = frozenset({
    consts.TYPE_VOID, consts.TYPE_BOOLEAN, consts.TYPE_CHAR, consts.TYPE_I1,
    consts.TYPE_U1, consts.TYPE_I2, consts.TYPE_U2, consts.TYPE_I4,
    consts.TYPE_U4, consts.TYPE_I8, consts.TYPE_U8, consts.TYPE_R4,
    consts.TYPE_R8, consts.TYPE_STRING, consts.TYPE_TYPEDBYREF, consts.TYPE_I,
    consts.TYPE_U, consts.TYPE_FNPTR, consts.TYPE_OBJECT,
})


# ---------------------------------------------------------------------------
# the actual generator
# ---------------------------------------------------------------------------
class _Context:
    """Shared state while building every assembly of the dump."""

    def __init__(self, executor: Executor):
        self.executor = executor
        self.metadata = executor.metadata
        self.il2cpp = executor.il2cpp
        self.full = executor.has_types

        # typedef index owning each image
        self.image_of_typedef: List[int] = []
        for image_index, image_def in enumerate(self.metadata.imageDefs):
            start = image_def["typeStart"]
            for _ in range(image_def["typeCount"]):
                self.image_of_typedef.append(image_index)
        while len(self.image_of_typedef) < len(self.metadata.typeDefs):
            self.image_of_typedef.append(len(self.metadata.imageDefs) - 1)

        self.image_name = [self.metadata.get_string_from_index(i["nameIndex"])
                           for i in self.metadata.imageDefs]

        # id(Il2CppTypeDefinition dict) -> global typedef index
        self.typedef_index: Dict[int, int] = {id(td): i for i, td
                                              in enumerate(self.metadata.typeDefs)}

        # types-array index -> typedef index
        self.typedef_of_type_index: Dict[int, int] = {}
        self.index_of_type_entry: Dict[int, int] = {}
        if self.full:
            id_to_index = {id(td): i for i, td in enumerate(self.metadata.typeDefs)}
            for index, entry in enumerate(self.il2cpp.types):
                self.index_of_type_entry[id(entry)] = index
                if entry["type"] in (consts.TYPE_CLASS, consts.TYPE_VALUETYPE):
                    typedef = executor._get_type_definition(entry)
                    if typedef is not None and id(typedef) in id_to_index:
                        self.typedef_of_type_index[index] = id_to_index[id(typedef)]

    def typedef_index_of(self, key: int) -> int:
        return self.typedef_index.get(key, -1)

    def assembly_name_of_image(self, image_index: int) -> str:
        if 0 <= image_index < len(self.metadata.assemblyDefs):
            assembly = self.metadata.assemblyDefs[image_index]
            return self.metadata.get_string_from_index(assembly["aname"]["nameIndex"])
        if 0 <= image_index < len(self.image_name):
            return self.image_name[image_index].rsplit(".", 1)[0]
        return "Assembly%d" % image_index


class _AssemblyBuilder:
    def __init__(self, context: _Context, image_index: int):
        self.context = context
        self.image_index = image_index
        self.image = MetadataImage()
        self.type_row: Dict[int, int] = {}          # typedef index -> TypeDef row
        self.type_row_ready: Dict[int, bool] = {}
        self.type_ref_row: Dict[int, int] = {}      # typedef index -> TypeRef row
        self.assembly_ref_row: Dict[str, int] = {}
        self.field_rows = 0
        self.method_rows = 0
        self.param_rows = 0
        self.property_rows = 0
        self.event_rows = 0

    # ---------------- references ----------------
    def _assembly_ref(self, assembly_name: str) -> int:
        if assembly_name in self.assembly_ref_row:
            return self.assembly_ref_row[assembly_name]
        row = self.image.add(T_ASSEMBLYREF,
                             ("u16", 4), ("u16", 0), ("u16", 0), ("u16", 0),
                             ("u32", 0), ("blob", 0),
                             ("str", self.image.strings.add(assembly_name)),
                             ("str", 0), ("blob", 0))
        self.assembly_ref_row[assembly_name] = row
        return row

    def _type_ref(self, typedef_index: int) -> int:
        if typedef_index in self.type_ref_row:
            return self.type_ref_row[typedef_index]
        metadata = self.context.metadata
        typedef = metadata.typeDefs[typedef_index]
        image_index = self.context.image_of_typedef[typedef_index]
        scope_cell = ("coded", (T_ASSEMBLYREF, self._assembly_ref(
            self.context.assembly_name_of_image(image_index))))
        name = metadata.get_string_from_index(typedef["nameIndex"])
        namespace = "" if typedef["declaringTypeIndex"] != -1 else \
            metadata.get_string_from_index(typedef["namespaceIndex"])
        row = self.image.add(T_TYPEREF, scope_cell,
                             ("str", self.image.strings.add(name)),
                             ("str", self.image.strings.add(namespace)))
        self.type_ref_row[typedef_index] = row
        return row

    def _type_def_or_ref(self, typedef_index: int) -> Tuple[str, Any]:
        if typedef_index in self.type_row:
            return ("coded", (T_TYPEDEF, self.type_row[typedef_index]))
        return ("coded", (T_TYPEREF, self._type_ref(typedef_index)))

    # ---------------- types ----------------
    def build(self) -> bytes:
        metadata = self.context.metadata
        image_def = metadata.imageDefs[self.image_index]
        image_name = self.context.image_name[self.image_index]

        self.image.add(T_MODULE, ("u16", 0),
                       ("str", self.image.strings.add(image_name)),
                       ("guid", self.image.guids.add(_synthetic_guid(image_name))),
                       ("guid", 0), ("guid", 0))

        assembly = metadata.assemblyDefs[self.image_index] \
            if self.image_index < len(metadata.assemblyDefs) else None
        if assembly is not None:
            aname = assembly["aname"]
            self.image.add(
                T_ASSEMBLY,
                ("u32", 0x8004),
                ("u16", aname["major"] & 0xFFFF), ("u16", aname["minor"] & 0xFFFF),
                ("u16", aname["build"] & 0xFFFF), ("u16", aname["revision"] & 0xFFFF),
                ("u32", aname["flags"]),
                ("blob", 0),
                ("str", self.image.strings.add(
                    metadata.get_string_from_index(aname["nameIndex"]))),
                ("str", self.image.strings.add(
                    metadata.get_string_from_index(aname["cultureIndex"]))))
        else:
            self.image.add(T_ASSEMBLY, ("u32", 0x8004), ("u16", 0), ("u16", 0),
                           ("u16", 0), ("u16", 0), ("u32", 0), ("blob", 0),
                           ("str", self.image.strings.add(image_name)), ("str", 0))

        start = image_def["typeStart"]
        end = start + image_def["typeCount"]
        typedef_range = range(start, min(end, len(metadata.typeDefs)))

        # pass 1 - reserve TypeDef rows so cross references resolve
        for typedef_index in typedef_range:
            typedef = metadata.typeDefs[typedef_index]
            name = metadata.get_string_from_index(typedef["nameIndex"])
            namespace = "" if typedef["declaringTypeIndex"] != -1 else \
                metadata.get_string_from_index(typedef["namespaceIndex"])
            row = self.image.add(T_TYPEDEF,
                                 ("u32", typedef["flags"]),
                                 ("str", self.image.strings.add(name)),
                                 ("str", self.image.strings.add(namespace)),
                                 ("coded", (T_TYPEDEF, 0)),   # Extends, patched
                                 ("tab", 0), ("tab", 0))
            self.type_row[typedef_index] = row

        # pass 2 - fill members
        for typedef_index in typedef_range:
            self._fill_type(typedef_index)

        # pass 3 - nested classes
        for typedef_index in typedef_range:
            typedef = metadata.typeDefs[typedef_index]
            declaring = typedef["declaringTypeIndex"]
            if declaring != -1:
                parent_typedef = self._typedef_from_type_index(declaring)
                if parent_typedef is not None and parent_typedef in self.type_row:
                    self.image.add(T_NESTEDCLASS, ("tab", self.type_row[typedef_index]),
                                   ("tab", self.type_row[parent_typedef]))

        return build_metadata_root(self.image)

    # ---------------- one type ----------------
    def _fill_type(self, typedef_index: int) -> None:
        metadata = self.context.metadata
        typedef = metadata.typeDefs[typedef_index]
        row = self.type_row[typedef_index]

        # Extends
        extends = ("coded", (T_TYPEDEF, 0))
        parent = typedef["parentIndex"]
        if parent >= 0 and self.context.full:
            parent_typedef = self._typedef_from_type_index(parent)
            if parent_typedef is not None:
                extends = self._type_def_or_ref(parent_typedef)
            else:
                entry = self.context.executor.type_at(parent)
                if entry is not None and entry["type"] == consts.TYPE_GENERICINST:
                    extends = ("coded", (T_TYPESPEC, self._type_spec(entry)))
        elif parent >= 0:
            parent_typedef = self._typedef_from_type_index(parent)
            if parent_typedef is not None:
                extends = self._type_def_or_ref(parent_typedef)
        self.image.rows[T_TYPEDEF][row][3] = extends

        # generic parameters
        if typedef["genericContainerIndex"] >= 0:
            container = self.context.executor._generic_container(
                typedef["genericContainerIndex"])
            if container is not None:
                for i in range(container["type_argc"]):
                    index = container["genericParameterStart"] + i
                    if index < len(metadata.genericParameters):
                        parameter = metadata.genericParameters[index]
                        self.image.add(
                            T_GENERICPARAM,
                            ("u16", parameter["num"]),
                            ("u16", parameter["flags"]),
                            ("coded", (T_TYPEDEF, row)),
                            ("str", self.image.strings.add(
                                metadata.get_string_from_index(parameter["nameIndex"]))))

        # interfaces
        for i in range(typedef["interfaces_count"]):
            slot = typedef["interfacesStart"] + i
            if slot >= len(metadata.interfaceIndices):
                break
            type_index = metadata.interfaceIndices[slot]
            interface_typedef = self._typedef_from_type_index(type_index)
            if interface_typedef is not None:
                cell = self._type_def_or_ref(interface_typedef)
            elif self.context.full:
                entry = self.context.executor.type_at(type_index)
                if entry is None:
                    continue
                cell = ("coded", (T_TYPESPEC, self._type_spec(entry)))
            else:
                continue
            self.image.add(T_INTERFACEIMPL, ("tab", row), cell)

        field_start = self.field_rows
        for i in range(typedef["fieldStart"],
                       typedef["fieldStart"] + typedef["field_count"]):
            if i >= len(metadata.fieldDefs):
                break
            self._add_field(metadata.fieldDefs[i])
        method_start = self.method_rows
        for i in range(typedef["methodStart"],
                       typedef["methodStart"] + typedef["method_count"]):
            if i >= len(metadata.methodDefs):
                break
            self._add_method(metadata.methodDefs[i], i)

        self.image.rows[T_TYPEDEF][row][4] = ("tab", field_start)
        self.image.rows[T_TYPEDEF][row][5] = ("tab", method_start)

        # properties
        if typedef["property_count"] > 0:
            property_start = self.property_rows
            for i in range(typedef["propertyStart"],
                           typedef["propertyStart"] + typedef["property_count"]):
                if i >= len(metadata.propertyDefs):
                    break
                self._add_property(metadata.propertyDefs[i], typedef,
                                   typedef_index)
            if self.property_rows > property_start:
                self.image.add(T_PROPERTYMAP, ("tab", row), ("tab", property_start))

        # events
        if typedef["event_count"] > 0:
            event_start = self.event_rows
            for i in range(typedef["eventStart"],
                           typedef["eventStart"] + typedef["event_count"]):
                if i >= len(metadata.eventDefs):
                    break
                self._add_event(metadata.eventDefs[i])
            if self.event_rows > event_start:
                self.image.add(T_EVENTMAP, ("tab", row), ("tab", event_start))

    # ---------------- members ----------------
    def _add_field(self, field_def: Dict[str, Any]) -> None:
        metadata = self.context.metadata
        entry = self.context.executor.type_at(field_def["typeIndex"])
        flags = entry["attrs"] if entry is not None else consts.FIELD_ATTRIBUTE_PUBLIC
        signature = bytearray([0x06])
        signature += self._type_signature(field_def["typeIndex"])
        self.image.add(T_FIELD,
                       ("u16", flags & 0xFFFF),
                       ("str", self.image.strings.add(
                           metadata.get_string_from_index(field_def["nameIndex"]))),
                       ("blob", self.image.blobs.add(bytes(signature))))
        self.field_rows += 1

    def _add_method(self, method_def: Dict[str, Any], method_index: int) -> None:
        metadata = self.context.metadata
        parameter_start = self.param_rows
        for j in range(method_def["parameterCount"]):
            index = method_def["parameterStart"] + j
            if index >= len(metadata.parameterDefs):
                break
            parameter = metadata.parameterDefs[index]
            entry = self.context.executor.type_at(parameter["typeIndex"])
            flags = 0
            if entry is not None and entry["byref"] == 1:
                flags = consts.PARAM_ATTRIBUTE_IN
            self.image.add(T_PARAM,
                           ("u16", flags), ("u16", j + 1),
                           ("str", self.image.strings.add(
                               metadata.get_string_from_index(parameter["nameIndex"]))))
            self.param_rows += 1

        signature = self._method_signature(method_def)
        self.image.add(T_METHODDEF,
                       ("u32", 0), ("u16", 0),
                       ("u16", method_def["flags"]),
                       ("str", self.image.strings.add(
                           metadata.get_string_from_index(method_def["nameIndex"]))),
                       ("blob", self.image.blobs.add(signature)),
                       ("tab", parameter_start))
        method_row = self.method_rows
        self.method_rows += 1

        # generic parameters of the method
        if method_def["genericContainerIndex"] >= 0:
            container = self.context.executor._generic_container(
                method_def["genericContainerIndex"])
            if container is not None:
                for i in range(container["type_argc"]):
                    index = container["genericParameterStart"] + i
                    if index < len(metadata.genericParameters):
                        parameter = metadata.genericParameters[index]
                        self.image.add(
                            T_GENERICPARAM,
                            ("u16", parameter["num"]),
                            ("u16", parameter["flags"]),
                            ("coded", (T_METHODDEF, method_row)),
                            ("str", self.image.strings.add(
                                metadata.get_string_from_index(parameter["nameIndex"]))))

    def _add_property(self, property_def: Dict[str, Any],
                      typedef: Dict[str, Any], typedef_index: int) -> None:
        metadata = self.context.metadata
        signature = bytearray([0x08, 0x1C])   # HASTHIS, object
        getter = property_def["get"]
        if getter >= 0:
            method_index = typedef["methodStart"] + getter
            if method_index < len(metadata.methodDefs):
                entry = self.context.executor.type_at(
                    metadata.methodDefs[method_index]["returnType"])
                signature = bytearray([0x08])
                signature += self._type_signature_from_entry(entry)
        property_row = self.property_rows
        self.image.add(T_PROPERTY,
                       ("u16", property_def["attrs"] & 0xFFFF),
                       ("str", self.image.strings.add(
                           metadata.get_string_from_index(property_def["nameIndex"]))),
                       ("blob", self.image.blobs.add(bytes(signature))))
        self.property_rows += 1

        if getter >= 0:
            self._semantics(getter, typedef, typedef_index, 0x0002, property_row)
        setter = property_def["set"]
        if setter >= 0:
            self._semantics(setter, typedef, typedef_index, 0x0001, property_row)

    def _add_event(self, event_def: Dict[str, Any]) -> None:
        metadata = self.context.metadata
        typedef_index = self._typedef_from_type_index(event_def["typeIndex"])
        if typedef_index is not None:
            cell = self._type_def_or_ref(typedef_index)
        else:
            entry = self.context.executor.type_at(event_def["typeIndex"])
            if entry is None:
                cell = ("coded", (T_TYPEDEF, 0))
            else:
                cell = ("coded", (T_TYPESPEC, self._type_spec(entry)))
        event_row = self.event_rows
        self.image.add(T_EVENT, ("u16", 0),
                       ("str", self.image.strings.add(
                           metadata.get_string_from_index(event_def["nameIndex"]))),
                       cell)
        self.event_rows += 1
        return event_row

    def _semantics(self, method_offset: int, typedef: Dict[str, Any],
                   typedef_index: int, flag: int, target_row: int) -> None:
        if not (0 <= method_offset < typedef["method_count"]):
            return
        if typedef_index not in self.type_row:
            return
        base = self.image.rows[T_TYPEDEF][self.type_row[typedef_index]][5][1]
        self.image.add(T_METHODSEMANTICS,
                       ("u16", flag),
                       ("tab", base + method_offset),
                       ("coded", (T_PROPERTY, target_row)))

    # ---------------- signatures ----------------
    def _typedef_from_type_index(self, type_index: int) -> Optional[int]:
        if not self.context.full:
            return None
        return self.context.typedef_of_type_index.get(type_index)

    def _type_signature(self, type_index: int) -> bytes:
        if not self.context.full:
            return bytes([consts.TYPE_OBJECT])
        entry = self.context.executor.type_at(type_index)
        return self._type_signature_from_entry(entry)

    def _type_signature_from_entry(self, entry: Optional[Dict[str, Any]],
                                   depth: int = 0) -> bytes:
        if entry is None or depth > 10:
            return bytes([consts.TYPE_OBJECT])
        il2cpp = self.context.il2cpp
        kind = entry["type"]

        if kind == consts.TYPE_PTR:
            inner = il2cpp.get_il2cpp_type(entry["datapoint"])
            return bytes([consts.TYPE_PTR]) + self._type_signature_from_entry(inner,
                                                                             depth + 1)
        if kind == consts.TYPE_SZARRAY:
            inner = il2cpp.get_il2cpp_type(entry["datapoint"])
            return bytes([consts.TYPE_SZARRAY]) + self._type_signature_from_entry(
                inner, depth + 1)
        if kind == consts.TYPE_ARRAY:
            array_type = il2cpp.read_struct_at(entry["datapoint"], "ARRAY_TYPE")
            if array_type is None:
                return bytes([consts.TYPE_OBJECT])
            inner = il2cpp.get_il2cpp_type(array_type["etype"])
            rank = max(1, array_type["rank"])
            out = bytearray([consts.TYPE_ARRAY])
            out += self._type_signature_from_entry(inner, depth + 1)
            out += _compressed(rank)
            out += _compressed(0)      # sizes
            out += _compressed(0)      # loBounds
            return bytes(out)
        if kind in (consts.TYPE_VAR, consts.TYPE_MVAR):
            parameter = self.context.executor._get_generic_parameter(entry)
            index = parameter["num"] if parameter is not None else 0
            return bytes([kind]) + _compressed(index)
        if kind == consts.TYPE_GENERICINST:
            generic_class = il2cpp.read_struct_at(entry["datapoint"], "GENERIC_CLASS")
            out = bytearray([consts.TYPE_GENERICINST])
            definition = None
            if generic_class is not None:
                definition = self.context.executor._get_generic_class_type_definition(
                    generic_class)
            if definition is None:
                return bytes([consts.TYPE_OBJECT])
            typedef_index = self.context.typedef_index_of(id(definition))
            base_kind = (consts.TYPE_VALUETYPE
                         if ((definition["bitfield"] & 0x1) == 1)
                         else consts.TYPE_CLASS)
            out.append(base_kind)
            if typedef_index in self.type_row:
                out += _compressed(((self.type_row[typedef_index] + 1) << 2) | 0)
            else:
                out += _compressed(((self._type_ref(typedef_index) + 1) << 2) | 1)
            inst = il2cpp.read_struct_at(generic_class["class_inst"], "GENERIC_INST")
            argc = inst["type_argc"] if inst is not None else 0
            argc = max(0, min(argc, 64))
            out += _compressed(argc)
            if inst is not None and argc:
                pointers = il2cpp.read_ptr_array_at(inst["type_argv"], argc)
                for pointer in pointers:
                    out += self._type_signature_from_entry(
                        il2cpp.get_il2cpp_type(pointer), depth + 1)
            return bytes(out)
        if kind in (consts.TYPE_CLASS, consts.TYPE_VALUETYPE):
            typedef_index = self.context.typedef_of_type_index.get(
                self.context.index_of_type_entry.get(id(entry), -1))
            if typedef_index is None:
                definition = self.context.executor._get_type_definition(entry)
                typedef_index = self.context.typedef_index_of(id(definition)) if definition else -1
            if typedef_index is None or typedef_index < 0:
                return bytes([consts.TYPE_OBJECT])
            tag = 0 if typedef_index in self.type_row else 1
            if tag == 0:
                token = (self.type_row[typedef_index] + 1) << 2
            else:
                token = (self._type_ref(typedef_index) + 1) << 2
            return bytes([kind]) + _compressed(token | tag)

        # Primitive / simple element types share their encoding with ECMA-335.
        if kind in _ELEMENT_TYPES:
            return bytes([kind])
        return bytes([consts.TYPE_OBJECT])

    def _type_spec(self, entry: Dict[str, Any]) -> int:
        signature = self._type_signature_from_entry(entry)
        return self.image.add(T_TYPESPEC, ("blob", self.image.blobs.add(signature)))

    def _method_signature(self, method_def: Dict[str, Any]) -> bytes:
        metadata = self.context.metadata
        flags = 0
        if not (method_def["flags"] & consts.METHOD_ATTRIBUTE_STATIC):
            flags |= 0x20                       # HASTHIS
        if method_def["genericContainerIndex"] >= 0:
            container = self.context.executor._generic_container(
                method_def["genericContainerIndex"])
            if container is not None:
                flags |= 0x10                   # GENERIC
        out = bytearray([flags])
        if flags & 0x10:
            out += _compressed(container["type_argc"])
        out += self._type_signature(method_def["returnType"])
        out += _compressed(method_def["parameterCount"])
        for j in range(method_def["parameterCount"]):
            index = method_def["parameterStart"] + j
            if index >= len(metadata.parameterDefs):
                out += bytes([consts.TYPE_OBJECT])
                continue
            parameter = metadata.parameterDefs[index]
            entry = self.context.executor.type_at(parameter["typeIndex"])
            prefix = b""
            if entry is not None and entry["byref"] == 1:
                prefix = bytes([consts.TYPE_BYREF])
            out += prefix + self._type_signature(parameter["typeIndex"])
        return bytes(out)


def _synthetic_guid(seed: str) -> bytes:
    """Deterministic, non-cryptographic GUID so rebuilds are reproducible."""
    digest = 0
    for char in seed:
        digest = (digest * 131 + ord(char)) & 0xFFFFFFFFFFFFFFFF
    return digest.to_bytes(8, "little") + (digest ^ 0x9E3779B97F4A7C15).to_bytes(8, "little")


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------
def generate_dummy_dlls(executor: Executor, output_dir: str,
                        progress: Progress = None) -> List[Dict[str, Any]]:
    """Write one managed assembly per image into ``output_dir``."""
    os.makedirs(output_dir, exist_ok=True)
    context = _Context(executor)
    results: List[Dict[str, Any]] = []
    total = max(1, len(context.image_name))

    for image_index, image_name in enumerate(context.image_name):
        builder = _AssemblyBuilder(context, image_index)
        try:
            metadata_blob = builder.build()
        except Exception as error:
            results.append({"name": image_name, "ok": False, "error": str(error),
                            "path": None})
            continue
        assembly_name = context.assembly_name_of_image(image_index) or "Assembly"
        if not assembly_name.lower().endswith(".dll"):
            assembly_name += ".dll"
        path = os.path.join(output_dir, assembly_name)
        with open(path, "wb") as handle:
            handle.write(build_managed_pe(metadata_blob))
        results.append({"name": assembly_name, "ok": True, "error": None,
                        "path": path, "size": os.path.getsize(path)})
        if progress is not None:
            progress((image_index + 1) / total, "DummyDll - %s" % assembly_name)

    return results
