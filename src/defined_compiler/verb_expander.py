"""
Verb expander — expand high-level verbs into primitive sequences.

Loads verb YAML definitions from the verb library directory and resolves
them into the intermediate representation consumed by the BT emitter and
capability gate. Each expanded verb carries its Jinja2 template name,
required capabilities, and caller-supplied parameter values.

Usage:
    from defined_compiler.verb_expander import expand_verb

    verb_data = expand_verb("go_to", {"waypoint": "dock"})
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_VERB_LIBRARY_DIR = Path(__file__).parent.parent.parent / "verb_library"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def load_verb_definition(verb_name: str, verbs_dir: Path | None = None) -> dict[str, Any]:
    """Load a verb definition YAML from the verb library.

    Args:
        verb_name: Identifier of the verb (e.g. ``"go_to"``).
        verbs_dir: Directory to search. Defaults to the built-in
            ``verb_library/`` shipped with defined-compiler.

    Returns:
        Parsed verb definition as a plain Python dict.

    Raises:
        ValueError: If no YAML definition file exists for ``verb_name``.
    """
    search_dir = verbs_dir if verbs_dir is not None else DEFAULT_VERB_LIBRARY_DIR
    path = search_dir / f"{verb_name}.yaml"
    if not path.exists():
        raise ValueError(f"Unknown verb: {verb_name} (no definition at {path})")
    with path.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def expand_verb(verb_name: str, params: dict[str, Any], verbs_dir: Path | None = None) -> dict[str, Any]:
    """Expand a verb into its intermediate representation.

    Loads the verb's YAML definition and merges it with the caller-supplied
    parameter values, producing the dict that the BT emitter and capability
    gate consume.

    Args:
        verb_name: Identifier of the verb (e.g. ``"go_to"``).
        params: Key/value parameters supplied by the task YAML.
        verbs_dir: Directory containing verb YAML and Jinja2 template files.
            Defaults to the built-in ``verb_library/``.

    Returns:
        Dict with keys ``verb``, ``params``, ``template``,
        ``required_capabilities``, and ``primitives``.

    Raises:
        ValueError: If the verb has no definition in the library.
    """
    definition = load_verb_definition(verb_name, verbs_dir)
    return {
        "verb": verb_name,
        "params": params,
        "template": definition.get("template", f"{verb_name}.xml.j2"),
        "required_capabilities": definition.get("required_capabilities", []),
        "primitives": definition.get("primitives", []),
    }
