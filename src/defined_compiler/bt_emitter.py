"""BT XML emitter — render BehaviorTree.CPP XML from expanded verbs."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

DEFAULT_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "verb_library"


def render_bt_xml(expanded_verbs: list[dict], task_name: str = "MainTask", verbs_dir: Path | None = None) -> str:
    """Render a complete BehaviorTree.CPP XML from a list of expanded verbs."""
    template_dir = verbs_dir if verbs_dir is not None else DEFAULT_TEMPLATE_DIR
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Render each verb's subtree
    subtrees = []
    for verb_data in expanded_verbs:
        template = env.get_template(verb_data["template"])
        subtree_xml = template.render(**verb_data["params"])
        subtrees.append(subtree_xml)

    # Wrap in a BehaviorTree root
    children = "\n        ".join(subtrees)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<root BTCPP_format="4">
    <BehaviorTree ID="{task_name}">
        <Sequence name="{task_name}_seq">
        {children}
        </Sequence>
    </BehaviorTree>
</root>
"""
