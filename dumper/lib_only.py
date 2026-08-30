"""
Metadata-free (".so only") analysis, exposed by the web studio as a third mode.

Real builds frequently ship an encrypted ``global-metadata.dat`` but a perfectly
readable ``libil2cpp.so``.  This module squeezes everything the native binary
alone can tell a reverse-engineer:

* ``il2cpp.h``       - the usual runtime-structure header for IDA / Ghidra
* ``script.json``    - same schema as the full dump (IDA / Ghidra loaders work
                       unchanged): exported symbols plus one entry per method
                       pointer found in every ``Il2CppCodeGenModule``
* ``lib-report.json``- machine readable analysis: format, ABI, bits, resolved
                       il2cpp version, sections, registration tables and every
                       exported symbol

No ``dump.cs`` / string literals / DummyDll are produced here - those need the
metadata.  The full and metadata-only pipelines are untouched by this module;
the web studio simply adds a toggle for it.

Developer: Mohamed Annati
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from .binary import BinaryError, open_binary
from .binary.base import Il2CppBinary
from .outputs import il2cpp_h
from .pipeline import DEFAULT_OUTPUT_DIR, DumpOptions, DumpResult, _describe

Progress = Optional[Any]

# Versions tried by the auto-detect, ordered by real-world frequency.
VERSION_CANDIDATES = (24.5, 24.2, 27.1, 29.1, 29.0, 31.0,
                      24.4, 24.3, 27.0, 24.1, 21.0, 19.0, 16.0)

ABI_PREFERENCE = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")


# ---------------------------------------------------------------------------
# extraction (APK -> libil2cpp.so, metadata intentionally NOT read)
# ---------------------------------------------------------------------------
def extract_lib(archive_path: str,
                preferred_abi: Optional[str] = None
                ) -> Tuple[bytes, str, str, List[str]]:
    """Pull only ``libil2cpp.so`` out of an APK / AAB / XAPK.

    Returns ``(bytes, entry_name, abi, available_abis)``.
    """
    binaries: Dict[str, str] = {}
    nested: List[str] = []
    with zipfile.ZipFile(archive_path) as handle:
        for name in handle.namelist():
            parts = name.split("/")
            base = parts[-1].lower()
            if base == "libil2cpp.so" and len(parts) >= 3 and parts[0] == "lib":
                binaries.setdefault(parts[1], name)
            elif base.endswith(".apk"):
                nested.append(name)
        if not binaries:
            for entry in nested:                       # split APK / xapk
                try:
                    inner = zipfile.ZipFile(
                        io.BytesIO(handle.read(entry)))
                except (zipfile.BadZipFile, KeyError, MemoryError):
                    continue
                with inner:
                    for name in inner.namelist():
                        parts = name.split("/")
                        if parts[-1].lower() == "libil2cpp.so" and len(parts) >= 3:
                            binaries.setdefault(parts[1], entry + "!" + name)
        if not binaries:
            raise BinaryError("No libil2cpp.so inside the archive.")
        available = sorted(binaries, key=lambda a: ABI_PREFERENCE.index(a)
                           if a in ABI_PREFERENCE else len(ABI_PREFERENCE))
        abi = preferred_abi if preferred_abi in binaries else available[0]
        entry = binaries[abi]
        if "!" in entry:                               # nested archive
            outer_name, inner_name = entry.split("!", 1)
            with zipfile.ZipFile(
                    io.BytesIO(handle.read(outer_name))) as inner:
                return inner.read(inner_name), entry, abi, available
        return handle.read(entry), entry, abi, available


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
def _exported_registration(binary: Il2CppBinary) -> Tuple[int, int]:
    symbols = getattr(binary, "symbols", None)
    if not symbols:
        return 0, 0
    code = meta = 0
    for symbol in symbols:
        name = binary.symbol_name(symbol)
        if name == "g_CodeRegistration":
            code = symbol["st_value"]
        elif name == "g_MetadataRegistration":
            meta = symbol["st_value"]
    return code, meta


def analyse(binary_bytes: bytes, version: Optional[float] = None,
            progress: Progress = None) -> Tuple[Il2CppBinary, bool]:
    """Parse the binary and resolve the registration tables.

    Returns ``(binary, resolved)``.  Without metadata the il2cpp version is
    unknown, so it is brute-forced over :data:`VERSION_CANDIDATES` (or pinned to
    ``version``).  The parse itself happens once; only the registration-table
    initialisation is retried per version, which is cheap.
    """
    binary = open_binary(binary_bytes)
    if binary.check_dump():
        binary.is_dumped = True

    candidates = [float(version)] if version else list(VERSION_CANDIDATES)
    code_reg, meta_reg = _exported_registration(binary)
    if not (code_reg and meta_reg):
        binary.log.append("No g_CodeRegistration / g_MetadataRegistration "
                          "symbols - static structure only.")
        return binary, False

    # Try every version and keep the one that recovers the most structure.
    best_version: Optional[float] = None
    best_score = -1
    for candidate in candidates:
        binary.set_properties(candidate, 0)
        binary.method_pointers = []
        binary.log.clear()
        if progress:
            progress(0.35, "Trying il2cpp v%s..." % candidate)
        try:
            if not binary.auto_plus_init(code_reg, meta_reg):
                continue
        except BinaryError:
            continue
        method_ptrs = sum(len(p) for p in
                          binary.code_gen_module_method_pointers.values()) \
            + len(binary.method_pointers)
        score = (1 if binary.types else 0) * 100000 \
            + (1 if binary.code_gen_module_method_pointers else 0) * 10000 \
            + method_ptrs + len(binary.types)
        if score > best_score:
            best_score, best_version = score, candidate
            # A full hit (types + modules + methods) is unlikely to improve.
            if binary.types and binary.code_gen_module_method_pointers \
                    and method_ptrs:
                break

    if best_version is not None:
        binary.set_properties(best_version, 0)
        binary.method_pointers = []
        binary.log.clear()
        try:
            binary.auto_plus_init(code_reg, meta_reg)
        except BinaryError:                            # pragma: no cover
            binary.types = []
    resolved = best_version is not None and bool(binary.types)
    binary.version_resolved = resolved
    return binary, resolved


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------
def write_native_header(binary: Il2CppBinary, path: str) -> None:
    """``il2cpp.h`` without metadata - struct shapes depend only on version."""
    parts = [
        "/*\n",
        " * il2cpp.h - generated by IL2CPP Dumper Studio (lib-only mode)\n",
        " * Developer  : Mohamed Annati\n",
        " * Metadata   : not supplied\n",
    ]
    parts.append(" * Binary     : %s (%d-bit, %s)\n"
                 % (binary.format_name, 32 if binary.is32bit else 64,
                    getattr(binary, "abi", "unknown")))
    if binary.code_registration:
        parts.append(" * CodeRegistration     : 0x%X\n" % binary.code_registration)
    if binary.metadata_registration:
        parts.append(" * MetadataRegistration : 0x%X\n"
                     % binary.metadata_registration)
    parts.append(" */\n")
    parts.append(il2cpp_h.GENERIC_HEADER)
    parts.append(il2cpp_h.CLASS_V29 if binary.version >= 29
                 else il2cpp_h.CLASS_LEGACY)
    parts.append(il2cpp_h.ENUM_HEADER)
    with open(path, "w", newline="\n") as handle:
        handle.write("".join(parts))


def _native_methods(binary: Il2CppBinary) -> List[Dict[str, Any]]:
    methods: List[Dict[str, Any]] = []
    for module_name, pointers in binary.code_gen_module_method_pointers.items():
        for index, pointer in enumerate(pointers):
            if not pointer:
                continue
            methods.append({"Address": pointer,
                            "Name": "%s$$sub_%X" % (module_name, pointer)})
    return methods


def _native_exports(binary: Il2CppBinary) -> List[Dict[str, Any]]:
    symbols = getattr(binary, "symbols", None)
    if not symbols:
        return []
    out: List[Dict[str, Any]] = []
    for symbol in symbols:
        name = binary.symbol_name(symbol)
        if not name or symbol["st_value"] == 0:
            continue
        out.append({"Address": symbol["st_value"], "Name": name})
    out.sort(key=lambda item: item["Address"])
    return out


def write_native_script(binary: Il2CppBinary, path: str) -> Dict[str, Any]:
    """``script.json`` from the binary alone - same schema as the full dump."""
    methods = _native_methods(binary)
    exports = _native_exports(binary)
    seen = {m["Address"] for m in methods}
    for export in exports:                            # real names win
        if export["Address"] not in seen:
            methods.append(export)
    methods.sort(key=lambda item: item["Address"])
    payload = {"ScriptMethod": methods,
               "ScriptString": [],
               "ScriptMetadata": [],
               "ScriptMetadataMethod": [],
               "Addresses": [m["Address"] for m in methods]}
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=1)
    return payload


def _sections(binary: Il2CppBinary) -> List[Dict[str, Any]]:
    """Normalise ELF program segments and PE sections into one shape."""
    names = getattr(binary, "section_names", []) or []
    rows: List[Dict[str, Any]] = []
    for index, segment in enumerate(getattr(binary, "program_segments", []) or []):
        rows.append({
            "name": names[index] if index < len(names) else "#%d" % index,
            "vaddr": segment.get("p_vaddr", 0),
            "size": segment.get("p_memsz", 0),
            "flags": segment.get("p_flags", 0),
        })
    if not rows:
        for segment in getattr(binary, "sections_list", []) or []:
            rows.append({
                "name": segment.get("name", ""),
                "vaddr": segment.get("VirtualAddress", 0),
                "size": segment.get("VirtualSize", 0),
                "flags": segment.get("Characteristics", 0),
            })
    return rows


def write_report(binary: Il2CppBinary, resolved: bool, extra: Dict[str, Any],
                 path: str) -> Dict[str, Any]:
    report = {
        "generator": "IL2CPP Dumper Studio",
        "developer": "Mohamed Annati",
        "mode": "lib-only",
        "format": binary.format_name,
        "abi": getattr(binary, "abi", None),
        "bits": 32 if binary.is32bit else 64,
        "imageBase": binary.image_base,
        "il2cppVersion": binary.version or None,
        "versionAutoDetected": bool(getattr(binary, "version_resolved", False)),
        "registrationResolved": resolved,
        "codeRegistration": hex(binary.code_registration)
        if binary.code_registration else None,
        "metadataRegistration": hex(binary.metadata_registration)
        if binary.metadata_registration else None,
        "sections": _sections(binary),
        "exportedSymbols": len(_native_exports(binary)),
        "codegenModules": {name: len(ptrs) for name, ptrs in
                           binary.code_gen_module_method_pointers.items()},
        "il2CppTypeCount": len(binary.types),
        "methodPointerCount": sum(len(p) for p in
                                  binary.code_gen_module_method_pointers.values())
        + len(binary.method_pointers),
        "fieldOffsetCount": len(binary.field_offsets),
        "warnings": list(binary.log),
        "notes": extra,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    return report


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def dump_lib_only(binary_bytes: bytes,
                  options: Optional[DumpOptions] = None,
                  version: Optional[float] = None,
                  progress: Progress = None) -> DumpResult:
    started = time.time()
    options = options or DumpOptions()
    output_dir = options.output_dir
    os.makedirs(output_dir, exist_ok=True)
    logs: List[str] = []

    def say(message: str) -> None:
        logs.append(message)

    if progress:
        progress(0.08, "Loading native binary...")
    try:
        binary, resolved = analyse(binary_bytes, version, progress)
    except BinaryError as error:
        return DumpResult(ok=False, output_dir=output_dir, logs=logs,
                          error=str(error), mode="lib-only")

    say("Binary format    : %s" % binary.format_name)
    say("ABI              : %s (%d-bit)"
        % (getattr(binary, "abi", "unknown"), 32 if binary.is32bit else 64))
    for line in binary.log:
        say(line)
    if resolved:
        say("il2cpp version   : %s (auto-detected)" % binary.version)
        say("CodeRegistration     : 0x%X" % binary.code_registration)
        say("MetadataRegistration : 0x%X" % binary.metadata_registration)
        say("Il2CppType table : %d entries" % len(binary.types))
    else:
        say("WARNING: registration tables not resolved - static structure only.")

    files: List[Dict[str, Any]] = []
    if progress:
        progress(0.6, "Writing il2cpp.h...")
    write_native_header(binary, os.path.join(output_dir, "il2cpp.h"))
    files.append(_describe(os.path.join(output_dir, "il2cpp.h"), "il2cpp.h",
                           "Runtime structures for IDA / Ghidra"))

    if progress:
        progress(0.72, "Writing script.json...")
    payload = write_native_script(binary, os.path.join(output_dir, "script.json"))
    files.append(_describe(os.path.join(output_dir, "script.json"), "script.json",
                           "%d native symbols for IDA / Ghidra"
                           % len(payload["ScriptMethod"])))

    if progress:
        progress(0.85, "Writing lib-report.json...")
    report = write_report(binary, resolved,
                          {"output": [f["name"] for f in files]},
                          os.path.join(output_dir, "lib-report.json"))
    files.append(_describe(os.path.join(output_dir, "lib-report.json"),
                           "lib-report.json",
                           "Machine readable analysis of the native binary"))

    manifest = {
        "generator": "IL2CPP Dumper Studio",
        "developer": "Mohamed Annati",
        "mode": "lib-only",
        "stats": report,
        "files": [f["name"] for f in files],
        "logs": logs,
    }
    manifest_path = os.path.join(output_dir, "dump-manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    files.append(_describe(manifest_path, "dump-manifest.json",
                           "Machine readable summary of this run"))

    stats = {
        "mode": "lib-only",
        "binaryFormat": binary.format_name,
        "binaryBits": 32 if binary.is32bit else 64,
        "binaryAbi": getattr(binary, "abi", None),
        "metadataVersion": None,
        "il2cppVersion": binary.version or None,
        "typeCount": len(binary.types),
        "dumpedTypes": len(binary.types),
        "dumpedMethods": len(payload["ScriptMethod"]),
        "dumpedFields": len(binary.field_offsets),
        "images": len(binary.code_gen_module_method_pointers),
        "codeRegistration": hex(binary.code_registration)
        if binary.code_registration else None,
        "metadataRegistration": hex(binary.metadata_registration)
        if binary.metadata_registration else None,
        "registrationResolved": resolved,
    }
    if progress:
        progress(1.0, "Done")
    return DumpResult(ok=True, output_dir=os.path.abspath(output_dir),
                      files=files, stats=stats, logs=logs, mode="lib-only",
                      duration_seconds=time.time() - started)
