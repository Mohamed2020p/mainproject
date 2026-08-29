"""
ELF reader for ``libil2cpp.so`` - the Android build of a Unity IL2CPP game.

Both word sizes are handled because Android ships several ABIs:

=====================  ======
ABI                    format
=====================  ======
armeabi-v7a            ELF32
arm64-v8a              ELF64
x86                    ELF32
x86_64                 ELF64
=====================  ======

The loader does three jobs before anything else looks at the image:

1. parse program headers / the ``PT_DYNAMIC`` table,
2. resolve the dynamic symbol table (``DT_HASH`` or ``DT_GNU_HASH``),
3. apply relocations in place so that data pointers read from the file contain
   real addresses instead of zeros.

Step 3 is what makes the pointer-graph search in
:mod:`dumper.binary.base` possible.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

from .. import consts
from .base import BinaryError, Il2CppBinary, SearchSection


class ElfBinary(Il2CppBinary):
    format_name = "ELF"

    def __init__(self, data: bytes):
        super().__init__(data)
        self.machine = 0
        self.program_segments: List[Dict[str, int]] = []
        self.dynamic: List[Dict[str, int]] = []
        self.symbols: List[Dict[str, Any]] = []
        self.section_names: List[str] = []
        self.may_be_protected = False
        self.protection_notes: List[str] = []
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        data = self.data
        if bytes(data[:4]) != consts.MAGIC_ELF:
            raise BinaryError("Not an ELF file.")
        ei_class = data[4]
        if ei_class == 1:
            self.is32bit = True
        elif ei_class == 2:
            self.is32bit = False
        else:
            raise BinaryError("Unknown ELF class %d." % ei_class)

        if data[5] != 1:
            raise BinaryError("Only little-endian ELF images are supported.")

        if self.is32bit:
            (self.e_type, self.machine, _ver, _entry, e_phoff, self.e_shoff,
             _flags, _ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum,
             self.e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
            self.format_name = "ELF32"
        else:
            (self.e_type, self.machine, _ver, _entry, e_phoff, self.e_shoff,
             _flags, _ehsize, e_phentsize, e_phnum, e_shentsize, e_shnum,
             self.e_shstrndx) = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
            self.format_name = "ELF64"

        self._read_program_headers(e_phoff, e_phnum)
        self._read_sections(e_shnum, e_shentsize)
        self._read_dynamic()
        self._read_symbols()

        if not self.is_dumped:
            self._apply_relocations()
            self._check_protection()

    # ------------------------------------------------------------------
    def _read_program_headers(self, offset: int, count: int) -> None:
        self.program_segments = []
        for i in range(count):
            if self.is32bit:
                (p_type, p_offset, p_vaddr, _paddr, p_filesz, p_memsz,
                 p_flags, _align) = struct.unpack_from("<IIIIIIII", self.data,
                                                      offset + i * 32)
            else:
                (p_type, p_flags, p_offset, p_vaddr, _paddr, p_filesz,
                 p_memsz, _align) = struct.unpack_from("<IIQQQQQQ", self.data,
                                                      offset + i * 56)
            self.program_segments.append({
                "p_type": p_type, "p_offset": p_offset, "p_vaddr": p_vaddr,
                "p_filesz": p_filesz, "p_memsz": p_memsz, "p_flags": p_flags,
            })

    def _read_sections(self, count: int, entsize: int) -> None:
        self.section_names = []
        if self.e_shoff == 0 or count == 0:
            return
        try:
            if self.is32bit:
                headers = [struct.unpack_from("<10I", self.data,
                                              self.e_shoff + i * 40)
                           for i in range(count)]
                strtab_offset = headers[self.e_shstrndx][4]
            else:
                headers = [struct.unpack_from("<IIQQQQIIQQ", self.data,
                                              self.e_shoff + i * 64)
                           for i in range(count)]
                strtab_offset = headers[self.e_shstrndx][4]
            for header in headers:
                self.section_names.append(self.read_string_to_null(
                    strtab_offset + header[0], 128))
        except Exception:
            self.section_names = []

    def _read_dynamic(self) -> None:
        dynamic_segment = next((s for s in self.program_segments
                               if s["p_type"] == consts.PT_DYNAMIC), None)
        if dynamic_segment is None:
            raise BinaryError("ELF image has no PT_DYNAMIC segment.")
        entry_size = 8 if self.is32bit else 16
        count = dynamic_segment["p_filesz"] // entry_size
        self.dynamic = []
        for i in range(count):
            if self.is32bit:
                tag, value = struct.unpack_from("<iI", self.data,
                                                dynamic_segment["p_offset"] + i * 8)
            else:
                tag, value = struct.unpack_from("<qQ", self.data,
                                                dynamic_segment["p_offset"] + i * 16)
            self.dynamic.append({"d_tag": tag, "d_un": value})
            if tag == consts.DT_NULL:
                break

    def _dyn(self, tag: int) -> Optional[int]:
        for entry in self.dynamic:
            if entry["d_tag"] == tag:
                return entry["d_un"]
        return None

    # ------------------------------------------------------------------
    def _read_symbols(self) -> None:
        self.symbols = []
        try:
            count = 0
            hash_value = self._dyn(consts.DT_HASH)
            if hash_value is not None:
                addr = self.map_vatr(hash_value)
                _nbucket, nchain = struct.unpack_from("<II", self.data, addr)
                count = nchain
            else:
                hash_value = self._dyn(consts.DT_GNU_HASH)
                if hash_value is None:
                    return
                addr = self.map_vatr(hash_value)
                nbuckets, symoffset, bloom_size, _shift = struct.unpack_from(
                    "<IIII", self.data, addr)
                buckets_address = addr + 16 + 4 * bloom_size
                buckets = list(struct.unpack_from("<%dI" % nbuckets, self.data,
                                                  buckets_address)) if nbuckets else []
                last_symbol = max(buckets) if buckets else 0
                if last_symbol < symoffset:
                    count = symoffset
                else:
                    chains = buckets_address + 4 * nbuckets
                    position = chains + (last_symbol - symoffset) * 4
                    while True:
                        entry = struct.unpack_from("<I", self.data, position)[0]
                        last_symbol += 1
                        position += 4
                        if entry & 1:
                            break
                    count = last_symbol

            symtab = self._dyn(consts.DT_SYMTAB)
            if symtab is None or count <= 0:
                return
            offset = self.map_vatr(symtab)
            for i in range(min(count, 1_000_000)):
                if self.is32bit:
                    st_name, st_value, _size, _info, _other, _shndx = struct.unpack_from(
                        "<IIIBBH", self.data, offset + i * 16)
                else:
                    st_name, _info, _other, _shndx, st_value, _size = struct.unpack_from(
                        "<IBBHQQ", self.data, offset + i * 24)
                self.symbols.append({"st_name": st_name, "st_value": st_value})
        except Exception:
            self.symbols = []

    def symbol_name(self, symbol: Dict[str, Any]) -> str:
        strtab = self._dyn(consts.DT_STRTAB)
        if strtab is None:
            return ""
        try:
            return self.read_string_to_null(self.map_vatr(strtab) + symbol["st_name"], 256)
        except Exception:
            return ""

    # ------------------------------------------------------------------
    def _apply_relocations(self) -> None:
        self._say("Applying relocations...")
        applied = 0
        applied += self._apply_rela()
        applied += self._apply_rel()
        self._say("Applied %d relocations." % applied)

    def _apply_rela(self) -> int:
        rela = self._dyn(consts.DT_RELA)
        size = self._dyn(consts.DT_RELASZ)
        if rela is None or not size:
            return 0
        try:
            offset = self.map_vatr(rela)
        except (ValueError, IndexError):
            return 0
        applied = 0
        if self.is32bit:
            entry_size, count = 12, size // 12
            for i in range(count):
                r_offset, r_info, r_addend = struct.unpack_from(
                    "<IIi", self.data, offset + i * 12)
                rtype = r_info & 0xFF
                symbol = r_info >> 8
                value = self._resolve_relocation(rtype, symbol, r_addend, False)
                if value is not None and self._write_word(r_offset, value):
                    applied += 1
        else:
            entry_size, count = 24, size // 24
            for i in range(count):
                r_offset, r_info, r_addend = struct.unpack_from(
                    "<QQq", self.data, offset + i * 24)
                rtype = r_info & 0xFFFFFFFF
                symbol = r_info >> 32
                value = self._resolve_relocation(rtype, symbol, r_addend, True)
                if value is not None and self._write_word(r_offset, value):
                    applied += 1
        return applied

    def _apply_rel(self) -> int:
        rel = self._dyn(consts.DT_REL)
        size = self._dyn(consts.DT_RELSZ)
        if rel is None or not size or not self.is32bit:
            return 0
        try:
            offset = self.map_vatr(rel)
        except (ValueError, IndexError):
            return 0
        applied = 0
        count = size // 8
        for i in range(count):
            r_offset, r_info = struct.unpack_from("<II", self.data, offset + i * 8)
            rtype = r_info & 0xFF
            symbol = r_info >> 8
            value = self._resolve_relocation(rtype, symbol, 0, False)
            if value is not None and self._write_word(r_offset, value):
                applied += 1
        return applied

    def _resolve_relocation(self, rtype: int, symbol: int, addend: int,
                            is64: bool) -> Optional[int]:
        absolute = {consts.R_ARM_ABS32, consts.R_386_32,
                    consts.R_X86_64_64, consts.R_AARCH64_ABS64}
        relative = {consts.R_ARM_RELATIVE, consts.R_386_RELATIVE,
                    consts.R_X86_64_RELATIVE, consts.R_AARCH64_RELATIVE}
        if rtype in absolute:
            if symbol < len(self.symbols):
                return (self.symbols[symbol]["st_value"] + addend) & _mask(is64)
            return None
        if rtype in relative:
            return addend & _mask(is64)
        return None

    def _write_word(self, vaddr: int, value: int) -> bool:
        try:
            offset = self.map_vatr(vaddr)
        except (ValueError, IndexError):
            return False
        size = self.pointer_size
        if offset + size > len(self.data):
            return False
        self.data[offset:offset + size] = (value & _mask(not self.is32bit)).to_bytes(
            size, "little")
        return True

    # ------------------------------------------------------------------
    def _check_protection(self) -> None:
        notes = self.protection_notes
        if self._dyn(consts.DT_INIT) is not None:
            notes.append("DT_INIT (.init_proc) present")
        for symbol in self.symbols:
            if self.symbol_name(symbol) == "JNI_OnLoad":
                notes.append("JNI_OnLoad export present")
                break
        self.may_be_protected = bool(notes)
        for note in notes:
            self._say("WARNING: %s - the binary may be protected." % note)

    # ------------------------------------------------------------------
    def check_dump(self) -> bool:
        return ".text" not in self.section_names

    def map_vatr(self, address: int) -> int:
        for segment in self.program_segments:
            if segment["p_type"] != consts.PT_LOAD:
                continue
            start = segment["p_vaddr"]
            if start <= address <= start + segment["p_memsz"]:
                return address - start + segment["p_offset"]
        raise ValueError("Virtual address 0x%X is not inside any load segment." % address)

    def map_rtva(self, offset: int) -> int:
        for segment in self.program_segments:
            if segment["p_type"] != consts.PT_LOAD:
                continue
            if segment["p_offset"] <= offset <= segment["p_offset"] + segment["p_filesz"]:
                return offset - segment["p_offset"] + segment["p_vaddr"]
        return 0

    def get_rva(self, pointer: int) -> int:
        if self.is_dumped:
            return pointer - self.image_base
        return pointer

    def sections(self) -> Tuple[List[SearchSection], List[SearchSection]]:
        data_sections: List[SearchSection] = []
        exec_sections: List[SearchSection] = []
        for segment in self.program_segments:
            if segment["p_memsz"] == 0 or segment["p_type"] != consts.PT_LOAD:
                continue
            flags = segment["p_flags"]
            if flags in (1, 3, 5, 7):
                exec_sections.append(SearchSection(
                    segment["p_offset"], segment["p_offset"] + segment["p_filesz"],
                    segment["p_vaddr"], segment["p_vaddr"] + segment["p_memsz"]))
            elif flags in (2, 4, 6):
                data_sections.append(SearchSection(
                    segment["p_offset"], segment["p_offset"] + segment["p_filesz"],
                    segment["p_vaddr"], segment["p_vaddr"] + segment["p_memsz"]))
        return exec_sections, data_sections

    def symbol_search(self) -> bool:
        code_registration = 0
        metadata_registration = 0
        for symbol in self.symbols:
            name = self.symbol_name(symbol)
            if name == "g_CodeRegistration":
                code_registration = symbol["st_value"]
            elif name == "g_MetadataRegistration":
                metadata_registration = symbol["st_value"]
        if code_registration and metadata_registration:
            self._say("Detected exported registration symbols.")
            self._say("CodeRegistration     : 0x%X" % code_registration)
            self._say("MetadataRegistration : 0x%X" % metadata_registration)
            self.init(code_registration, metadata_registration)
            return True
        self._say("No g_CodeRegistration / g_MetadataRegistration symbols found.")
        return False

    # ------------------------------------------------------------------
    @property
    def abi(self) -> str:
        return {
            consts.EM_ARM: "armeabi-v7a",
            consts.EM_AARCH64: "arm64-v8a",
            consts.EM_386: "x86",
            consts.EM_X86_64: "x86_64",
        }.get(self.machine, "machine-%d" % self.machine)


def _mask(is64: bool) -> int:
    return 0xFFFFFFFFFFFFFFFF if is64 else 0xFFFFFFFF
