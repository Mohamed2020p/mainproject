"""
Executable-format detection and factory.

``open_binary`` sniffs the magic bytes of a file and returns the matching
reader, so a user can hand the tool a ``libil2cpp.so``, a ``GameAssembly.dll``
or a ``UnityFramework`` Mach-O without caring which one it is.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .. import consts
from .base import BinaryError, Il2CppBinary, SearchSection
from .elf import ElfBinary
from .pe import PeBinary

__all__ = [
    "BinaryError",
    "ElfBinary",
    "Il2CppBinary",
    "PeBinary",
    "SearchSection",
    "detect_format",
    "open_binary",
]


FORMAT_ELF = "elf"
FORMAT_PE = "pe"
FORMAT_MACHO = "macho"
FORMAT_NSO = "nso"
FORMAT_WASM = "wasm"
FORMAT_UNKNOWN = "unknown"

FORMAT_LABEL = {
    FORMAT_ELF: "ELF (Android / Linux)",
    FORMAT_PE: "PE (Windows GameAssembly.dll)",
    FORMAT_MACHO: "Mach-O (iOS / macOS)",
    FORMAT_NSO: "NSO (Nintendo Switch)",
    FORMAT_WASM: "WebAssembly",
    FORMAT_UNKNOWN: "Unknown",
}


def detect_format(head: bytes) -> str:
    """Classify a container from its first bytes."""
    if head.startswith(consts.MAGIC_ELF):
        return FORMAT_ELF
    if head.startswith(consts.MAGIC_PE):
        return FORMAT_PE
    if head[:4] in (consts.MAGIC_MACHO_32, consts.MAGIC_MACHO_64,
                    consts.MAGIC_MACHO_32_SWAP, consts.MAGIC_MACHO_64_SWAP):
        return FORMAT_MACHO
    if head[:4] == consts.MAGIC_FAT:
        return FORMAT_MACHO
    if head[:4] == consts.MAGIC_NSO:
        return FORMAT_NSO
    if head[:4] == consts.MAGIC_WASM:
        return FORMAT_WASM
    return FORMAT_UNKNOWN


def open_binary(data: bytes) -> Il2CppBinary:
    """Instantiate the right reader for ``data`` or raise ``BinaryError``."""
    kind = detect_format(data[:16])
    if kind == FORMAT_ELF:
        return ElfBinary(data)
    if kind == FORMAT_PE:
        return PeBinary(data)
    if kind == FORMAT_MACHO:
        raise BinaryError(
            "Mach-O images (iOS / macOS) are not supported by this build. "
            "Upload an Android libil2cpp.so or a Windows GameAssembly.dll.")
    if kind == FORMAT_NSO:
        raise BinaryError("Nintendo Switch NSO images are not supported by this build.")
    if kind == FORMAT_WASM:
        raise BinaryError("WebAssembly images are not supported by this build.")
    raise BinaryError(
        "Unrecognised binary format. Expected an ELF (.so) or PE (.dll) image.")
