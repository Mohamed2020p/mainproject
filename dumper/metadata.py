"""
Reader for Unity's ``global-metadata.dat``.

This is the half of an IL2CPP dump that carries every name in the game: image
(assembly) names, namespaces, type names, method names, parameter names,
property names, event names, generic parameters and string literals.  It is a
flat, self-describing blob: a header of ``(offset, size)`` pairs followed by
arrays of fixed-size records.

Parsing is deliberately independent of the native binary, which means a
meaningful ``dump.cs`` can be produced even when the ``libil2cpp.so`` is missing
or protected - the binary is only needed to resolve full type signatures,
field offsets and method RVAs.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

from . import consts, structs


class MetadataError(Exception):
    """Raised when the metadata blob is not a readable global-metadata.dat."""


class Metadata:
    """Parsed ``global-metadata.dat``."""

    def __init__(self, data: bytes):
        self.data = data
        self._string_cache: Dict[int, str] = {}
        self._parse()

    # ------------------------------------------------------------------
    # header
    # ------------------------------------------------------------------
    def _parse(self) -> None:
        data = self.data
        if len(data) < 8:
            raise MetadataError("Metadata file is too small to be valid.")

        sanity = int.from_bytes(data[0:4], "little")
        if sanity != consts.METADATA_SANITY:
            raise MetadataError(
                "Not a valid metadata file (bad sanity 0x%08X). "
                "The file may be encrypted or obfuscated." % sanity
            )

        version = int.from_bytes(data[4:8], "little", signed=True)
        if version < 0 or version > 1000:
            raise MetadataError("Not a valid metadata file (bad version field).")
        if version < consts.MIN_METADATA_VERSION or version > consts.MAX_METADATA_VERSION:
            raise MetadataError(
                "Unsupported metadata version %d (supported: %d - %d)."
                % (version, consts.MIN_METADATA_VERSION, consts.MAX_METADATA_VERSION)
            )

        self.version: float = float(version)
        self.header = structs.read_struct(data, 0, "GLOBAL_METADATA_HEADER", self.version, 8)

        # Unity 2019.x shipped several incompatible layouts that all report
        # version 24.  Disambiguate them the same way the reference dumper does.
        if version == 24:
            if self.header["stringLiteralOffset"] == 264:
                self.version = 24.2
                self.header = structs.read_struct(
                    data, 0, "GLOBAL_METADATA_HEADER", self.version, 8)
            else:
                probes = self._read_array(
                    self.header["imagesOffset"], self.header["imagesSize"],
                    "IMAGE_DEFINITION")
                if any(x["token"] != 1 for x in probes):
                    self.version = 24.1

        image_defs = self._read_array(
            self.header["imagesOffset"], self.header["imagesSize"], "IMAGE_DEFINITION")

        if self.version == 24.2 and self.header["assembliesSize"] // 68 < len(image_defs):
            self.version = 24.4

        v241_plus = False
        if self.version == 24.1 and self.header["assembliesSize"] // 64 == len(image_defs):
            v241_plus = True
        if v241_plus:
            self.version = 24.4

        assembly_defs = self._read_array(
            self.header["assembliesOffset"], self.header["assembliesSize"],
            "ASSEMBLY_DEFINITION")

        if v241_plus:
            self.version = 24.1

        self.imageDefs = image_defs
        self.assemblyDefs = assembly_defs
        self.typeDefs = self._read_array(
            self.header["typeDefinitionsOffset"], self.header["typeDefinitionsSize"],
            "TYPE_DEFINITION")
        self.methodDefs = self._read_array(
            self.header["methodsOffset"], self.header["methodsSize"], "METHOD_DEFINITION")
        self.parameterDefs = self._read_array(
            self.header["parametersOffset"], self.header["parametersSize"],
            "PARAMETER_DEFINITION")
        self.fieldDefs = self._read_array(
            self.header["fieldsOffset"], self.header["fieldsSize"], "FIELD_DEFINITION")

        field_defaults = self._read_array(
            self.header["fieldDefaultValuesOffset"],
            self.header["fieldDefaultValuesSize"], "FIELD_DEFAULT_VALUE")
        parameter_defaults = self._read_array(
            self.header["parameterDefaultValuesOffset"],
            self.header["parameterDefaultValuesSize"], "PARAMETER_DEFAULT_VALUE")

        self.fieldDefaultValues: Dict[int, Dict[str, Any]] = {}
        for item in field_defaults:
            self.fieldDefaultValues.setdefault(item["fieldIndex"], item)
        self.parameterDefaultValues: Dict[int, Dict[str, Any]] = {}
        for item in parameter_defaults:
            self.parameterDefaultValues.setdefault(item["parameterIndex"], item)

        self.propertyDefs = self._read_array(
            self.header["propertiesOffset"], self.header["propertiesSize"],
            "PROPERTY_DEFINITION")
        self.eventDefs = self._read_array(
            self.header["eventsOffset"], self.header["eventsSize"], "EVENT_DEFINITION")
        self.genericContainers = self._read_array(
            self.header["genericContainersOffset"], self.header["genericContainersSize"],
            "GENERIC_CONTAINER")
        self.genericParameters = self._read_array(
            self.header["genericParametersOffset"], self.header["genericParametersSize"],
            "GENERIC_PARAMETER")
        self.stringLiterals = self._read_array(
            self.header["stringLiteralOffset"], self.header["stringLiteralSize"],
            "STRING_LITERAL")

        self.interfaceIndices = self._read_int_array(
            self.header["interfacesOffset"], self.header["interfacesSize"])
        self.nestedTypeIndices = self._read_int_array(
            self.header["nestedTypesOffset"], self.header["nestedTypesSize"])
        self.constraintIndices = self._read_int_array(
            self.header["genericParameterConstraintsOffset"],
            self.header["genericParameterConstraintsSize"])
        self.vtableMethods = self._read_uint_array(
            self.header["vtableMethodsOffset"], self.header["vtableMethodsSize"])

        self.attributeTypeRanges: List[Dict[str, Any]] = []
        self.attributeTypes: List[int] = []
        self.attributeDataRanges: List[Dict[str, Any]] = []

        if self.version > 16:
            self.fieldRefs = self._read_array(
                self.header["fieldRefsOffset"], self.header["fieldRefsSize"], "FIELD_REF")
            if self.version < 27:
                self.metadataUsageLists = self._read_array(
                    self.header["metadataUsageListsOffset"],
                    self.header["metadataUsageListsCount"], "METADATA_USAGE_LIST",
                    by_count=True)
                self.metadataUsagePairs = self._read_array(
                    self.header["metadataUsagePairsOffset"],
                    self.header["metadataUsagePairsCount"], "METADATA_USAGE_PAIR",
                    by_count=True)
            else:
                self.metadataUsageLists = []
                self.metadataUsagePairs = []
        else:
            self.fieldRefs = []
            self.metadataUsageLists = []
            self.metadataUsagePairs = []

        if 20 < self.version < 29:
            self.attributeTypeRanges = self._read_array(
                self.header["attributesInfoOffset"], self.header["attributesInfoCount"],
                "CUSTOM_ATTRIBUTE_TYPE_RANGE", by_count=True)
            self.attributeTypes = self._read_int_array(
                self.header["attributeTypesOffset"], self.header["attributeTypesCount"])

        if self.version >= 29:
            self.attributeDataRanges = self._read_array(
                self.header["attributeDataRangeOffset"],
                self.header["attributeDataRangeSize"], "CUSTOM_ATTRIBUTE_DATA_RANGE")

        if self.version <= 24.1 and self.header.get("rgctxEntriesCount", 0) > 0:
            self.rgctxEntries = self._read_array(
                self.header["rgctxEntriesOffset"], self.header["rgctxEntriesCount"],
                "RGCTX_DEFINITION", by_count=True)
        else:
            self.rgctxEntries = []

        # token -> index maps, mirroring attributeTypeRangesDic
        self.attributeIndexByImage: List[Dict[int, int]] = []
        if self.version > 24:
            source = (self.attributeDataRanges if self.version >= 29
                      else self.attributeTypeRanges)
            for image in self.imageDefs:
                mapping: Dict[int, int] = {}
                start = image.get("customAttributeStart", 0)
                count = image.get("customAttributeCount", 0)
                for i in range(start, start + count):
                    if 0 <= i < len(source):
                        mapping[source[i]["token"]] = i
                self.attributeIndexByImage.append(mapping)

        self.metadataUsagesCount = self._process_metadata_usage()

    # ------------------------------------------------------------------
    # low level helpers
    # ------------------------------------------------------------------
    def _read_array(self, offset: int, size_or_count: int, name: str,
                    by_count: bool = False) -> List[Dict[str, Any]]:
        if offset <= 0 or size_or_count <= 0:
            return []
        if by_count:
            count = size_or_count
        else:
            unit = structs.struct_size(name, self.version, 8)
            if unit == 0:
                return []
            count = size_or_count // unit
        try:
            return structs.read_struct_array(self.data, offset, name, count,
                                             self.version, 8)
        except (EOFError, IndexError):
            return []

    def _read_int_array(self, offset: int, size: int) -> List[int]:
        return self._read_uint_array(offset, size, signed=True)

    def _read_uint_array(self, offset: int, size: int,
                         signed: bool = False) -> List[int]:
        if offset <= 0 or size <= 0:
            return []
        count = size // 4
        chunk = self.data[offset:offset + count * 4]
        if len(chunk) < count * 4:
            count = len(chunk) // 4
            chunk = chunk[:count * 4]
        fmt = "<%d%s" % (count, "i" if signed else "I")
        return list(struct.unpack(fmt, chunk))

    def _process_metadata_usage(self) -> int:
        """Compute ``metadataUsagesCount`` the same way the reference dumper does."""
        if self.version >= 27 or not self.metadataUsagePairs:
            return 0
        usage: Dict[int, Dict[int, int]] = {i: {} for i in range(1, 7)}
        for entry in self.metadataUsageLists:
            for i in range(entry["count"]):
                offset = entry["start"] + i
                if offset >= len(self.metadataUsagePairs):
                    continue
                pair = self.metadataUsagePairs[offset]
                kind = (pair["encodedSourceIndex"] & 0xE0000000) >> 29
                decoded = self.get_decoded_method_index(pair["encodedSourceIndex"])
                usage.setdefault(kind, {})[pair["destinationIndex"]] = decoded
        self.metadataUsageDic = usage
        highest = 0
        for table in usage.values():
            if table:
                highest = max(highest, max(table.keys()))
        return highest + 1

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def get_string_from_index(self, index: int) -> str:
        index = int(index)
        if index in self._string_cache:
            return self._string_cache[index]
        start = self.header["stringOffset"] + index
        end = self.data.find(b"\x00", start)
        if end < 0:
            end = len(self.data)
        try:
            value = self.data[start:end].decode("utf-8", "replace")
        except Exception:
            value = ""
        self._string_cache[index] = value
        return value

    def get_string_literal_from_index(self, index: int) -> str:
        literal = self.stringLiterals[index]
        start = self.header["stringLiteralDataOffset"] + literal["dataIndex"]
        raw = self.data[start:start + literal["length"]]
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("utf-8", "replace")

    def get_default_value_from_index(self, index: int) -> int:
        return self.header["fieldAndParameterDefaultValueDataOffset"] + index

    def get_field_default_value(self, index: int) -> Optional[Dict[str, Any]]:
        return self.fieldDefaultValues.get(index)

    def get_parameter_default_value(self, index: int) -> Optional[Dict[str, Any]]:
        return self.parameterDefaultValues.get(index)

    def get_decoded_method_index(self, index: int) -> int:
        if self.version >= 27:
            return (index & 0x1FFFFFFE) >> 1
        return index & 0x1FFFFFFF

    def get_custom_attribute_index(self, image_index: int, custom_attribute_index: int,
                                   token: int) -> int:
        if self.version > 24:
            if 0 <= image_index < len(self.attributeIndexByImage):
                return self.attributeIndexByImage[image_index].get(token, -1)
            return -1
        return custom_attribute_index

    @property
    def size(self) -> int:
        return len(self.data)

    # ------------------------------------------------------------------
    # diagnostics
    # ------------------------------------------------------------------
    def summary(self) -> Dict[str, Any]:
        return {
            "metadataVersion": self.version,
            "sizeBytes": len(self.data),
            "images": len(self.imageDefs),
            "assemblies": len(self.assemblyDefs),
            "types": len(self.typeDefs),
            "methods": len(self.methodDefs),
            "fields": len(self.fieldDefs),
            "parameters": len(self.parameterDefs),
            "properties": len(self.propertyDefs),
            "events": len(self.eventDefs),
            "genericContainers": len(self.genericContainers),
            "genericParameters": len(self.genericParameters),
            "stringLiterals": len(self.stringLiterals),
        }


def is_metadata_file(head: bytes) -> bool:
    """True when the leading bytes look like ``global-metadata.dat``."""
    if len(head) < 4:
        return False
    return int.from_bytes(head[0:4], "little") == consts.METADATA_SANITY
