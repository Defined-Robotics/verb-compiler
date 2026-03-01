"""YAML task parser — loads verb task files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_task(path: str | Path) -> dict[str, Any]:
    """Load a YAML task file and return the raw task dict."""
    path = Path(path)
    with path.open() as f:
        data = yaml.safe_load(f)
    return data
