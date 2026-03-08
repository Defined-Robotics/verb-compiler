"""CLI entry point for the verb compiler."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from defined_rdf.parser import load as load_rdf
from defined_rdf.registry import CapabilityRegistry

from . import bt_emitter, capability_gate, parser, urdf_emitter, verb_expander


def main() -> None:
    ap = argparse.ArgumentParser(description="Compile YAML verb tasks to BehaviorTree.CPP XML")
    ap.add_argument("task", type=Path, nargs="?", help="Path to YAML task file (not needed with --generate-urdf)")
    ap.add_argument("--rdf", type=Path, required=True, help="Path to RDF YAML file")
    ap.add_argument("--output", "-o", type=Path, help="Output file (default: stdout)")
    ap.add_argument("--verbs-dir", type=Path, default=None,
                    help="Directory containing verb YAML and Jinja2 template files")
    ap.add_argument("--generate-urdf", action="store_true",
                    help="Generate URDF xacro from RDF physical description instead of BT XML")
    args = ap.parse_args()

    # Load RDF
    robot = load_rdf(args.rdf)

    # --generate-urdf mode: render URDF xacro and exit
    if args.generate_urdf:
        try:
            xacro = urdf_emitter.render_urdf(robot)
        except ValueError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
        if args.output:
            args.output.write_text(xacro)
            print(f"Written to {args.output}")
        else:
            print(xacro)
        return

    # Normal BT compilation mode
    if args.task is None:
        ap.error("task argument is required when not using --generate-urdf")

    registry = CapabilityRegistry(robot)
    verbs_dir = args.verbs_dir

    # Load task
    task = parser.load_task(args.task)

    # Expand verbs and gate capabilities
    expanded = []
    for step in task.get("steps", []):
        verb_name = step["verb"]
        params = step.get("params", {})
        verb_data = verb_expander.expand_verb(verb_name, params, verbs_dir=verbs_dir)

        # Capability gate
        result = capability_gate.check(registry, verb_data["required_capabilities"])
        if not result.passed:
            print(f"REJECTED: verb '{verb_name}' requires capabilities {result.missing} "
                  f"not available on robot '{registry.robot_name}'", file=sys.stderr)
            sys.exit(1)

        expanded.append(verb_data)

    # Emit BT XML
    task_name = task.get("name", "CompiledTask")
    xml = bt_emitter.render_bt_xml(expanded, task_name=task_name, verbs_dir=verbs_dir)

    if args.output:
        args.output.write_text(xml)
        print(f"Written to {args.output}")
    else:
        print(xml)


if __name__ == "__main__":
    main()
