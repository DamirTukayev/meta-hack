"""Model prompts live in versioned text files next to this module (`<name>.<version>.txt`).

`active.json` says which version each part of the pipeline uses; code asks for a prompt by name, so a prompt can
be improved, compared on real runs (`scripts/eval_grounding.py`) and rolled back without touching Python code.
"""

from __future__ import annotations

import json
from pathlib import Path

DIR = Path(__file__).parent


def active_version(name: str) -> str:
    return json.loads((DIR / "active.json").read_text())[name]


def versions(name: str) -> list[str]:
    return sorted(p.name.split(".")[1] for p in DIR.glob(f"{name}.*.txt"))


def load(name: str, version: str | None = None) -> tuple[str, str]:
    """Returns (version, text) of a prompt; the active version when none is given."""
    version = version or active_version(name)
    path = DIR / f"{name}.{version}.txt"
    if not path.exists():
        raise KeyError(f"no prompt {name!r} version {version!r} (have: {versions(name)})")
    return version, path.read_text().strip()
