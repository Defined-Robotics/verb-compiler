"""
YAML task parser — loads verb task files.

Reads a task YAML from disk and returns the raw Python dict. The caller
is responsible for schema validation and verb expansion.

Usage:
    from defined_compiler.parser import load_task

    task = load_task("patrol.task.yaml")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_task(path: str | Path) -> dict[str, Any]:
    """Load a YAML task file and return the raw task dict.

    Args:
        path: Filesystem path to the task YAML file.

    Returns:
        Parsed task as a plain Python dict.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError: If the file is not valid YAML.
    """
    path = Path(path)
    with path.open() as f:
        data = yaml.safe_load(f)
    return data
