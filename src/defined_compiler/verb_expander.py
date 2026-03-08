"""Verb expander — expand high-level verbs into primitive sequences."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

DEFAULT_VERB_LIBRARY_DIR = Path(__file__).parent.parent.parent / "verb_library"


def load_verb_definition(verb_name: str, verbs_dir: Path | None = None) -> dict[str, Any]:
    """Load a verb definition YAML from the verb library."""
    search_dir = verbs_dir if verbs_dir is not None else DEFAULT_VERB_LIBRARY_DIR
    path = search_dir / f"{verb_name}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown verb: {verb_name} (no definition at {path})")
    with path.open() as f:
        return yaml.safe_load(f)


def expand_verb(verb_name: str, params: dict[str, Any], verbs_dir: Path | None = None) -> dict[str, Any]:
    """Expand a verb into its primitive sequence with resolved parameters."""
    definition = load_verb_definition(verb_name, verbs_dir)
    return {
        "verb": verb_name,
        "params": params,
        "template": definition.get("template", f"{verb_name}.xml.j2"),
        "required_capabilities": definition.get("required_capabilities", []),
        "primitives": definition.get("primitives", []),
    }
