"""
End-to-end orchestration: files in, ``dump/`` folder out.

The pipeline is deliberately tolerant.  The two halves of an IL2CPP dump have
very different failure modes:

* ``global-metadata.dat`` is small, well-formed and almost always parseable -
  unless it is encrypted, in which case nothing works.
* ``libil2cpp.so`` is where things break: stripped symbols, packers, split
  sections, memory dumps with a wrong image base.

So a failed binary never aborts the job.  The dumper falls back to
metadata-only mode, still writes a useful ``dump.cs`` and reports exactly why
the native side was skipped.
"""

from __future__ import annotations

import json
import os
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import apk as apk_module
from .binary import BinaryError, open_binary
from .binary.base import Il2CppBinary
from .executor import Executor
from .metadata import Metadata, MetadataError, is_metadata_file
from .outputs.dummy_dll import generate_dummy_dlls
from .outputs.dump_cs import DumpConfig, write_dump_cs
from .outputs.il2cpp_h import write_il2cpp_header
from .outputs.script_json import write_script_json
from .outputs.string_literal import write_string_literals

Progress = Optional[Callable[[float, str], None]]

DEFAULT_OUTPUT_DIR = "dump"


@dataclass
class DumpResult:
    """Everything the caller (CLI, web UI, notebook) needs after a dump."""

    ok: bool
    output_dir: str
    files: List[Dict[str, Any]] = field(default_factory=list)
    stats: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    mode: str = "metadata"
    duration_seconds: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "outputDir": self.output_dir,
            "files": self.files,
            "stats": self.stats,
            "logs": self.logs,
            "error": self.error,
            "durationSeconds": round(self.duration_seconds, 3),
        }


class DumpOptions:
    """What to produce, and how hard to try."""

    def __init__(self, output_dir: str = DEFAULT_OUTPUT_DIR,
                 dump_config: Optional[DumpConfig] = None,
                 make_dummy_dll: bool = True,
                 make_script_json: bool = True,
                 make_il2cpp_header: bool = True,
                 make_string_literals: bool = True,
                 preferred_abi: Optional[str] = None):
        self.output_dir = output_dir
        self.dump_config = dump_config or DumpConfig()
        self.make_dummy_dll = make_dummy_dll
        self.make_script_json = make_script_json
        self.make_il2cpp_header = make_il2cpp_header
        self.make_string_literals = make_string_literals
        self.preferred_abi = preferred_abi

    @staticmethod
    def from_dict(values: Dict[str, Any]) -> "DumpOptions":
        return DumpOptions(
            output_dir=values.get("outputDir") or DEFAULT_OUTPUT_DIR,
            dump_config=DumpConfig.from_dict(values.get("dump", {}) or {}),
            make_dummy_dll=bool(values.get("dummyDll", True)),
            make_script_json=bool(values.get("scriptJson", True)),
            make_il2cpp_header=bool(values.get("il2cppHeader", True)),
            make_string_literals=bool(values.get("stringLiterals", True)),
            preferred_abi=values.get("preferredAbi"),
        )


# ---------------------------------------------------------------------------
def dump_apk(archive_path: str, options: Optional[DumpOptions] = None,
             progress: Progress = None) -> DumpResult:
    """Extract an APK and dump it in one step."""
    options = options or DumpOptions()
    logs: List[str] = []
    if progress:
        progress(0.02, "Opening archive...")
    pair = apk_module.extract_pair(archive_path, options.preferred_abi)
    logs.append("ABI selected     : %s (available: %s)"
                % (pair.abi, ", ".join(pair.available_abis)))
    logs.append("IL2CPP binary    : %s (%s)"
                % (pair.binary_entry, _human(pair.binary.__len__())))
    logs.append("Metadata         : %s (%s)"
                % (pair.metadata_entry, _human(len(pair.metadata))))
    result = dump_bytes(pair.binary, pair.metadata, options, progress)
    result.logs = logs + result.logs
    result.stats["apk"] = pair.summary()
    return result


def dump_files(binary_path: str, metadata_path: str,
               options: Optional[DumpOptions] = None,
               progress: Progress = None) -> DumpResult:
    """Dump from two files already on disk."""
    with open(binary_path, "rb") as handle:
        binary = handle.read()
    with open(metadata_path, "rb") as handle:
        metadata = handle.read()
    return dump_bytes(binary, metadata, options, progress)


