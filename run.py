#!/usr/bin/env python3
"""
IL2CPP Dumper Studio - launcher.

    python3 run.py                 # start the web studio
    python3 run.py cli a.apk       # run the command-line dumper
    python3 run.py cli a.so b.dat  # run on an explicit pair

The web front end binds to ``0.0.0.0`` so it works in this sandbox's live
preview, behind the Google Colab reverse proxy, or on ``localhost``.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)


def main(argv):
    if argv and argv[0] == "cli":
        from dumper.cli import main as cli_main
        return cli_main(argv[1:])
    from app.server import main as server_main
    return server_main()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
