"""BT XML emitter — render BehaviorTree.CPP v4 XML from expanded verbs."""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

DEFAULT_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "verb_library"

# ---------------------------------------------------------------------------
# TreeNodesModel — declares input/output ports so BT.CPP and Groot2 know the
# contract for each custom action node.
# Built dynamically from verb YAML definitions.
# ---------------------------------------------------------------------------

def _build_tree_nodes_model(verb_names: list[str], verbs_dir: Path) -> str:
    """Generate <TreeNodesModel> XML from verb definition YAMLs."""
    lines = ["    <TreeNodesModel>"]
    seen = set()

    for verb_name in verb_names:
        if verb_name in seen:
            continue
        seen.add(verb_name)

        yaml_path = verbs_dir / f"{verb_name}.yaml"
        if not yaml_path.exists():
            continue

        with open(yaml_path) as f:
            defn = yaml.safe_load(f)

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


def render_bt_xml(
    expanded_verbs: list[dict],
    task_name: str = "MainTask",
    verbs_dir: Path | None = None,
) -> str:
    """Render a complete BehaviorTree.CPP v4 XML from a list of expanded verbs."""
    template_dir = verbs_dir if verbs_dir is not None else DEFAULT_TEMPLATE_DIR
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
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
    tree_nodes_model = _build_tree_nodes_model(verb_names, template_dir)

    return f"""\
<?xml version="1.0" encoding="UTF-8"?>
<root BTCPP_format="4">
    <BehaviorTree ID="{task_name}">
        <Sequence name="{task_name}_seq">
{children}
        </Sequence>
    </BehaviorTree>
{tree_nodes_model}
</root>
"""
