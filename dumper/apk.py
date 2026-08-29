"""
APK / AAB / XAPK handling.

Users normally do not have ``libil2cpp.so`` and ``global-metadata.dat`` lying
around - they have the game's ``.apk``.  This module opens the archive and pulls
both files out of the locations Unity uses:

=========================================  ===================================
Entry                                      Meaning
=========================================  ===================================
``lib/<abi>/libil2cpp.so``                 the native IL2CPP binary
``assets/bin/Data/Managed/Metadata/global-metadata.dat``   the metadata
``assets/bin/Data/Managed/*.dll``          (pre-IL2CPP games only, ignored)
=========================================  ===================================

Split APKs and ``.xapk`` bundles are handled too: every nested ``.apk`` is
scanned until both files are found.
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import Dict, List, Optional, Tuple

ABI_PREFERENCE = ("arm64-v8a", "armeabi-v7a", "x86_64", "x86")

METADATA_SUFFIXES = ("global-metadata.dat",)
BINARY_NAMES = ("libil2cpp.so", "libunity.so")


class ApkError(Exception):
    """Raised when the archive does not look like an IL2CPP package."""


class ExtractedPair:
    """The two files an IL2CPP dump needs, lifted out of an archive."""

    __slots__ = ("binary", "metadata", "binary_entry", "metadata_entry",
                 "abi", "available_abis")

    def __init__(self, binary: bytes, metadata: bytes, binary_entry: str,
                 metadata_entry: str, abi: str, available_abis: List[str]):
        self.binary = binary
        self.metadata = metadata
        self.binary_entry = binary_entry
        self.metadata_entry = metadata_entry
        self.abi = abi
        self.available_abis = available_abis

    def summary(self) -> Dict[str, object]:
        return {
            "binaryEntry": self.binary_entry,
            "metadataEntry": self.metadata_entry,
            "abi": self.abi,
            "availableAbis": self.available_abis,
            "binarySize": len(self.binary),
            "metadataSize": len(self.metadata),
        }


def _is_zip(head: bytes) -> bool:
    return head[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def looks_like_archive(head: bytes) -> bool:
    return _is_zip(head)


def list_abis(archive_path: str) -> List[str]:
    """Return every ``lib/<abi>/`` folder present in the archive."""
    abis: List[str] = []
    try:
        with zipfile.ZipFile(archive_path) as handle:
            for name in handle.namelist():
                parts = name.split("/")
                if len(parts) >= 3 and parts[0] == "lib" and parts[1] not in abis:
                    abis.append(parts[1])
    except zipfile.BadZipFile:
        return []
    return abis


def _rank(abi: str) -> int:
    return ABI_PREFERENCE.index(abi) if abi in ABI_PREFERENCE else len(ABI_PREFERENCE)


def _read_from_zip(handle: zipfile.ZipFile, path: str) -> Dict[str, object]:
    """Index an open zip: metadata, binaries per ABI, and nested archives."""
    metadata_entry: Optional[str] = None
    binaries: Dict[str, str] = {}
    nested: List[str] = []

    for name in handle.namelist():
        lowered = name.lower()
        base = lowered.rsplit("/", 1)[-1]
        parts = lowered.split("/")
        if metadata_entry is None and any(base.endswith(s) for s in METADATA_SUFFIXES):
            metadata_entry = name
        if base == "libil2cpp.so" and len(parts) >= 3 and parts[0] == "lib":
            binaries.setdefault(parts[1], name)
        if base.endswith(".apk") and name.lower() != path.lower():
            nested.append(name)

    return {"metadata": metadata_entry, "binaries": binaries, "nested": nested}


def extract_pair(archive_path: str, preferred_abi: Optional[str] = None
                 ) -> ExtractedPair:
    """Pull ``libil2cpp.so`` + ``global-metadata.dat`` out of an APK/AAB/XAPK."""
    if not os.path.isfile(archive_path):
        raise ApkError("Archive not found: %s" % archive_path)

    with open(archive_path, "rb") as probe:
        head = probe.read(8)
    if not _is_zip(head):
        raise ApkError("Not a ZIP-based archive (apk/aab/xapk/zip expected).")

    with zipfile.ZipFile(archive_path) as handle:
        index = _read_from_zip(handle, archive_path)
        pair = _try_build(handle, index, preferred_abi)
        if pair is not None:
            return pair

        # split APK / xapk: look inside the nested archives
        for entry in index["nested"]:
            try:
                inner = zipfile.ZipFile(io.BytesIO(handle.read(entry)))
            except (zipfile.BadZipFile, KeyError, MemoryError):
                continue
            with inner:
                inner_index = _read_from_zip(inner, entry)
                pair = _try_build(inner, inner_index, preferred_abi,
                                  metadata_from=handle, index_for_metadata=index)
                if pair is not None:
                    return pair

    raise ApkError(
        "Could not find libil2cpp.so and global-metadata.dat inside the archive. "
        "Either this is not a Unity IL2CPP build, or the metadata is stored "
        "encrypted / at a non-standard path.")


def _try_build(handle: zipfile.ZipFile, index: Dict[str, object],
               preferred_abi: Optional[str],
               metadata_from: Optional[zipfile.ZipFile] = None,
               index_for_metadata: Optional[Dict[str, object]] = None
               ) -> Optional[ExtractedPair]:
    binaries: Dict[str, str] = index["binaries"]  # type: ignore[assignment]
    metadata_entry = index["metadata"]            # type: ignore[assignment]
    metadata_handle = handle
    if metadata_entry is None and index_for_metadata is not None and metadata_from:
        metadata_entry = index_for_metadata["metadata"]  # type: ignore[assignment]
        metadata_handle = metadata_from
    if metadata_entry is None or not binaries:
        return None

    available = sorted(binaries.keys(), key=_rank)
    abi = preferred_abi if preferred_abi in binaries else available[0]
    binary_entry = binaries[abi]

    binary = handle.read(binary_entry)
    metadata = metadata_handle.read(metadata_entry)  # type: ignore[arg-type]
    return ExtractedPair(binary, metadata, binary_entry, metadata_entry, abi,
                         available)


def extract_to_dir(archive_path: str, destination: str,
                   preferred_abi: Optional[str] = None) -> Tuple[str, str, ExtractedPair]:
    """Extract both files next to each other in ``destination``."""
    pair = extract_pair(archive_path, preferred_abi)
    os.makedirs(destination, exist_ok=True)
    binary_path = os.path.join(destination, os.path.basename(pair.binary_entry))
    metadata_path = os.path.join(destination, "global-metadata.dat")
    with open(binary_path, "wb") as handle:
        handle.write(pair.binary)
    with open(metadata_path, "wb") as handle:
        handle.write(pair.metadata)
    return binary_path, metadata_path, pair
