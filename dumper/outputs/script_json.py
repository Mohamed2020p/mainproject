"""
``script.json`` - symbol / string information for IDA Pro and Ghidra.

Feed it to ``ida.py`` / ``ghidra.py`` (shipped by the reference dumper) to
rename every IL2CPP method inside the disassembly.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from ..executor import Executor

Progress = Optional[Callable[[float, str], None]]


def build_script_json(executor: Executor) -> Dict[str, Any]:
    metadata = executor.metadata
    il2cpp = executor.il2cpp
    result: Dict[str, Any] = {
        "ScriptMethod": [],
        "ScriptString": [],
        "ScriptMetadata": [],
        "ScriptMetadataMethod": [],
        "Addresses": [],
    }
    if il2cpp is None:
        return result

    addresses: List[int] = []
    script_methods: List[Dict[str, Any]] = []

    for image_index, image_def in enumerate(metadata.imageDefs):
        image_name = metadata.get_string_from_index(image_def["nameIndex"])
        type_end = image_def["typeStart"] + image_def["typeCount"]
        for type_index in range(image_def["typeStart"], type_end):
            if type_index >= len(metadata.typeDefs):
                break
            type_def = metadata.typeDefs[type_index]
            for i in range(type_def["methodStart"],
                           type_def["methodStart"] + type_def["method_count"]):
                if i >= len(metadata.methodDefs):
                    break
                method_def = metadata.methodDefs[i]
                pointer = il2cpp.get_method_pointer(image_name, method_def)
                if pointer == 0:
                    continue
                method_name = metadata.get_string_from_index(method_def["nameIndex"])
                type_name = executor.get_type_def_name(type_def, False, False)
                full_name = "%s$$%s" % (type_name, method_name)
                signature = _method_signature(executor, method_def)
                type_signature = _type_signature(executor, method_def)
                script_methods.append({
                    "Address": pointer,
                    "Name": full_name,
                    "Signature": signature,
                    "TypeSignature": type_signature,
                })
                addresses.append(pointer)

    result["ScriptMethod"] = script_methods
    result["Addresses"] = addresses
    result.update(_metadata_usages(executor))
    return result


def _method_signature(executor: Executor, method_def: Dict[str, Any]) -> str:
    if not executor.has_types:
        return ""
    metadata = executor.metadata
    return_type = executor.type_at(method_def["returnType"])
    parts = [executor.get_type_name(return_type, True, False),
             metadata.get_string_from_index(method_def["nameIndex"])]
    parameters = []
    for j in range(method_def["parameterCount"]):
        index = method_def["parameterStart"] + j
        if index >= len(metadata.parameterDefs):
            break
        parameter = metadata.parameterDefs[index]
        entry = executor.type_at(parameter["typeIndex"])
        parameters.append("%s %s" % (executor.get_type_name(entry, True, False),
                                     metadata.get_string_from_index(parameter["nameIndex"])))
    return "%s %s(%s)" % (parts[0], parts[1], ", ".join(parameters))


def _type_signature(executor: Executor, method_def: Dict[str, Any]) -> str:
    if not executor.has_types:
        return ""
    metadata = executor.metadata
    return_type = executor.type_at(method_def["returnType"])
    head = executor.get_type_name(return_type, True, False)
    parameters = []
    for j in range(method_def["parameterCount"]):
        index = method_def["parameterStart"] + j
        if index >= len(metadata.parameterDefs):
            break
        entry = executor.type_at(metadata.parameterDefs[index]["typeIndex"])
        parameters.append(executor.get_type_name(entry, True, False))
    return "%s (*%s)(%s)" % (head,
                             metadata.get_string_from_index(method_def["nameIndex"]),
                             ", ".join(["void*"] + parameters))


def _metadata_usages(executor: Executor) -> Dict[str, Any]:
    """Resolve the metadata-usage table into strings / metadata / method refs."""
    il2cpp = executor.il2cpp
    metadata = executor.metadata
    out: Dict[str, Any] = {"ScriptString": [], "ScriptMetadata": [],
                           "ScriptMetadataMethod": []}
    if il2cpp is None:
        return out

    usage_kind_names = {
        1: "TypeInfo", 2: "Il2CppType", 3: "MethodDef", 4: "FieldInfo",
        5: "StringLiteral", 6: "MethodRef",
    }

    # Pre v27: the table is described inside global-metadata.dat.
    if metadata.version < 27 and getattr(metadata, "metadataUsageDic", None):
        usage_pointers = []
        count = metadata.metadataUsagesCount
        if count:
            struct = il2cpp.metadata_registration_struct
            usage_pointers = il2cpp.read_ptr_array_at(struct.get("metadataUsages", 0), count)
        for kind, table in metadata.metadataUsageDic.items():
            for destination, index in table.items():
                if destination >= len(usage_pointers):
                    continue
                address = usage_pointers[destination]
                if address == 0:
                    continue
                _emit_usage(out, kind, index, address, executor)
        return out

    # v27+: the array lives directly in the binary.
    struct = il2cpp.metadata_registration_struct
    count = struct.get("metadataUsagesCount", 0) or 0
    pointers = il2cpp.read_ptr_array_at(struct.get("metadataUsages", 0), count)
    for kind, table in getattr(metadata, "metadataUsageDic", {}).items():
        for destination, index in table.items():
            if destination < len(pointers) and pointers[destination]:
                _emit_usage(out, kind, index, pointers[destination], executor)
    return out


def _emit_usage(out: Dict[str, Any], kind: int, index: int, address: int,
                executor: Executor) -> None:
    metadata = executor.metadata
    il2cpp = executor.il2cpp
    if kind == 5 and index < len(metadata.stringLiterals):
        try:
            value = metadata.get_string_literal_from_index(index)
        except Exception:
            value = ""
        out["ScriptString"].append({"Address": address, "Value": value})
    elif kind == 3 and index < len(metadata.methodDefs):
        method_def = metadata.methodDefs[index]
        type_def = metadata.typeDefs[method_def["declaringType"]] \
            if 0 <= method_def["declaringType"] < len(metadata.typeDefs) else None
        name = "%s$$%s" % (
            executor.get_type_def_name(type_def, True, False) if type_def else "?",
            metadata.get_string_from_index(method_def["nameIndex"]))
        method_address = il2cpp.get_method_pointer(
            executor.image_name(0), method_def) if il2cpp else 0
        out["ScriptMetadataMethod"].append({
            "Address": address, "Name": name, "MethodAddress": method_address})
    elif kind in (1, 2, 4, 6):
        entry = executor.type_at(index)
        signature = executor.get_type_name(entry, True, False) if entry else ""
        out["ScriptMetadata"].append({
            "Address": address, "Name": "Metadata_%d" % index, "Signature": signature})


def write_script_json(executor: Executor, path: str) -> Dict[str, Any]:
    payload = build_script_json(executor)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    return payload
