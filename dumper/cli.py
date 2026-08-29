"""
Command line front end.

    python -m dumper.cli <libil2cpp.so | game.apk> [global-metadata.dat] [-o dump]

With one argument the tool decides what it got:

* an archive (``.apk`` / ``.aab`` / ``.xapk``) - both files are extracted,
* a ``libil2cpp.so`` - ``global-metadata.dat`` is looked for next to it,
* a ``global-metadata.dat`` - the ``.so`` is looked for next to it.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional

from . import __author__, __version__
from .apk import ApkError, list_abis, looks_like_archive
from .pipeline import DumpOptions, dump_apk, dump_files


def _head(path: str, count: int = 8) -> bytes:
    with open(path, "rb") as handle:
        return handle.read(count)


def _looks_like_metadata(path: str) -> bool:
    from .metadata import is_metadata_file
    return is_metadata_file(_head(path, 4))


def _find_sibling(directory: str, candidates: List[str]) -> Optional[str]:
    for candidate in candidates:
        path = os.path.join(directory, candidate)
        if os.path.isfile(path):
            return path
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="il2cpp-dumper",
        description="IL2CPP Dumper Studio - dump Unity IL2CPP Android builds.",
        epilog="Developer: %s" % __author__)
    parser.add_argument("inputs", nargs="+",
                        help="APK, libil2cpp.so and/or global-metadata.dat")
    parser.add_argument("-o", "--output", default="dump",
                        help="output folder (default: dump)")
    parser.add_argument("--abi", default=None, choices=["arm64-v8a", "armeabi-v7a",
                                                        "x86_64", "x86"],
                        help="preferred ABI when the APK ships several")
    parser.add_argument("--no-dummy-dll", action="store_true",
                        help="skip rebuilding the DummyDll assemblies")
    parser.add_argument("--no-script-json", action="store_true",
                        help="skip script.json")
    parser.add_argument("--no-il2cpp-header", action="store_true",
                        help="skip il2cpp.h")
    parser.add_argument("--no-string-literals", action="store_true",
                        help="skip stringliteral.json")
    parser.add_argument("--no-field-offset", action="store_true",
                        help="omit field offsets from dump.cs")
    parser.add_argument("--no-method-offset", action="store_true",
                        help="omit RVA / Offset comments from dump.cs")
    parser.add_argument("--quiet", action="store_true", help="only print errors")
    parser.add_argument("--version", action="version",
                        version="il2cpp-dumper %s" % __version__)
    return parser


def _resolve_inputs(paths: List[str]):
    """Work out which input is the archive / binary / metadata."""
    archive = binary = metadata = None
    for path in paths:
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        if _looks_like_metadata(path):
            metadata = path
        elif looks_like_archive(_head(path)):
            archive = path
        else:
            binary = path

    if binary is not None and metadata is None:
        metadata = _find_sibling(os.path.dirname(os.path.abspath(binary)),
                                 ["global-metadata.dat"])
    if metadata is not None and binary is None and archive is None:
        metadata_dir = os.path.dirname(os.path.abspath(metadata))
        binary = _find_sibling(metadata_dir, ["libil2cpp.so"])
    return archive, binary, metadata


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    say = (lambda *_: None) if args.quiet else _print

    try:
        archive, binary, metadata = _resolve_inputs(args.inputs)
    except FileNotFoundError as error:
        print("ERROR: input file not found: %s" % error, file=sys.stderr)
        return 2

    options = DumpOptions(
        output_dir=args.output,
        make_dummy_dll=not args.no_dummy_dll,
        make_script_json=not args.no_script_json,
        make_il2cpp_header=not args.no_il2cpp_header,
        make_string_literals=not args.no_string_literals,
        preferred_abi=args.abi)
    if args.no_field_offset:
        options.dump_config.dump_field_offset = False
    if args.no_method_offset:
        options.dump_config.dump_method_offset = False

    def progress(fraction: float, message: str) -> None:
        bar = "#" * int(fraction * 24)
        sys.stdout.write("\r[%-24s] %3d%%  %s" % (bar, int(fraction * 100), message))
        sys.stdout.flush()
        if fraction >= 1.0:
            sys.stdout.write("\n")

    say("IL2CPP Dumper Studio %s - by %s" % (__version__, __author__))
    try:
        if archive:
            say("Archive : %s (ABIs: %s)"
                % (archive, ", ".join(list_abis(archive)) or "none"))
            result = dump_apk(archive, options, progress)
        elif binary and metadata:
            say("Binary  : %s" % binary)
            say("Metadata: %s" % metadata)
            result = dump_files(binary, metadata, options, progress)
        elif metadata:
            say("Metadata only: %s" % metadata)
            result = dump_files("", metadata, options, progress)
        else:
            print("ERROR: no usable input. Provide an APK, or a "
                  "libil2cpp.so + global-metadata.dat pair.", file=sys.stderr)
            return 2
    except ApkError as error:
        print("ERROR: %s" % error, file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    for line in result.logs:
        say("  " + line)
    if not result.ok:
        print("ERROR: %s" % result.error, file=sys.stderr)
        return 1

    say("")
    say("Output folder: %s" % result.output_dir)
    for item in result.files:
        say("  - %-22s %s" % (item["name"], item["description"]))
    say("Completed in %.2fs" % result.duration_seconds)
    return 0


def _print(*values) -> None:
    print(*values)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
