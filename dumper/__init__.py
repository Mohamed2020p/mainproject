"""
``il2cppdumper`` - a pure-Python IL2CPP dumper for Android APKs.

Public API::

    from dumper.pipeline import dump_files, dump_apk

    result = dump_files("libil2cpp.so", "global-metadata.dat", "dump")
    print(result.summary())

Everything else in the package is an implementation detail.

Developer: Mohamed Annati
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Mohamed Annati"
__all__ = ["__version__", "__author__"]
