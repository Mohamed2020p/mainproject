"""
PE reader for ``GameAssembly.dll`` (Windows / PC builds and some emulators).

Handles PE32 and PE32+ images and applies the base relocations in place so the
data pointers read from the file are real virtual addresses.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

from .. import consts
from .base import BinaryError, Il2CppBinary, SearchSection

IMAGE_SCN_MEM_EXECUTE = 0x20000000
IMAGE_SCN_MEM_READ = 0x40000000
IMAGE_SCN_MEM_WRITE = 0x80000000

IMAGE_REL_BASED_HIGHLOW = 3
IMAGE_REL_BASED_DIR64 = 10


class PeBinary(Il2CppBinary):
    format_name = "PE"

    def __init__(self, data: bytes):
        super().__init__(data)
        self.sections_list: List[Dict[str, int]] = []
        self.data_directories: List[Tuple[int, int]] = []
        self._load()

    def _load(self) -> None:
        data = self.data
        if bytes(data[:2]) != consts.MAGIC_PE:
            raise BinaryError("Not a PE file.")
        e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
        if bytes(data[e_lfanew:e_lfanew + 4]) != b"PE\x00\x00":
            raise BinaryError("Missing PE signature.")

        machine, num_sections, _ts, _sym, _nsym, size_of_optional, _chars = \
            struct.unpack_from("<HHIIIHH", data, e_lfanew + 4)
        self.machine = machine
        optional_offset = e_lfanew + 24
        magic = struct.unpack_from("<H", data, optional_offset)[0]

        if magic == 0x20B:
            self.is32bit = False
            self.image_base = struct.unpack_from("<Q", data, optional_offset + 24)[0]
            directory_offset = optional_offset + 112
        elif magic == 0x10B:
            self.is32bit = True
            self.image_base = struct.unpack_from("<I", data, optional_offset + 28)[0]
            directory_offset = optional_offset + 96
        else:
            raise BinaryError("Unknown optional header magic 0x%X." % magic)

        self.format_name = "PE32" if self.is32bit else "PE32+"

        count = min(16, (size_of_optional - (directory_offset - optional_offset)) // 8)
        self.data_directories = [struct.unpack_from("<II", data,
                                                   directory_offset + i * 8)
                                 for i in range(max(0, count))]

        section_offset = optional_offset + size_of_optional
        self.sections_list = []
        for i in range(num_sections):
            base = section_offset + i * 40
            name = bytes(data[base:base + 8]).rstrip(b"\x00").decode("latin-1")
            (virtual_size, virtual_address, size_of_raw, pointer_to_raw,
             _pr, _pl, _nreloc, _nline, _creloc, characteristics) = struct.unpack_from(
                 "<IIIIIIHHI", data, base + 8)
            self.sections_list.append({
                "name": name, "VirtualSize": virtual_size,
                "VirtualAddress": virtual_address, "SizeOfRawData": size_of_raw,
                "PointerToRawData": pointer_to_raw,
                "Characteristics": characteristics,
            })

        self._apply_relocations()

    def _apply_relocations(self) -> None:
        if len(self.data_directories) < 6:
            return
        rva, size = self.data_directories[5]
        if rva == 0 or size == 0:
            return
        try:
            start = self.map_vatr(rva)
        except (ValueError, IndexError):
            return
        self._say("Applying base relocations...")
        position = start
        limit = min(start + size, len(self.data))
        applied = 0
        word = 4 if self.is32bit else 8
        while position + 8 <= limit:
            page_rva, block_size = struct.unpack_from("<II", self.data, position)
            if block_size < 8:
                break
            entries = (block_size - 8) // 2
            for i in range(entries):
                item = struct.unpack_from("<H", self.data, position + 8 + i * 2)[0]
                rtype = item >> 12
                offset_in_page = item & 0x0FFF
                if rtype not in (IMAGE_REL_BASED_HIGHLOW, IMAGE_REL_BASED_DIR64):
                    continue
                try:
                    file_offset = self.map_vatr(page_rva + offset_in_page)
                except (ValueError, IndexError):
                    continue
                if file_offset + word > len(self.data):
                    continue
                value = int.from_bytes(self.data[file_offset:file_offset + word], "little")
                value = (value + self.image_base) & (
                    0xFFFFFFFFFFFFFFFF if word == 8 else 0xFFFFFFFF)
                self.data[file_offset:file_offset + word] = value.to_bytes(word, "little")
                applied += 1
            position += block_size
        self._say("Applied %d base relocations." % applied)

    # ------------------------------------------------------------------
    def map_vatr(self, address: int) -> int:
        rva = address - self.image_base if address >= self.image_base else address
        for section in self.sections_list:
            start = section["VirtualAddress"]
            end = start + max(section["VirtualSize"], section["SizeOfRawData"])
            if start <= rva < end:
                return rva - start + section["PointerToRawData"]
        raise ValueError("RVA 0x%X is not inside any PE section." % rva)

    def map_rtva(self, offset: int) -> int:
        for section in self.sections_list:
            start = section["PointerToRawData"]
            if start <= offset < start + section["SizeOfRawData"]:
                return offset - start + section["VirtualAddress"] + self.image_base
        return 0

    def sections(self) -> Tuple[List[SearchSection], List[SearchSection]]:
        data_sections: List[SearchSection] = []
        exec_sections: List[SearchSection] = []
        for section in self.sections_list:
            characteristics = section["Characteristics"]
            item = SearchSection(
                section["PointerToRawData"],
                section["PointerToRawData"] + section["SizeOfRawData"],
                section["VirtualAddress"] + self.image_base,
                section["VirtualAddress"] + section["VirtualSize"] + self.image_base)
            if characteristics & IMAGE_SCN_MEM_EXECUTE:
                exec_sections.append(item)
            elif characteristics & IMAGE_SCN_MEM_READ:
                data_sections.append(item)
        return exec_sections, data_sections

    def check_dump(self) -> bool:
        return not any(s["name"] == ".text" for s in self.sections_list)
