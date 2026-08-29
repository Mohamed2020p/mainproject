"""``stringliteral.json`` - every managed string literal baked into the game."""

from __future__ import annotations

import json
from typing import List

from ..metadata import Metadata


def collect_string_literals(metadata: Metadata, limit: int = 0) -> List[str]:
    literals: List[str] = []
    for index in range(len(metadata.stringLiterals)):
        try:
            literals.append(metadata.get_string_literal_from_index(index))
        except Exception:
            literals.append("")
        if limit and len(literals) >= limit:
            break
    return literals


def write_string_literals(metadata: Metadata, path: str) -> List[str]:
    literals = collect_string_literals(metadata)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(literals, handle, ensure_ascii=False, indent=1)
    return literals
