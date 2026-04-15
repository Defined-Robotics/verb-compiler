"""
BT XML emitter — render BehaviorTree.CPP v4 XML from expanded verbs.

Takes the intermediate representation produced by the verb expander and
renders a complete BehaviorTree.CPP v4 XML document, including the
``<TreeNodesModel>`` port manifest required by Groot2.

Usage:
    from defined_compiler.bt_emitter import render_bt_xml

    xml = render_bt_xml(expanded_verbs, task_name="PatrolTask")
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import FileSystemLoader, select_autoescape
from jinja2.sandbox import SandboxedEnvironment

from defined_compiler.verb_expander import resolve_verb_definition

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE_DIR = Path(__file__).parent / "verb_library"

# ---------------------------------------------------------------------------
# TreeNodesModel — declares input/output ports so BT.CPP and Groot2 know the
# contract for each custom action node.
# Built dynamically from verb YAML definitions.
# ---------------------------------------------------------------------------


def _build_tree_nodes_model(verb_names: list[str], verbs_dir: Path | None) -> str:
    """Generate ``<TreeNodesModel>`` XML from verb definition YAMLs.

    Uses ``resolve_verb_definition`` so that stubs with ``extends``
    inherit port declarations from their base verb.

    Args:
        verb_names: Ordered list of verb identifiers used in the task.
            Duplicates are deduplicated automatically.
        verbs_dir: Project verb directory (or ``None`` for built-in only).

    Returns:
        XML string for the ``<TreeNodesModel>`` block, including
        ``<input_port>`` and ``<output_port>`` declarations.
    """
    lines = ["    <TreeNodesModel>"]
    seen = set()

    for verb_name in verb_names:
        if verb_name in seen:
            continue
        seen.add(verb_name)

        try:
            defn = resolve_verb_definition(verb_name, verbs_dir)
        except ValueError:
            continue

        # Action ID is PascalCase of the verb name
        action_id = "".join(w.capitalize() for w in verb_name.split("_"))
        params = defn.get("parameters", {})

        output_params = defn.get("output_parameters", {})

        if not params and not output_params:
            lines.append(f'        <Action ID="{action_id}" />')
        else:
            lines.append(f'        <Action ID="{action_id}">')
            for pname, pinfo in params.items():
                default = pinfo.get("default", "")
                desc = pinfo.get("description", "")
                lines.append(
                    f'            <input_port name="{pname}" default="{default}">{desc}</input_port>'
                )
            for pname, pinfo in output_params.items():
                desc = pinfo.get("description", "")
                lines.append(
                    f'            <output_port name="{pname}">{desc}</output_port>'
                )
            lines.append("        </Action>")

    lines.append("    </TreeNodesModel>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_bt_xml(
    expanded_verbs: list[dict[str, Any]],
    task_name: str = "MainTask",
    verbs_dir: Path | None = None,
) -> str:
    """Render a complete BehaviorTree.CPP v4 XML document.

    Takes the list of expanded verb dicts produced by
    :func:`defined_compiler.verb_expander.expand_verb` and renders them
    through their Jinja2 templates into a single BT XML document with a
    ``<TreeNodesModel>`` port manifest.

    Args:
        expanded_verbs: Sequence of expanded verb dicts, each containing
            keys ``verb``, ``params``, ``template``, and
            ``required_capabilities``.
        task_name: Name for the root ``<BehaviorTree>`` ID and the wrapping
            ``<Sequence>``. Defaults to ``"MainTask"``.
        verbs_dir: Directory containing the Jinja2 template files and verb
            YAML definitions. Defaults to the built-in ``verb_library/``.

    Returns:
        Complete BehaviorTree.CPP v4 XML as a string.
    """
    # Build search path: project dir (if given) + built-in library fallback.
    # Jinja2 FileSystemLoader checks directories in order, so project
    # templates shadow built-in ones — matching verb_expander's resolution.
    search_dirs: list[Path] = []
    if verbs_dir is not None:
        search_dirs.append(verbs_dir)
    if DEFAULT_TEMPLATE_DIR not in search_dirs:
        search_dirs.append(DEFAULT_TEMPLATE_DIR)

    env = SandboxedEnvironment(
        loader=FileSystemLoader([str(d) for d in search_dirs]),
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=select_autoescape(enabled_extensions=["xml"], default_for_string=False),
    )

    # Render each verb's action XML
    subtrees = []
    for verb_data in expanded_verbs:
        template = env.get_template(verb_data["template"])
        subtree_xml = template.render(**verb_data["params"])
        subtrees.append(subtree_xml)

    # Indent action nodes inside the Sequence (handle multi-line templates)
    indented_lines = []
    for s in subtrees:
        for line in s.splitlines():
            indented_lines.append(f"            {line}")
    children = "\n".join(indented_lines)

    # Build port manifest from verb definitions
    verb_names = [v["verb"] for v in expanded_verbs]
    tree_nodes_model = _build_tree_nodes_model(verb_names, verbs_dir)

    # Suffix the tree ID to avoid collisions with registered action node
    # names (e.g. task "Explore" would collide with Action ID="Explore").
    tree_id = f"{task_name}Tree"

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<root BTCPP_format="4">
    <BehaviorTree ID="{tree_id}">
        <Sequence name="{task_name}_seq">
{children}
        </Sequence>
    </BehaviorTree>
{tree_nodes_model}
</root>
"""
