"""
Container / reader for the native IL2CPP binary.

The binary side of the dump supplies everything the metadata does not:

* the ``Il2CppType`` table, which turns the integer type indices stored in
  ``global-metadata.dat`` into real signatures (generics, arrays, pointers,
  by-ref parameters, enums ...),
* field offsets,
* method RVAs, and
* the generic-instantiation tables used to print ``GenericInstMethod`` blocks.

Finding those tables is the hard part: stripped IL2CPP binaries contain no
symbols, so ``CodeRegistration`` / ``MetadataRegistration`` have to be located
by pattern.  Two strategies are implemented, exactly as in the reference
implementation:

``SymbolSearch``   - use the exported ``g_CodeRegistration`` /
                     ``g_MetadataRegistration`` symbols when they are present.
``PlusSearch``     - heuristic pointer-graph walk (SectionHelper).
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .. import consts, structs


class BinaryError(Exception):
    """Raised when the native binary cannot be interpreted."""


class SearchSection:
    __slots__ = ("offset", "offset_end", "address", "address_end")

    def __init__(self, offset: int, offset_end: int, address: int, address_end: int):
        self.offset = offset
        self.offset_end = offset_end
        self.address = address
        self.address_end = address_end

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return ("<SearchSection file=0x%X-0x%X va=0x%X-0x%X>"
                % (self.offset, self.offset_end, self.address, self.address_end))


class Il2CppBinary:
    """Base class for every supported executable format."""

    format_name = "unknown"

    def __init__(self, data: bytes):
        # bytearray so that relocation fix-ups can be written back in place,
        # exactly like the reference implementation does.
        self.data = bytearray(data)
        self.version: float = 0.0
        self.is32bit = False
        self.image_base = 0
        self.is_dumped = False
        self.metadata_usages_count = 0

        self.types: List[Dict[str, Any]] = []
        self._type_dic: Dict[int, Dict[str, Any]] = {}
        self.method_pointers: List[int] = []
        self.generic_method_pointers: List[int] = []
        self.invoker_pointers: List[int] = []
        self.custom_attribute_generators: List[int] = []
        self.generic_inst_pointers: List[int] = []
        self.generic_insts: List[Dict[str, Any]] = []
        self.method_specs: List[Dict[str, Any]] = []
        self.generic_method_table: List[Dict[str, Any]] = []
        self.field_offsets: List[int] = []
        self.field_offsets_are_pointers = True
        self.code_gen_modules: Dict[str, Dict[str, Any]] = {}
        self.code_gen_module_method_pointers: Dict[str, List[int]] = {}
        self.code_registration = 0
        self.metadata_registration = 0
        self.code_registration_struct: Dict[str, Any] = {}
        self.metadata_registration_struct: Dict[str, Any] = {}
        self.method_definition_method_specs: Dict[int, List[Dict[str, Any]]] = {}
        self.method_spec_generic_method_pointers: Dict[int, int] = {}
        self.method_definition_pointers: Dict[int, int] = {}
        self.log: List[str] = []

    # ------------------------------------------------------------------
    # plumbing
    # ------------------------------------------------------------------
    @property
    def pointer_size(self) -> int:
        return 4 if self.is32bit else 8

    def set_properties(self, version: float, metadata_usages_count: int) -> None:
        self.version = version
        self.metadata_usages_count = metadata_usages_count

    def _say(self, message: str) -> None:
        self.log.append(message)

    def read_struct(self, offset: int, name: str) -> Dict[str, Any]:
        return structs.read_struct(bytes(self.data), offset, name,
                                   self.version, self.pointer_size)

    def read_struct_at(self, address: int, name: str) -> Optional[Dict[str, Any]]:
        try:
            return self.read_struct(self.map_vatr(address), name)
        except (EOFError, IndexError, ValueError):
            return None

    def read_ptr_array_at(self, address: int, count: int) -> List[int]:
        try:
            offset = self.map_vatr(address)
        except (ValueError, IndexError):
            return []
        fmt = "<%d%s" % (count, "I" if self.is32bit else "Q")
        size = count * self.pointer_size
        chunk = bytes(self.data[offset:offset + size])
        if len(chunk) < size:
            return [0] * count
        return list(struct.unpack(fmt, chunk))

    def read_ptr_array_at_file_offset(self, offset: int, count: int) -> List[int]:
        """Read ``count`` pointers straight from a *file* offset (already mapped).

        The section-helper search works in file offsets, so it must not go
        through :meth:`map_vatr` a second time.
        """
        size = count * self.pointer_size
        chunk = bytes(self.data[offset:offset + size])
        if len(chunk) < size or count <= 0:
            return [0] * max(count, 0)
        fmt = "<%d%s" % (count, "I" if self.is32bit else "Q")
        return list(struct.unpack(fmt, chunk))

    def read_int_array_at(self, address: int, count: int) -> List[int]:
        try:
            offset = self.map_vatr(address)
        except (ValueError, IndexError):
            return []
        size = count * 4
        chunk = bytes(self.data[offset:offset + size])
        if len(chunk) < size:
            return []
        return list(struct.unpack("<%di" % count, chunk))

    def read_string_to_null(self, offset: int, limit: int = 512) -> str:
        end = self.data.find(b"\x00", offset, offset + limit)
        if end < 0:
            end = offset + limit
        return bytes(self.data[offset:end]).decode("utf-8", "replace")

    # ------------------------------------------------------------------
    # address mapping - overridden per format
    # ------------------------------------------------------------------
    def map_vatr(self, address: int) -> int:
        raise NotImplementedError

    def map_rtva(self, offset: int) -> int:
        raise NotImplementedError

    def get_rva(self, pointer: int) -> int:
        return pointer

    def check_dump(self) -> bool:
        return False

    def sections(self) -> Tuple[List[SearchSection], List[SearchSection]]:
        raise NotImplementedError

    # ------------------------------------------------------------------
    # registration discovery
    # ------------------------------------------------------------------
    def symbol_search(self) -> bool:
        return False

    def plus_search(self, method_count: int, type_definitions_count: int,
                    image_count: int) -> bool:
        helper = _SectionHelper(self, method_count, type_definitions_count,
                                self.metadata_usages_count, image_count)
        code_registration = helper.find_code_registration()
        metadata_registration = helper.find_metadata_registration()
        return self.auto_plus_init(code_registration, metadata_registration)

    def auto_plus_init(self, code_registration: int, metadata_registration: int) -> bool:
        limit = 0x50000
        if code_registration:
            if self.version >= 24.2:
                probe = self.read_struct_at(code_registration, "CODE_REGISTRATION")
                if probe is None:
                    probe = {}
                if self.version == 31:
                    if probe.get("genericMethodPointersCount", 0) > limit:
                        code_registration -= self.pointer_size * 2
                    else:
                        self.version = 29
                        self._say("Changed il2cpp version to 29")
                if self.version == 29:
                    if probe.get("genericMethodPointersCount", 0) > limit:
                        self.version = 29.1
                        code_registration -= self.pointer_size * 2
                        self._say("Changed il2cpp version to 29.1")
                if self.version == 27:
                    if probe.get("reversePInvokeWrapperCount", 0) > limit:
                        self.version = 27.1
                        code_registration -= self.pointer_size
                        self._say("Changed il2cpp version to 27.1")
                if self.version == 24.4:
                    code_registration -= self.pointer_size * 2
                    if probe.get("reversePInvokeWrapperCount", 0) > limit:
                        self.version = 24.5
                        code_registration -= self.pointer_size
                        self._say("Changed il2cpp version to 24.5")
                if self.version == 24.2 and probe.get("interopDataCount", 0) == 0:
                    self.version = 24.3
                    code_registration -= self.pointer_size * 2
                    self._say("Changed il2cpp version to 24.3")

        self._say("CodeRegistration     : 0x%X" % code_registration)
        self._say("MetadataRegistration : 0x%X" % metadata_registration)

        if code_registration and metadata_registration:
            self.init(code_registration, metadata_registration)
            return True
        return False

    # ------------------------------------------------------------------
    # initialisation
    # ------------------------------------------------------------------
    def init(self, code_registration: int, metadata_registration: int) -> None:
        limit = 0x50000
        self.code_registration = code_registration
        self.metadata_registration = metadata_registration

        code_reg = self.read_struct_at(code_registration, "CODE_REGISTRATION")
        if code_reg is None:
            raise BinaryError("Could not read Il2CppCodeRegistration.")

        if self.version == 27 and code_reg.get("invokerPointersCount", 0) > limit:
            self.version = 27.1
            self._say("Changed il2cpp version to 27.1")
            code_reg = self.read_struct_at(code_registration, "CODE_REGISTRATION") or code_reg

        if self.version == 24.4 and code_reg.get("invokerPointersCount", 0) > limit:
            self.version = 24.5
            self._say("Changed il2cpp version to 24.5")
            code_reg = self.read_struct_at(code_registration, "CODE_REGISTRATION") or code_reg

        if self.version == 24.2 and code_reg.get("codeGenModules", 0) == 0:
            self.version = 24.3
            self._say("Changed il2cpp version to 24.3")
            code_reg = self.read_struct_at(code_registration, "CODE_REGISTRATION") or code_reg

        meta_reg = self.read_struct_at(metadata_registration, "METADATA_REGISTRATION")
        if meta_reg is None:
            raise BinaryError("Could not read Il2CppMetadataRegistration.")

        self.code_registration_struct = code_reg
        self.metadata_registration_struct = meta_reg

        self.generic_method_pointers = self.read_ptr_array_at(
            code_reg.get("genericMethodPointers", 0),
            _clamp_count(code_reg.get("genericMethodPointersCount", 0)))
        self.invoker_pointers = self.read_ptr_array_at(
            code_reg.get("invokerPointers", 0),
            _clamp_count(code_reg.get("invokerPointersCount", 0)))

        if self.version < 27:
            self.custom_attribute_generators = self.read_ptr_array_at(
                code_reg.get("customAttributeGenerators", 0),
                _clamp_count(code_reg.get("customAttributeCount", 0)))

        self.generic_inst_pointers = self.read_ptr_array_at(
            meta_reg.get("genericInsts", 0),
            _clamp_count(meta_reg.get("genericInstsCount", 0)))
        self.generic_insts = []
        for pointer in self.generic_inst_pointers:
            item = self.read_struct_at(pointer, "GENERIC_INST")
            if item is not None:
                self.generic_insts.append(item)

        self._load_field_offsets(meta_reg)
        self._load_types(meta_reg)
        self._load_code_gen_modules(code_reg)
        self._load_generic_method_table(meta_reg)

    def _load_field_offsets(self, meta_reg: Dict[str, Any]) -> None:
        count = _clamp_count(meta_reg.get("fieldOffsetsCount", 0))
        self.field_offsets_are_pointers = self.version > 21
        if self.version == 21:
            try:
                offset = self.map_vatr(meta_reg["fieldOffsets"])
                probe = list(struct.unpack("<6I", bytes(self.data[offset:offset + 24])))
                self.field_offsets_are_pointers = (
                    probe[0] == 0 and probe[1] == 0 and probe[2] == 0
                    and probe[3] == 0 and probe[4] == 0 and probe[5] > 0)
            except Exception:
                pass
        if self.field_offsets_are_pointers:
            self.field_offsets = self.read_ptr_array_at(meta_reg.get("fieldOffsets", 0), count)
        else:
            self.field_offsets = [x & 0xFFFFFFFF for x in self.read_int_array_at(
                meta_reg.get("fieldOffsets", 0), count)]

    def _load_types(self, meta_reg: Dict[str, Any]) -> None:
        count = _clamp_count(meta_reg.get("typesCount", 0))
        pointers = self.read_ptr_array_at(meta_reg.get("types", 0), count)
        self.types = []
        self._type_dic = {}
        for pointer in pointers:
            entry = self.read_struct_at(pointer, "IL2CPP_TYPE")
            if entry is None:
                entry = {"datapoint": 0, "bits": 0}
            entry.update(_decode_il2cpp_type_bits(entry["bits"], self.version))
            self.types.append(entry)
            self._type_dic[pointer] = entry

    def _load_code_gen_modules(self, code_reg: Dict[str, Any]) -> None:
        if self.version < 24.2:
            self.method_pointers = self.read_ptr_array_at(
                code_reg.get("methodPointers", 0),
                _clamp_count(code_reg.get("methodPointersCount", 0)))
            return

        count = _clamp_count(code_reg.get("codeGenModulesCount", 0))
        module_pointers = self.read_ptr_array_at(code_reg.get("codeGenModules", 0), count)
        self.code_gen_modules = {}
        self.code_gen_module_method_pointers = {}
        for module_pointer in module_pointers:
            module = self.read_struct_at(module_pointer, "CODEGEN_MODULE")
            if module is None:
                continue
            try:
                name_offset = self.map_vatr(module["moduleName"])
            except (ValueError, IndexError):
                continue
            name = self.read_string_to_null(name_offset)
            if not name:
                continue
            self.code_gen_modules[name] = module
            self.code_gen_module_method_pointers[name] = self.read_ptr_array_at(
                module["methodPointers"], _clamp_count(module["methodPointerCount"]))

    def _load_generic_method_table(self, meta_reg: Dict[str, Any]) -> None:
        try:
            table_offset = self.map_vatr(meta_reg.get("genericMethodTable", 0))
            specs_offset = self.map_vatr(meta_reg.get("methodSpecs", 0))
        except (ValueError, IndexError):
            return
        table_count = _clamp_count(meta_reg.get("genericMethodTableCount", 0))
        spec_count = _clamp_count(meta_reg.get("methodSpecsCount", 0))
        if table_count == 0 or spec_count == 0:
            return
        self.generic_method_table = structs.read_struct_array(
            bytes(self.data), table_offset, "GENERIC_METHOD_FUNCTIONS_DEFINITIONS",
            table_count, self.version, self.pointer_size)
        self.method_specs = structs.read_struct_array(
            bytes(self.data), specs_offset, "METHOD_SPEC",
            spec_count, self.version, self.pointer_size)

        self.method_definition_method_specs = {}
        self.method_spec_generic_method_pointers = {}
        for index, table in enumerate(self.generic_method_table):
            spec_index = table["genericMethodIndex"]
            if not (0 <= spec_index < len(self.method_specs)):
                continue
            spec = self.method_specs[spec_index]
            definition_index = spec["methodDefinitionIndex"]
            self.method_definition_method_specs.setdefault(definition_index, []).append(spec)
            method_index = table["indices"].get("methodIndex", 0)
            pointer = 0
            if 0 <= method_index < len(self.generic_method_pointers):
                pointer = self.generic_method_pointers[method_index]
            self.method_spec_generic_method_pointers[spec_index] = pointer
            if pointer:
                self.method_definition_pointers[definition_index] = pointer

    # ------------------------------------------------------------------
    # queries used by the writers
    # ------------------------------------------------------------------
    def get_il2cpp_type(self, pointer: int) -> Optional[Dict[str, Any]]:
        return self._type_dic.get(pointer)

    def type_at(self, index: int) -> Optional[Dict[str, Any]]:
        if 0 <= index < len(self.types):
            return self.types[index]
        return None

    def get_method_pointer(self, image_name: str, method_def: Dict[str, Any],
                           method_index: int = -1) -> int:
        pointer = 0
        if self.version >= 24.2:
            pointers = self.code_gen_module_method_pointers.get(image_name)
            if pointers:
                index = (method_def["token"] & 0x00FFFFFF) - 1
                if 0 <= index < len(pointers):
                    pointer = pointers[index]
        else:
            method_def_index = method_def.get("methodIndex", -1)
            if method_def_index is not None and method_def_index >= 0 \
                    and method_def_index < len(self.method_pointers):
                pointer = self.method_pointers[method_def_index]

        # Generic / inflated methods are not in the per-module pointer arrays;
        # resolve them through the generic method table instead.
        if pointer == 0 and method_index >= 0:
            pointer = self.method_definition_pointers.get(method_index, 0)
        return pointer

    def get_field_offset_from_index(self, type_index: int, field_index_in_type: int,
                                    field_index: int, is_value_type: bool,
                                    is_static: bool) -> int:
        try:
            offset = -1
            if self.field_offsets_are_pointers:
                if 0 <= type_index < len(self.field_offsets):
                    pointer = self.field_offsets[type_index]
                    if pointer > 0:
                        position = self.map_vatr(pointer) + 4 * field_index_in_type
                        offset = struct.unpack_from("<i", self.data, position)[0]
            else:
                if 0 <= field_index < len(self.field_offsets):
                    offset = self.field_offsets[field_index]
            if offset > 0 and is_value_type and not is_static:
                offset -= 8 if self.is32bit else 16
            return offset
        except Exception:
            return -1


def _decode_il2cpp_type_bits(bits: int, version: float) -> Dict[str, int]:
    attrs = bits & 0xFFFF
    type_value = (bits >> 16) & 0xFF
    if version >= 27.2:
        num_mods = (bits >> 24) & 0x1F
        byref = (bits >> 29) & 1
        pinned = (bits >> 30) & 1
        valuetype = bits >> 31
    else:
        num_mods = (bits >> 24) & 0x3F
        byref = (bits >> 30) & 1
        pinned = bits >> 31
        valuetype = 0
    return {
        "attrs": attrs,
        "type": type_value,
        "num_mods": num_mods,
        "byref": byref,
        "pinned": pinned,
        "valuetype": valuetype,
    }


def _clamp_count(count: Any, limit: int = 4_000_000) -> int:
    try:
        count = int(count)
    except (TypeError, ValueError):
        return 0
    if count < 0:
        return 0
    return min(count, limit)


class _SectionHelper:
    """Port of Il2CppDumper's ``SectionHelper``."""

    FEATURE_BYTES = b"mscorlib.dll\x00"

    def __init__(self, binary: Il2CppBinary, method_count: int,
                 type_definitions_count: int, metadata_usages_count: int,
                 image_count: int):
        self.binary = binary
        self.method_count = method_count
        self.type_definitions_count = type_definitions_count
        self.metadata_usages_count = metadata_usages_count
        self.image_count = image_count
        self.pointer_in_exec = False

        exec_sections, data_sections = binary.sections()
        self.exec = exec_sections
        self.data = data_sections
        self.bss = data_sections

    # ---------------- code registration ----------------
    def find_code_registration(self) -> int:
        if self.binary.version < 24.2:
            return self._find_code_registration_old()
        found = self._find_code_registration_2019(self.exec)
        if found:
            self.pointer_in_exec = True
            return found
        return self._find_code_registration_2019(self.data)

    def _find_code_registration_old(self) -> int:
        ptr = self.binary.pointer_size
        for section in self.data:
            position = section.offset
            while position + 2 * ptr <= section.offset_end:
                value = _read_intptr(self.binary.data, position, self.binary.is32bit)
                if value == self.method_count:
                    try:
                        pointer = self.binary.map_vatr(
                            _read_uintptr(self.binary.data, position + ptr,
                                          self.binary.is32bit))
                        if self._check_pointer_range_data_ra(pointer):
                            pointers = self.binary.read_ptr_array_at_file_offset(
                                pointer, self.method_count)
                            if pointers and self._check_pointer_range_exec_va(pointers):
                                return position - section.offset + section.address
                    except Exception:
                        pass
                position += ptr
        return 0

    def _find_code_registration_2019(self, sections: Sequence[SearchSection]) -> int:
        for section in sections:
            blob = bytes(self.binary.data[section.offset:section.offset_end])
            start = 0
            while True:
                index = blob.find(self.FEATURE_BYTES, start)
                if index < 0:
                    break
                start = index + 1
                dllva = index + section.address
                for refva in self._find_references(dllva):
                    for refva2 in self._find_references(refva):
                        if self.binary.version >= 27:
                            for i in range(self.image_count - 1, -1, -1):
                                for refva3 in self._find_references(
                                        refva2 - i * self.binary.pointer_size):
                                    if self._image_count_matches(refva3):
                                        if self.binary.version >= 29:
                                            return refva3 - self.binary.pointer_size * 14
                                        return refva3 - self.binary.pointer_size * 13
                        else:
                            for i in range(self.image_count):
                                for refva3 in self._find_references(
                                        refva2 - i * self.binary.pointer_size):
                                    return refva3 - self.binary.pointer_size * 13
        return 0

    def _image_count_matches(self, refva3: int) -> bool:
        try:
            offset = self.binary.map_vatr(refva3 - self.binary.pointer_size)
            value = _read_intptr(self.binary.data, offset, self.binary.is32bit)
        except Exception:
            return False
        return value == self.image_count

    # ---------------- metadata registration ----------------
    def find_metadata_registration(self) -> int:
        if self.binary.version < 19:
            return 0
        if self.binary.version >= 27:
            return self._find_metadata_registration_v21()
        return self._find_metadata_registration_old()

    def _find_metadata_registration_old(self) -> int:
        ptr = self.binary.pointer_size
        for section in self.data:
            end = min(section.offset_end, len(self.binary.data)) - ptr
            position = section.offset
            while position < end:
                if _read_intptr(self.binary.data, position,
                                self.binary.is32bit) == self.type_definitions_count:
                    try:
                        pointer = self.binary.map_vatr(_read_uintptr(
                            self.binary.data, position + ptr * 3, self.binary.is32bit))
                        if self._check_pointer_range_data_ra(pointer):
                            pointers = self.binary.read_ptr_array_at_file_offset(
                                pointer, self.metadata_usages_count)
                            if self._check_pointer_range_bss_va(pointers):
                                return (position - ptr * 12 - section.offset
                                        + section.address)
                    except Exception:
                        pass
                position += ptr
        return 0

    def _find_metadata_registration_v21(self) -> int:
        ptr = self.binary.pointer_size
        for section in self.data:
            end = min(section.offset_end, len(self.binary.data)) - ptr
            position = section.offset
            while position + 4 * ptr <= end:
                if _read_intptr(self.binary.data, position,
                                self.binary.is32bit) == self.type_definitions_count:
                    if _read_intptr(self.binary.data, position + ptr * 2,
                                    self.binary.is32bit) == self.type_definitions_count:
                        try:
                            pointer = self.binary.map_vatr(_read_uintptr(
                                self.binary.data, position + ptr * 3,
                                self.binary.is32bit))
                            if self._check_pointer_range_data_ra(pointer):
                                pointers = self.binary.read_ptr_array_at_file_offset(
                                    pointer, self.type_definitions_count)
                                if pointers:
                                    ok = (self._check_pointer_range_exec_va(pointers)
                                          if self.pointer_in_exec
                                          else self._check_pointer_range_data_va(pointers))
                                    if ok:
                                        return (position - ptr * 10 - section.offset
                                                + section.address)
                        except Exception:
                            pass
                position += ptr
        return 0

    # ---------------- helpers ----------------
    def _find_references(self, address: int) -> List[int]:
        """Return every pointer-aligned VA in a data section holding ``address``."""
        results: List[int] = []
        if address <= 0:
            return results
        ptr = self.binary.pointer_size
        needle = address.to_bytes(ptr, "little")
        total = len(self.binary.data)
        for section in self.data:
            start = section.offset
            stop = min(section.offset_end, total) - ptr
            cursor = start
            while True:
                index = self.binary.data.find(needle, cursor, stop + ptr)
                if index < 0 or index > stop:
                    break
                if (index - start) % ptr == 0:
                    results.append(index - section.offset + section.address)
                cursor = index + ptr
        return results

    def _check_pointer_range_data_ra(self, pointer: int) -> bool:
        return any(s.offset <= pointer <= s.offset_end for s in self.data)

    def _check_pointer_range_exec_va(self, pointers: Sequence[int]) -> bool:
        return all(any(s.address <= p <= s.address_end for s in self.exec)
                   for p in pointers)

    def _check_pointer_range_data_va(self, pointers: Sequence[int]) -> bool:
        return all(any(s.address <= p <= s.address_end for s in self.data)
                   for p in pointers)

    def _check_pointer_range_bss_va(self, pointers: Sequence[int]) -> bool:
        return all(any(s.address <= p <= s.address_end for s in self.bss)
                   for p in pointers)


def _read_uintptr(data: bytes, offset: int, is32bit: bool) -> int:
    size = 4 if is32bit else 8
    return int.from_bytes(data[offset:offset + size], "little")


def _read_intptr(data: bytes, offset: int, is32bit: bool) -> int:
    size = 4 if is32bit else 8
    value = int.from_bytes(data[offset:offset + size], "little")
    if value >= (1 << (size * 8 - 1)):
        value -= (1 << (size * 8))
    return value
