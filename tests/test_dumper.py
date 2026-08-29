"""
Test suite for the IL2CPP dumper.

Run with::

    python -m pytest -q            # if pytest is available
    python tests/test_dumper.py    # plain-python fallback (no dependencies)

The tests build a synthetic ``libil2cpp.so`` + ``global-metadata.dat`` pair
(see ``tests/fixture.py``) and then run the real dumper over it, so every layer
is exercised: metadata parsing, ELF loading, the ``Il2CppType`` table, the
``dump.cs`` writer, ``script.json``, ``il2cpp.h`` and the ``DummyDll``
ECMA-335 writer.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dumper.binary import open_binary                     # noqa: E402
from dumper.executor import Executor                      # noqa: E402
from dumper.metadata import Metadata, is_metadata_file     # noqa: E402
from dumper.pipeline import DumpOptions, dump_apk, dump_bytes, dump_files  # noqa: E402
from tests import fixture                                 # noqa: E402


class MetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = Metadata(fixture.build_metadata())

    def test_sanity_and_version(self) -> None:
        blob = fixture.build_metadata()
        self.assertTrue(is_metadata_file(blob[:4]))
        self.assertEqual(self.metadata.version, 24.2,
                         "Unity 2019 metadata must resolve to version 24.2")

    def test_structure_counts(self) -> None:
        self.assertEqual(len(self.metadata.imageDefs), 2)
        self.assertEqual(len(self.metadata.assemblyDefs), 2)
        self.assertEqual(len(self.metadata.typeDefs), 5)
        self.assertEqual(len(self.metadata.methodDefs), 5)
        self.assertEqual(len(self.metadata.fieldDefs), 2)
        self.assertEqual(len(self.metadata.parameterDefs), 3)
        self.assertEqual(len(self.metadata.propertyDefs), 1)
        self.assertEqual(len(self.metadata.stringLiterals), 1)

    def test_strings(self) -> None:
        self.assertEqual(self.metadata.get_string_from_index(
            self.metadata.imageDefs[0]["nameIndex"]), "mscorlib.dll")
        self.assertEqual(self.metadata.get_string_from_index(
            self.metadata.imageDefs[1]["nameIndex"]), "Assembly-CSharp.dll")
        self.assertEqual(self.metadata.get_string_literal_from_index(0), "Hello")

    def test_metadata_usage_count(self) -> None:
        self.assertEqual(self.metadata.metadataUsagesCount, 2)

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(Exception):
            Metadata(b"not a metadata file at all")


class BinaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = Metadata(fixture.build_metadata())
        cls.binary = open_binary(fixture.build_binary())

    def test_elf_detected(self) -> None:
        self.assertEqual(self.binary.format_name, "ELF64")
        self.assertFalse(self.binary.is32bit)
        self.assertEqual(self.binary.abi, "arm64-v8a")
        self.assertIn(".text", self.binary.section_names)
        self.assertFalse(self.binary.check_dump())

    def test_symbol_search(self) -> None:
        self.binary.set_properties(self.metadata.version,
                                   self.metadata.metadataUsagesCount)
        self.assertTrue(self.binary.symbol_search())
        self.assertEqual(len(self.binary.types), 8)
        self.assertEqual(self.binary.code_gen_modules.keys(),
                         {"mscorlib.dll", "Assembly-CSharp.dll"})
        self.assertEqual(len(self.binary.code_gen_module_method_pointers
                             ["Assembly-CSharp.dll"]), 5)

    def test_heuristic_search_finds_the_same_tables(self) -> None:
        binary = open_binary(fixture.build_binary())
        binary.set_properties(self.metadata.version,
                              self.metadata.metadataUsagesCount)
        self.assertTrue(binary.plus_search(len(self.metadata.methodDefs),
                                           len(self.metadata.typeDefs),
                                           len(self.metadata.imageDefs)),
                        "SectionHelper must locate both registration tables")
        self.assertEqual(len(binary.types), 8)

    def test_method_pointers(self) -> None:
        self.binary.set_properties(self.metadata.version,
                                   self.metadata.metadataUsagesCount)
        self.binary.symbol_search()
        method = self.metadata.methodDefs[1]           # get_Health
        pointer = self.binary.get_method_pointer("Assembly-CSharp.dll", method)
        self.assertNotEqual(pointer, 0)
        self.assertEqual(self.binary.get_rva(pointer), pointer)

    def test_field_offsets(self) -> None:
        self.binary.set_properties(self.metadata.version,
                                   self.metadata.metadataUsagesCount)
        self.binary.symbol_search()
        # Player is typedef 3, "health" is field 0 inside it.
        self.assertEqual(
            self.binary.get_field_offset_from_index(3, 0, 0, False, False), 16)
        self.assertEqual(
            self.binary.get_field_offset_from_index(3, 1, 1, False, False), 24)


class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.metadata = Metadata(fixture.build_metadata())
        cls.binary = open_binary(fixture.build_binary())
        cls.binary.set_properties(cls.metadata.version,
                                  cls.metadata.metadataUsagesCount)
        cls.binary.symbol_search()
        cls.executor = Executor(cls.metadata, cls.binary)

    def test_mode(self) -> None:
        self.assertEqual(self.executor.mode(), "full")

    def test_primitive_type_names(self) -> None:
        self.assertEqual(self.executor.get_type_name(
            self.executor.type_at(0), False, False), "void")
        self.assertEqual(self.executor.get_type_name(
            self.executor.type_at(2), False, False), "int")
        self.assertEqual(self.executor.get_type_name(
            self.executor.type_at(3), False, False), "string")

    def test_class_and_valuetype_names(self) -> None:
        self.assertEqual(self.executor.get_type_name(
            self.executor.type_at(1), True, False), "System.Object")
        self.assertEqual(self.executor.get_type_name(
            self.executor.type_at(4), True, False), "Game.Player")
        self.assertEqual(self.executor.get_type_name(
            self.executor.type_at(5), True, False), "System.Int32")

    def test_array_type_name(self) -> None:
        self.assertEqual(self.executor.get_type_name(
            self.executor.type_at(7), False, False), "string[]")

    def test_typedef_name(self) -> None:
        typedef = self.metadata.typeDefs[3]
        self.assertEqual(self.executor.get_type_def_name(typedef, True, True),
                         "Game.Player")

    def test_default_value_reader(self) -> None:
        metadata = self.metadata
        blob = bytearray(metadata.data)
        offset = metadata.header["fieldAndParameterDefaultValueDataOffset"]
        blob[offset:offset + 4] = struct.pack("<i", 42)
        reader = Executor(Metadata(bytes(blob)), self.binary)
        ok, value = reader.try_get_default_value(2, 0)     # TYPE_I4
        self.assertTrue(ok)
        self.assertEqual(value, 42)


class PipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def _options(self) -> DumpOptions:
        return DumpOptions(output_dir=os.path.join(self.dir, "dump"))

    def test_full_dump(self) -> None:
        binary = fixture.build_binary()
        metadata = fixture.build_metadata()
        result = dump_bytes(binary, metadata, self._options())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.mode, "full")

        names = {item["name"] for item in result.files}
        for expected in ("dump.cs", "il2cpp.h", "script.json",
                         "stringliteral.json", "DummyDll/",
                         "dump-manifest.json"):
            self.assertIn(expected, names)

        self.assertEqual(result.stats["dumpedTypes"], 5)
        self.assertEqual(result.stats["dumpedMethods"], 5)
        self.assertEqual(result.stats["dumpedFields"], 2)
        self.assertEqual(result.stats["dummyDllCount"], 2)

        dump = open(os.path.join(self.dir, "dump", "dump.cs"),
                    encoding="utf-8").read()
        self.assertIn("namespace", dump.lower())
        self.assertIn("class Player", dump)
        self.assertIn("Game", dump)
        self.assertIn("int health;", dump)
        self.assertIn("string name;", dump)
        self.assertIn("int get_Health()", dump)
        self.assertIn("void TakeDamage(int amount)", dump)
        self.assertIn("// 0x10", dump)
        self.assertIn("// Image 0: mscorlib.dll - 0", dump)
        self.assertIn("TypeDefIndex: 3", dump)

        script = json.load(open(os.path.join(self.dir, "dump", "script.json"),
                                encoding="utf-8"))
        self.assertEqual(len(script["ScriptMethod"]), 5)
        self.assertTrue(any("get_Health" in m["Name"] for m in script["ScriptMethod"]))

        literals = json.load(open(os.path.join(self.dir, "dump",
                                               "stringliteral.json"),
                                  encoding="utf-8"))
        self.assertEqual(literals, ["Hello"])

    def test_metadata_only_mode(self) -> None:
        result = dump_bytes(b"", fixture.build_metadata(), self._options())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.mode, "metadata")
        dump = open(os.path.join(self.dir, "dump", "dump.cs"),
                    encoding="utf-8").read()
        self.assertIn("class Player", dump)
        self.assertIn("TypeIndex:", dump)

    def test_swapped_inputs_are_repaired(self) -> None:
        result = dump_bytes(fixture.build_metadata(), fixture.build_binary(),
                            self._options())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.mode, "full")

    def test_encrypted_metadata_is_reported(self) -> None:
        result = dump_bytes(fixture.build_binary(), b"\x00" * 512, self._options())
        self.assertFalse(result.ok)
        self.assertIn("global-metadata.dat", result.error)

    def test_dump_from_files_on_disk(self) -> None:
        binary_path, metadata_path = fixture.write_fixture(
            os.path.join(self.dir, "input"))
        result = dump_files(binary_path, metadata_path, self._options())
        self.assertTrue(result.ok, result.error)
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "dump", "dump.cs")))

    def test_apk_extraction_and_dump(self) -> None:
        apk_path = os.path.join(self.dir, "game.apk")
        with zipfile.ZipFile(apk_path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("lib/arm64-v8a/libil2cpp.so", fixture.build_binary())
            archive.writestr("lib/armeabi-v7a/libil2cpp.so", fixture.build_binary())
            archive.writestr(
                "assets/bin/Data/Managed/Metadata/global-metadata.dat",
                fixture.build_metadata())
            archive.writestr("AndroidManifest.xml", b"<manifest/>")

        result = dump_apk(apk_path, self._options())
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.stats["apk"]["abi"], "arm64-v8a")
        self.assertEqual(result.stats["apk"]["availableAbis"],
                         ["arm64-v8a", "armeabi-v7a"])
        self.assertEqual(result.mode, "full")


class DummyDllTests(unittest.TestCase):
    """The DummyDll assemblies have to be structurally valid PE/CLI files."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = os.path.join(cls.tmp.name, "dump")
        metadata = Metadata(fixture.build_metadata())
        binary = open_binary(fixture.build_binary())
        binary.set_properties(metadata.version, metadata.metadataUsagesCount)
        binary.symbol_search()
        from dumper.outputs.dummy_dll import generate_dummy_dlls
        cls.results = generate_dummy_dlls(Executor(metadata, binary), cls.dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def _read(self, name: str) -> bytes:
        for item in self.results:
            if item["name"] == name:
                with open(item["path"], "rb") as handle:
                    return handle.read()
        raise AssertionError("%s was not produced" % name)

    def test_one_assembly_per_image(self) -> None:
        produced = sorted(r["name"] for r in self.results if r["ok"])
        self.assertEqual(produced, ["Assembly-CSharp.dll", "mscorlib.dll"])

    def test_pe_and_cli_headers(self) -> None:
        for name in ("mscorlib.dll", "Assembly-CSharp.dll"):
            blob = self._read(name)
            self.assertEqual(blob[:2], b"MZ", name)
            e_lfanew = struct.unpack_from("<I", blob, 0x3C)[0]
            self.assertEqual(blob[e_lfanew:e_lfanew + 4], b"PE\x00\x00", name)
            machine, num_sections, _ts, _sp, _ns, opt_size, chars = struct.unpack_from(
                "<HHIIIHH", blob, e_lfanew + 4)
            self.assertEqual(machine, 0x14C)
            self.assertEqual(num_sections, 1)
            self.assertEqual(opt_size, 0xE0)
            self.assertTrue(chars & 0x2000, "must be marked as a DLL")

            cli_rva, cli_size = struct.unpack_from(
                "<II", blob, e_lfanew + 24 + 96 + 14 * 8)
            self.assertEqual(cli_size, 72, name)
            # section header: Name(8) VirtualSize(4) VirtualAddress(4)
            #                 SizeOfRawData(4) PointerToRawData(4) ...
            section_va = struct.unpack_from("<I", blob, e_lfanew + 24 + opt_size + 12)[0]
            section_raw = struct.unpack_from("<I", blob, e_lfanew + 24 + opt_size + 20)[0]
            cli_file_offset = cli_rva - section_va + section_raw
            cb, major, minor, meta_rva, meta_size = struct.unpack_from(
                "<IHHII", blob, cli_file_offset)
            self.assertEqual(cb, 72, name)
            self.assertEqual((major, minor), (2, 5), name)
            self.assertGreater(meta_size, 100, name)

            # CLI metadata signature 0x424A5342 ("BSJB")
            meta_offset = meta_rva - section_va + section_raw
            self.assertEqual(struct.unpack_from("<I", blob, meta_offset)[0],
                             0x424A5342, name)
            self._assert_metadata_parses(blob, meta_offset)

    def _assert_metadata_parses(self, blob: bytes, root: int) -> None:
        """Walk the #~ stream header and check every declared table."""
        version_len = struct.unpack_from("<I", blob, root + 12)[0]
        cursor = root + 16 + version_len
        _flags, stream_count = struct.unpack_from("<HH", blob, cursor)
        cursor += 4
        til = None
        for _ in range(stream_count):
            offset, size = struct.unpack_from("<iI", blob, cursor)
            cursor += 8
            name = b""
            while blob[cursor] != 0:
                name += bytes([blob[cursor]])
                cursor += 1
            cursor += (4 - (len(name) % 4)) % 4 + 1
            cursor = (cursor + 3) & ~3
            if name == b"#~":
                til = (root + offset, size)
        self.assertIsNotNone(til, "#~ stream missing")
        offset, size = til
        _reserved, _major, _minor, heap_sizes, _r2 = struct.unpack_from(
            "<IBBBB", blob, offset)
        valid, sorted_mask = struct.unpack_from("<QQ", blob, offset + 8)
        cursor = offset + 24
        rows = {}
        for table in range(64):
            if valid & (1 << table):
                rows[table] = struct.unpack_from("<I", blob, cursor)[0]
                cursor += 4
        self.assertIn(0x02, rows, "TypeDef table must exist")
        self.assertIn(0x20, rows, "Assembly table must exist")
        self.assertGreaterEqual(rows[0x02], 1)
        self.assertLess(cursor, offset + size)


if __name__ == "__main__":
    unittest.main(verbosity=2)