def dump_bytes(binary: bytes, metadata_bytes: bytes,
               options: Optional[DumpOptions] = None,
               progress: Progress = None) -> DumpResult:
    """The real worker - everything else is a thin wrapper around this."""
    started = time.time()
    options = options or DumpOptions()
    logs: List[str] = []
    output_dir = options.output_dir
    os.makedirs(output_dir, exist_ok=True)

    def say(message: str) -> None:
        logs.append(message)

    # ---- sanity: the two inputs are frequently swapped by hand ----
    if is_metadata_file(binary[:4]) and not is_metadata_file(metadata_bytes[:4]):
        say("Inputs look swapped - correcting automatically.")
        binary, metadata_bytes = metadata_bytes, binary

    if not is_metadata_file(metadata_bytes[:4]):
        return DumpResult(
            ok=False, output_dir=output_dir, logs=logs,
            error=("The metadata file is not a valid global-metadata.dat "
                   "(bad magic). It is probably encrypted or obfuscated - dump "
                   "it from memory instead (Zygisk-Il2CppDumper / "
                   "il2cppmemorydumper) and try again."))

    try:
        metadata = Metadata(metadata_bytes)
    except (MetadataError, Exception) as error:
        return DumpResult(ok=False, output_dir=output_dir, logs=logs,
                          error="Metadata parsing failed: %s" % error)

    say("Metadata version : %s" % metadata.version)
    say("Images           : %d" % len(metadata.imageDefs))
    say("Types            : %d" % len(metadata.typeDefs))
    say("Methods          : %d" % len(metadata.methodDefs))

    # ---- native binary (best effort) ----
    il2cpp: Optional[Il2CppBinary] = None
    if binary:
        if progress:
            progress(0.10, "Loading native binary...")
        try:
            il2cpp = open_binary(binary)
            say("Binary format    : %s (%s)"
                % (il2cpp.format_name,
                   getattr(il2cpp, "abi", "%d-bit" % (32 if il2cpp.is32bit else 64))))
            il2cpp.set_properties(metadata.version, metadata.metadataUsagesCount)
            if il2cpp.check_dump():
                say("WARNING: no .text section - this looks like a memory dump.")
                il2cpp.is_dumped = True
            for line in il2cpp.log:
                say(line)
            il2cpp.log.clear()

            resolved = False
            try:
                resolved = il2cpp.symbol_search()
            except Exception as error:
                say("Symbol search failed: %s" % error)
            if not resolved:
                if progress:
                    progress(0.20, "Searching CodeRegistration / MetadataRegistration...")
                try:
                    method_count = sum(1 for m in metadata.methodDefs
                                       if m.get("methodIndex", -1) is None
                                       or m.get("methodIndex", -1) >= 0)
                    resolved = il2cpp.plus_search(len(metadata.methodDefs),
                                                  len(metadata.typeDefs),
                                                  len(metadata.imageDefs))
                    del method_count
                except Exception as error:
                    say("Heuristic search failed: %s" % error)
            if resolved:
                say("Il2CppType table : %d entries" % len(il2cpp.types))
                for line in il2cpp.log:
                    say(line)
                il2cpp.log.clear()
            else:
                say("WARNING: registration tables not found - continuing in "
                    "metadata-only mode.")
                il2cpp = None
        except BinaryError as error:
            say("Binary rejected: %s" % error)
            il2cpp = None
        except Exception as error:
            say("Binary analysis failed: %s" % error)
            say(traceback.format_exc(limit=2).strip())
            il2cpp = None
    else:
        say("No IL2CPP binary supplied - metadata-only mode.")

    executor = Executor(metadata, il2cpp)
    mode = executor.mode()
    say("Dump mode        : %s" % mode)

    files: List[Dict[str, Any]] = []

    # ---- dump.cs ----
    if progress:
        progress(0.30, "Writing dump.cs...")
    dump_path = os.path.join(output_dir, "dump.cs")
    counters = write_dump_cs(executor, options.dump_config, dump_path,
                             progress=_scaled(progress, 0.30, 0.60))
    files.append(_describe(dump_path, "dump.cs",
                           "C# pseudo-code of every type in the game"))

    # ---- il2cpp.h ----
    if options.make_il2cpp_header:
        header_path = os.path.join(output_dir, "il2cpp.h")
        write_il2cpp_header(executor, header_path)
        files.append(_describe(header_path, "il2cpp.h",
                               "Runtime structures for IDA / Ghidra"))

    # ---- stringliteral.json ----
    if options.make_string_literals:
        if progress:
            progress(0.62, "Writing stringliteral.json...")
        literal_path = os.path.join(output_dir, "stringliteral.json")
        literals = write_string_literals(metadata, literal_path)
        files.append(_describe(literal_path, "stringliteral.json",
                               "%d managed string literals" % len(literals)))

    # ---- script.json ----
    if options.make_script_json:
        if progress:
            progress(0.68, "Writing script.json...")
        script_path = os.path.join(output_dir, "script.json")
        payload = write_script_json(executor, script_path)
        files.append(_describe(script_path, "script.json",
                               "%d symbols for IDA / Ghidra"
                               % len(payload["ScriptMethod"])))

    # ---- DummyDll ----
    dummy_results: List[Dict[str, Any]] = []
    if options.make_dummy_dll:
        if progress:
            progress(0.75, "Rebuilding DummyDll assemblies...")
        dummy_dir = os.path.join(output_dir, "DummyDll")
        dummy_results = generate_dummy_dlls(
            executor, dummy_dir, progress=_scaled(progress, 0.75, 0.97))
        produced = [r for r in dummy_results if r["ok"]]
        if produced:
            files.append({
                "name": "DummyDll/",
                "path": os.path.abspath(dummy_dir),
                "size": sum(r.get("size", 0) for r in produced),
                "description": "%d restored .NET assemblies (open in dnSpy / ILSpy)"
                               % len(produced),
                "kind": "folder",
                "children": [{"name": r["name"], "size": r.get("size", 0)}
                             for r in produced],
            })
        for failure in [r for r in dummy_results if not r["ok"]]:
            say("DummyDll: %s skipped (%s)" % (failure["name"], failure["error"]))

    if progress:
        progress(1.0, "Done")

    stats = dict(metadata.summary())
    stats.update({
        "mode": mode,
        "binaryFormat": il2cpp.format_name if il2cpp else None,
        "binaryBits": (32 if il2cpp.is32bit else 64) if il2cpp else None,
        "binaryAbi": getattr(il2cpp, "abi", None) if il2cpp else None,
        "codeRegistration": hex(il2cpp.code_registration) if il2cpp else None,
        "metadataRegistration": hex(il2cpp.metadata_registration) if il2cpp else None,
        "typeCount": len(il2cpp.types) if il2cpp else 0,
        "dumpedTypes": counters["types"],
        "dumpedFields": counters["fields"],
        "dumpedMethods": counters["methods"],
        "dumpedProperties": counters["properties"],
        "dummyDllCount": len([r for r in dummy_results if r["ok"]]),
        "stringLiterals": len(metadata.stringLiterals),
    })

    manifest = {
        "generator": "IL2CPP Dumper Studio",
        "developer": "Mohamed Annati",
        "mode": mode,
        "stats": stats,
        "files": [f["name"] for f in files],
        "logs": logs,
    }
    manifest_path = os.path.join(output_dir, "dump-manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False)
    files.append(_describe(manifest_path, "dump-manifest.json",
                           "Machine readable summary of this run"))

    return DumpResult(ok=True, output_dir=os.path.abspath(output_dir), files=files,
                      stats=stats, logs=logs, mode=mode,
                      duration_seconds=time.time() - started)


# ---------------------------------------------------------------------------
def _describe(path: str, name: str, description: str) -> Dict[str, Any]:
    return {
        "name": name,
        "path": os.path.abspath(path),
        "size": os.path.getsize(path) if os.path.exists(path) else 0,
        "description": description,
        "kind": "file",
    }


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return "%d %s" % (size, unit) if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%.1f TB" % size


def _scaled(progress: Progress, low: float, high: float):
    if progress is None:
        return None

    def inner(fraction: float, message: str) -> None:
        progress(low + (high - low) * max(0.0, min(1.0, fraction)), message)

    return inner
