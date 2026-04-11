"""
Verb expander — expand high-level verbs into primitive sequences.

Loads verb YAML definitions from the verb library directory and resolves
them into the intermediate representation consumed by the BT emitter and
capability gate. Each expanded verb carries its Jinja2 template name,
required capabilities, and caller-supplied parameter values.

Supports ``extends: defined/<name>`` for inheriting from built-in verbs.
Merge rules:
- ``dependencies``: additive union (apt/source/pip lists concatenate, deduplicated)
- All other top-level keys: shallow replace (local replaces base entirely)

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

_EXTENDS_PREFIX = "defined/"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _deduplicated(items: list) -> list:
    """Deduplicate a list preserving order."""
    seen: set = set()
    result = []
    for item in items:
        # For dicts (source deps), use a frozen representation
        key = repr(item) if isinstance(item, dict) else item
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _merge_dependencies(base_deps: dict[str, Any], local_deps: dict[str, Any]) -> dict[str, Any]:
    """Merge dependencies additively — union per category, deduplicated."""
    merged: dict[str, Any] = {}

    # apt: concatenate and deduplicate
    merged["apt"] = _deduplicated(
        base_deps.get("apt", []) + local_deps.get("apt", [])
    )

    # source: concatenate (dedup by repr since dicts aren't hashable)
    merged["source"] = _deduplicated(
        base_deps.get("source", []) + local_deps.get("source", [])
    )

    # pip: concatenate and deduplicate
    merged["pip"] = _deduplicated(
        base_deps.get("pip", []) + local_deps.get("pip", [])
    )

    return merged


def _load_builtin_verb(verb_name: str) -> dict[str, Any]:
    """Load a built-in verb definition from the default library."""
    path = DEFAULT_VERB_LIBRARY_DIR / f"{verb_name}.yaml"
    if not path.exists():
        raise ValueError(
            f"Built-in verb '{verb_name}' not found "
            f"(no definition at {path})"
        )
    with path.open() as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Public API
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
        if verbs_dir is not None:
            # Fall back to built-in library
            builtin_path = DEFAULT_VERB_LIBRARY_DIR / f"{verb_name}.yaml"
            if not builtin_path.exists():
                raise ValueError(f"Unknown verb: {verb_name} (no definition at {path} or {builtin_path})")
            return _load_builtin_verb(verb_name)
        raise ValueError(f"Unknown verb: {verb_name} (no definition at {path})")
    with path.open() as f:
        return yaml.safe_load(f)


def resolve_verb_definition(verb_name: str, verbs_dir: Path | None = None) -> dict[str, Any]:
    """Load and resolve a verb definition, handling ``extends``.

    If the verb has ``extends: defined/<base>``, the base verb is loaded
    from the built-in library and merged with the local definition.

    Merge rules:
    - ``dependencies``: additive union (apt/source/pip concatenate, deduplicated)
    - All other top-level keys: shallow replace (local replaces base)

    Args:
        verb_name: Identifier of the verb (e.g. ``"go_to"``).
        verbs_dir: Project verb directory. Falls back to built-in library.

    Returns:
        Fully resolved verb definition dict.

    Raises:
        ValueError: If extends target not found or has invalid prefix.
    """
    local = load_verb_definition(verb_name, verbs_dir)
    extends = local.get("extends")

    if extends is None:
        return local

    # Validate extends prefix
    if not extends.startswith(_EXTENDS_PREFIX):
        raise ValueError(
            f"Verb '{verb_name}' has extends: '{extends}' — "
            f"only '{_EXTENDS_PREFIX}<name>' is supported in v0.1.0"
        )

    base_name = extends[len(_EXTENDS_PREFIX):]
    base = _load_builtin_verb(base_name)

    # Merge: start with base, override with local (shallow replace)
    resolved = dict(base)
    for key, value in local.items():
        if key == "extends":
            continue
        if key == "dependencies":
            # Additive merge for dependencies
            base_deps = base.get("dependencies") or {}
            local_deps = value or {}
            resolved["dependencies"] = _merge_dependencies(base_deps, local_deps)
        else:
            # Shallow replace for everything else
            resolved[key] = value

    return resolved


def expand_verb(verb_name: str, params: dict[str, Any], verbs_dir: Path | None = None) -> dict[str, Any]:
    """Expand a verb into its intermediate representation.

    Loads the verb's YAML definition (resolving ``extends`` if present)
    and merges it with the caller-supplied parameter values, producing
    the dict that the BT emitter and capability gate consume.

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
    definition = resolve_verb_definition(verb_name, verbs_dir)
    return {
        "verb": verb_name,
        "params": params,
        "template": definition.get("template", f"{verb_name}.xml.j2"),
        "required_capabilities": definition.get("required_capabilities", []),
        "primitives": definition.get("primitives", []),
    }
