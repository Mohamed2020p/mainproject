"""
High-level queries over the parsed metadata + binary.

Everything the writers need in order to print human readable C# goes through
here: type names (including generics, arrays, pointers and by-ref), assembly /
image names, default values, and generic-instantiation names.

Two modes are supported:

``full``     the native binary was resolved, so ``Il2CppType`` entries are
             available and signatures are complete.
``metadata`` only ``global-metadata.dat`` was usable.  Names, tokens, flags and
             structure are still recovered; type signatures degrade to
             ``/* TypeIndex: N */`` markers.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

from . import consts
from .binary.base import Il2CppBinary
from .metadata import Metadata


class Executor:
    def __init__(self, metadata: Metadata, il2cpp: Optional[Il2CppBinary]):
        self.metadata = metadata
        self.il2cpp = il2cpp
        self.has_types = bool(il2cpp and il2cpp.types)
        self.custom_attribute_generators: List[int] = (
            il2cpp.custom_attribute_generators if il2cpp else [])

    # ------------------------------------------------------------------
    # type names
    # ------------------------------------------------------------------
    def type_at(self, index: int) -> Optional[Dict[str, Any]]:
        if not self.has_types:
            return None
        return self.il2cpp.type_at(index)

    def type_placeholder(self, index: int) -> str:
        return "/* TypeIndex: %d */" % index

    def get_type_name(self, il2cpp_type: Optional[Dict[str, Any]],
                      add_namespace: bool, is_nested: bool,
                      depth: int = 0) -> str:
        if il2cpp_type is None:
            return "object"
        if depth > 12:
            return "object"
        t = il2cpp_type["type"]
        binary = self.il2cpp
        assert binary is not None

        if t == consts.TYPE_ARRAY:
            array_type = binary.read_struct_at(il2cpp_type["datapoint"], "ARRAY_TYPE")
            if array_type is None:
                return "object[]"
            element = binary.get_il2cpp_type(array_type["etype"])
            rank = max(1, array_type["rank"])
            return "%s[%s]" % (self.get_type_name(element, add_namespace, False,
                                                 depth + 1),
                               "," * (rank - 1))

        if t == consts.TYPE_SZARRAY:
            element = binary.get_il2cpp_type(il2cpp_type["datapoint"])
            return "%s[]" % self.get_type_name(element, add_namespace, False, depth + 1)

        if t == consts.TYPE_PTR:
            element = binary.get_il2cpp_type(il2cpp_type["datapoint"])
            return "%s*" % self.get_type_name(element, add_namespace, False, depth + 1)

        if t in (consts.TYPE_VAR, consts.TYPE_MVAR):
            param = self._get_generic_parameter(il2cpp_type)
            if param is None:
                return "T"
            return self.metadata.get_string_from_index(param["nameIndex"])

        if t in (consts.TYPE_CLASS, consts.TYPE_VALUETYPE, consts.TYPE_GENERICINST):
            text = ""
            type_def: Optional[Dict[str, Any]]
            generic_class: Optional[Dict[str, Any]] = None

            if t == consts.TYPE_GENERICINST:
                generic_class = binary.read_struct_at(il2cpp_type["datapoint"],
                                                      "GENERIC_CLASS")
                type_def = self._get_generic_class_type_definition(generic_class)
            else:
                type_def = self._get_type_definition(il2cpp_type)

            if type_def is None:
                return "object"

            declaring = type_def["declaringTypeIndex"]
            if declaring != -1:
                parent_type = self.type_at(declaring)
                if parent_type is None:
                    text += "object"
                else:
                    text += self.get_type_name(parent_type, add_namespace, True,
                                               depth + 1)
                text += "."
            elif add_namespace:
                namespace = self.metadata.get_string_from_index(
                    type_def["namespaceIndex"])
                if namespace:
                    text += namespace + "."

            name = self.metadata.get_string_from_index(type_def["nameIndex"])
            tick = name.find("`")
            text += name[:tick] if tick != -1 else name

            if is_nested:
                return text

            if generic_class is not None:
                inst = binary.read_struct_at(generic_class["class_inst"], "GENERIC_INST")
                if inst is not None:
                    text += self._generic_inst_params(inst, depth)
            elif type_def["genericContainerIndex"] >= 0:
                container = self._generic_container(type_def["genericContainerIndex"])
                if container is not None:
                    text += self._generic_container_params(container)
            return text

        if t == consts.TYPE_FNPTR:
            return "IntPtr"

        return consts.TYPE_KEYWORDS.get(t, "object")

    def _generic_inst_params(self, inst: Dict[str, Any], depth: int = 0) -> str:
        binary = self.il2cpp
        assert binary is not None
        argc = inst["type_argc"]
        if argc <= 0 or argc > 64:
            return ""
        pointers = binary.read_ptr_array_at(inst["type_argv"], argc)
        names = []
        for pointer in pointers:
            entry = binary.get_il2cpp_type(pointer)
            names.append(self.get_type_name(entry, False, False, depth + 1))
        return "<%s>" % ", ".join(names)

    def _generic_container_params(self, container: Dict[str, Any]) -> str:
        names = []
        start = container["genericParameterStart"]
        for i in range(container["type_argc"]):
            index = start + i
            if 0 <= index < len(self.metadata.genericParameters):
                param = self.metadata.genericParameters[index]
                names.append(self.metadata.get_string_from_index(param["nameIndex"]))
        return "<%s>" % ", ".join(names)

    def get_type_def_name(self, type_def: Dict[str, Any], add_namespace: bool,
                          generic_parameter: bool, depth: int = 0) -> str:
        prefix = ""
        declaring = type_def["declaringTypeIndex"]
        if declaring != -1:
            parent = self.type_at(declaring)
            prefix = (self.get_type_name(parent, add_namespace, True, depth + 1)
                      if parent is not None else "object") + "."
        elif add_namespace:
            namespace = self.metadata.get_string_from_index(type_def["namespaceIndex"])
            if namespace:
                prefix = namespace + "."
        name = self.metadata.get_string_from_index(type_def["nameIndex"])
        if type_def["genericContainerIndex"] >= 0:
            tick = name.find("`")
            if tick != -1:
                name = name[:tick]
            if generic_parameter:
                container = self._generic_container(type_def["genericContainerIndex"])
                if container is not None:
                    name += self._generic_container_params(container)
        return prefix + name

    def _generic_container(self, index: int) -> Optional[Dict[str, Any]]:
        containers = self.metadata.genericContainers
        if 0 <= index < len(containers):
            return containers[index]
        return None

    def _get_type_definition(self, il2cpp_type: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        binary = self.il2cpp
        assert binary is not None
        if binary.version >= 27 and binary.is_dumped:
            offset = (il2cpp_type["datapoint"] - self.metadata.header["typeDefinitionsOffset"]
                      - binary.image_base)
            from .structs import struct_size
            unit = struct_size("TYPE_DEFINITION", self.metadata.version, 8)
            if unit and offset >= 0:
                index = offset // unit
                if 0 <= index < len(self.metadata.typeDefs):
                    return self.metadata.typeDefs[index]
            return None
        index = il2cpp_type["datapoint"]
        if isinstance(index, int) and 0 <= index < len(self.metadata.typeDefs):
            return self.metadata.typeDefs[index]
        return None

    def _get_generic_class_type_definition(
            self, generic_class: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if generic_class is None:
            return None
        binary = self.il2cpp
        assert binary is not None
        if binary.version >= 27:
            entry = binary.get_il2cpp_type(generic_class.get("type", 0))
            if entry is None:
                return None
            return self._get_type_definition(entry)
        index = generic_class.get("typeDefinitionIndex", -1)
        if index == -1 or index == 0xFFFFFFFF:
            return None
        if 0 <= index < len(self.metadata.typeDefs):
            return self.metadata.typeDefs[index]
        return None

    def _get_generic_parameter(self, il2cpp_type: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        index = il2cpp_type["datapoint"]
        params = self.metadata.genericParameters
        if isinstance(index, int) and 0 <= index < len(params):
            return params[index]
        return None

    # ------------------------------------------------------------------
    # method specs
    # ------------------------------------------------------------------
    def get_method_spec_name(self, spec_index: int) -> Tuple[str, str]:
        binary = self.il2cpp
        assert binary is not None
        spec = binary.method_specs[spec_index]
        definition_index = spec["methodDefinitionIndex"]
        if not (0 <= definition_index < len(self.metadata.methodDefs)):
            return ("object", "Method")
        method_def = self.metadata.methodDefs[definition_index]
        type_index = method_def["declaringType"]
        if not (0 <= type_index < len(self.metadata.typeDefs)):
            return ("object", "Method")
        type_def = self.metadata.typeDefs[type_index]
        type_name = self.get_type_def_name(type_def, False, False)
        class_index = spec["classIndexIndex"]
        if class_index != -1 and 0 <= class_index < len(binary.generic_insts):
            type_name += self._generic_inst_params(binary.generic_insts[class_index])
        method_name = self.metadata.get_string_from_index(method_def["nameIndex"])
        method_index = spec["methodIndexIndex"]
        if method_index != -1 and 0 <= method_index < len(binary.generic_insts):
            method_name += self._generic_inst_params(binary.generic_insts[method_index])
        return type_name, method_name

    # ------------------------------------------------------------------
    # constants / default values
    # ------------------------------------------------------------------
    def try_get_default_value(self, type_index: int, data_index: int
                              ) -> Tuple[bool, Any]:
        pointer = self.metadata.get_default_value_from_index(data_index)
        entry = self.type_at(type_index)
        if entry is None:
            return False, pointer
        ok, value = self._read_constant(entry["type"], pointer)
        return ok, value

    def _read_constant(self, type_value: int, pointer: int) -> Tuple[bool, Any]:
        data = self.metadata.data
        version = self.metadata.version
        try:
            if type_value == consts.TYPE_BOOLEAN:
                return True, bool(data[pointer])
            if type_value == consts.TYPE_U1:
                return True, data[pointer]
            if type_value == consts.TYPE_I1:
                value = data[pointer]
                return True, value - 256 if value > 127 else value
            if type_value == consts.TYPE_CHAR:
                return True, struct.unpack_from("<H", data, pointer)[0]
            if type_value == consts.TYPE_U2:
                return True, struct.unpack_from("<H", data, pointer)[0]
            if type_value == consts.TYPE_I2:
                return True, struct.unpack_from("<h", data, pointer)[0]
            if type_value == consts.TYPE_U4:
                if version >= 29:
                    return True, _read_compressed_uint(data, pointer)[0]
                return True, struct.unpack_from("<I", data, pointer)[0]
            if type_value == consts.TYPE_I4:
                if version >= 29:
                    return True, _read_compressed_int(data, pointer)[0]
                return True, struct.unpack_from("<i", data, pointer)[0]
            if type_value == consts.TYPE_U8:
                return True, struct.unpack_from("<Q", data, pointer)[0]
            if type_value == consts.TYPE_I8:
                return True, struct.unpack_from("<q", data, pointer)[0]
            if type_value == consts.TYPE_R4:
                return True, struct.unpack_from("<f", data, pointer)[0]
            if type_value == consts.TYPE_R8:
                return True, struct.unpack_from("<d", data, pointer)[0]
            if type_value == consts.TYPE_STRING:
                if version >= 29:
                    length, size = _read_compressed_int(data, pointer)
                    if length == -1:
                        return True, None
                    raw = data[pointer + size:pointer + size + length]
                    return True, raw.decode("utf-8", "replace")
                length = struct.unpack_from("<i", data, pointer)[0]
                if length < 0:
                    return True, None
                raw = data[pointer + 4:pointer + 4 + length]
                return True, raw.decode("utf-8", "replace")
        except (struct.error, IndexError):
            return False, pointer
        return False, pointer

    # ------------------------------------------------------------------
    # names
    # ------------------------------------------------------------------
    def image_name(self, index: int) -> str:
        image = self.metadata.imageDefs[index]
        return self.metadata.get_string_from_index(image["nameIndex"])

    def assembly_name(self, index: int) -> str:
        assembly = self.metadata.assemblyDefs[index]
        name_index = assembly["aname"]["nameIndex"]
        return self.metadata.get_string_from_index(name_index)

    def mode(self) -> str:
        return "full" if self.has_types else "metadata"


def _read_compressed_uint(data: bytes, offset: int) -> Tuple[int, int]:
    """ECMA-335 II.23.2 compressed unsigned integer -> ``(value, size)``."""
    first = data[offset]
    if (first & 0x80) == 0:
        return first, 1
    if (first & 0xC0) == 0x80:
        return ((first & 0x3F) << 8) | data[offset + 1], 2
    return (((first & 0x1F) << 24) | (data[offset + 1] << 16)
            | (data[offset + 2] << 8) | data[offset + 3]), 4


def _read_compressed_int(data: bytes, offset: int) -> Tuple[int, int]:
    """ECMA-335 II.23.2 compressed signed integer -> ``(value, size)``."""
    first = data[offset]
    if (first & 0x80) == 0:
        byte_len = 1
    elif (first & 0xC0) == 0x80:
        byte_len = 2
    else:
        byte_len = 4
    unsigned, size = _read_compressed_uint(data, offset)
    if (unsigned & 1) == 0:
        return unsigned >> 1, size
    value = unsigned >> 1
    if byte_len == 1:
        value -= 0x40
    elif byte_len == 2:
        value -= 0x2000
    else:
        value -= 0x10000000
    return value, size
