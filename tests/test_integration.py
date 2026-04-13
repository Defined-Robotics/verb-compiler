"""Integration tests — verify the compile pipeline as a user would invoke it.

These tests exercise the full path: task YAML -> expand -> gate -> emit XML,
including CLI invocation, XML validity, custom verbs, and error paths.
"""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

from defined_rdf.parser import load as load_rdf
from defined_rdf.registry import CapabilityRegistry

from defined_compiler import bt_emitter, capability_gate, parser, verb_expander

# Shared paths
VERB_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "src" / "defined_compiler" / "verb_library"
RDF_MVP = Path(__file__).resolve().parent.parent.parent / "rdf" / "examples" / "defined_mvp.rdf.yaml"
PATROL_TASK = Path(__file__).resolve().parent.parent / "examples" / "patrol_task.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compile_task(task_path: Path, rdf_path: Path = RDF_MVP,
                  verbs_dir: Path = VERB_LIBRARY_DIR) -> str:
    """Run the full compile pipeline and return BT XML string."""
    robot = load_rdf(rdf_path)
    registry = CapabilityRegistry(robot)
    task = parser.load_task(task_path)

    expanded = []
    for step in task["steps"]:
        verb_data = verb_expander.expand_verb(
            step["verb"], step.get("params", {}), verbs_dir=verbs_dir
        )
        result = capability_gate.check(registry, verb_data["required_capabilities"])
        if not result.passed:
            raise RuntimeError(
                f"Capability gate failed for '{step['verb']}': missing {result.missing}"
            )
        expanded.append(verb_data)

    return bt_emitter.render_bt_xml(
        expanded, task_name=task.get("name", "Task"), verbs_dir=verbs_dir
    )


def _parse_xml(xml_str: str) -> ET.Element:
    """Parse XML string, raising on any malformed XML."""
    return ET.fromstring(xml_str)


# ---------------------------------------------------------------------------
# 1. Full pipeline — "user compiles patrol_task.yaml"
# ---------------------------------------------------------------------------

class TestFullPipeline:

    def test_patrol_produces_valid_xml(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)
        assert root.tag == "root"
        assert root.attrib["BTCPP_format"] == "4"

    def test_patrol_has_correct_structure(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)

        bt = root.find("BehaviorTree")
        assert bt is not None
        assert bt.attrib["ID"] == "PatrolTask"

        seq = bt.find("Sequence")
        assert seq is not None

        # GoTo verbs are wrapped in RetryUntilSuccessful, others are direct Action children
        # 8 steps total: go_to(retry), report, wait, go_to(retry), report, wait, go_to(retry), report
        direct_children = list(seq)
        assert len(direct_children) == 8

        # All actions (including nested in RetryUntilSuccessful)
        all_actions = list(seq.iter("Action"))
        assert len(all_actions) == 8

    def test_patrol_action_ids_match_verbs(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)
        seq = root.find("BehaviorTree").find("Sequence")
        all_actions = list(seq.iter("Action"))
        ids = [a.attrib["ID"] for a in all_actions]
        assert ids == ["GoTo", "Report", "Wait", "GoTo", "Report", "Wait", "GoTo", "Report"]

    def test_patrol_go_to_has_coordinates(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)
        seq = root.find("BehaviorTree").find("Sequence")
        first_goto = list(seq.iter("Action"))[0]
        assert first_goto.attrib["x"] == "1.0"
        assert first_goto.attrib["y"] == "0.0"
        assert "theta" in first_goto.attrib
        assert "timeout" in first_goto.attrib
        assert first_goto.attrib["frame_id"] == "map"
        assert first_goto.attrib["server_name"] == "/navigate_to_pose"

    def test_patrol_go_to_wrapped_in_retry(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)
        seq = root.find("BehaviorTree").find("Sequence")
        retry_nodes = seq.findall("RetryUntilSuccessful")
        assert len(retry_nodes) == 3  # 3 go_to steps
        for retry in retry_nodes:
            assert retry.attrib["num_attempts"] == "3"
            assert retry.find("Action") is not None
            assert retry.find("Action").attrib["ID"] == "GoTo"

    def test_tree_nodes_model_valid_xml(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)
        model = root.find("TreeNodesModel")
        assert model is not None
        # Should have 3 unique action types declared
        declared = model.findall("Action")
        declared_ids = {a.attrib["ID"] for a in declared}
        assert declared_ids == {"GoTo", "Report", "Wait"}

    def test_go_to_ports_declared(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)
        model = root.find("TreeNodesModel")
        goto_model = [a for a in model.findall("Action") if a.attrib["ID"] == "GoTo"][0]
        input_port_names = {p.attrib["name"] for p in goto_model.findall("input_port")}
        assert input_port_names == {"x", "y", "theta", "timeout", "frame_id", "server_name", "retries"}
        output_port_names = {p.attrib["name"] for p in goto_model.findall("output_port")}
        assert output_port_names == {"error_code"}

    def test_report_ports_declared(self):
        xml = _compile_task(PATROL_TASK)
        root = _parse_xml(xml)
        model = root.find("TreeNodesModel")
        report_model = [a for a in model.findall("Action") if a.attrib["ID"] == "Report"][0]
        input_port_names = {p.attrib["name"] for p in report_model.findall("input_port")}
        assert input_port_names == {"message", "topic", "level"}
        output_port_names = {p.attrib["name"] for p in report_model.findall("output_port")}
        assert output_port_names == {"success"}


# ---------------------------------------------------------------------------
# 2. CLI invocation — "user runs defined-compile from terminal"
# ---------------------------------------------------------------------------

class TestCLI:

    def test_cli_compiles_patrol(self, tmp_path):
        out = tmp_path / "patrol.xml"
        result = subprocess.run(
            [sys.executable, "-m", "defined_compiler.cli",
             str(PATROL_TASK), "--rdf", str(RDF_MVP),
             "--verbs-dir", str(VERB_LIBRARY_DIR),
             "-o", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        xml = out.read_text()
        root = _parse_xml(xml)
        assert root.attrib["BTCPP_format"] == "4"

    def test_cli_rejects_missing_capability(self, tmp_path):
        """Task requires a capability the robot doesn't have."""
        # Create a verb that needs 'flying'
        verb_dir = tmp_path / "verbs"
        verb_dir.mkdir()
        (verb_dir / "fly.yaml").write_text(yaml.dump({
            "name": "fly",
            "required_capabilities": ["flying"],
            "template": "fly.xml.j2",
            "primitives": [],
            "parameters": {},
        }))
        (verb_dir / "fly.xml.j2").write_text('<Action ID="Fly" />')
        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "name": "FlyTask",
            "steps": [{"verb": "fly", "params": {}}],
        }))

        result = subprocess.run(
            [sys.executable, "-m", "defined_compiler.cli",
             str(task_file), "--rdf", str(RDF_MVP),
             "--verbs-dir", str(verb_dir)],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "REJECTED" in result.stderr

    def test_cli_unknown_verb_fails(self, tmp_path):
        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "name": "BadTask",
            "steps": [{"verb": "teleport", "params": {}}],
        }))

        result = subprocess.run(
            [sys.executable, "-m", "defined_compiler.cli",
             str(task_file), "--rdf", str(RDF_MVP),
             "--verbs-dir", str(VERB_LIBRARY_DIR)],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_cli_stdout_when_no_output_flag(self):
        result = subprocess.run(
            [sys.executable, "-m", "defined_compiler.cli",
             str(PATROL_TASK), "--rdf", str(RDF_MVP),
             "--verbs-dir", str(VERB_LIBRARY_DIR)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "<?xml" in result.stdout
        assert "PatrolTask" in result.stdout


# ---------------------------------------------------------------------------
# 3. Custom verb — "user creates their own verb and compiles"
# ---------------------------------------------------------------------------

class TestCustomVerb:

    def test_user_defined_verb_compiles(self, tmp_path):
        """Simulate a user adding a 'blink_led' verb to their project."""
        verb_dir = tmp_path / "verbs"
        verb_dir.mkdir()

        # User writes a verb definition
        (verb_dir / "blink_led.yaml").write_text(yaml.dump({
            "name": "blink_led",
            "required_capabilities": [],
            "template": "blink_led.xml.j2",
            "primitives": ["gpio_toggle"],
            "parameters": {
                "count": {"type": "int", "required": True, "description": "Number of blinks"},
                "interval": {"type": "float", "required": False, "default": 0.5,
                             "description": "Seconds between blinks"},
            },
        }))

        # User writes a Jinja2 template
        (verb_dir / "blink_led.xml.j2").write_text(
            '<Action ID="BlinkLed" count="{{ count }}" interval="{{ interval | default(\'0.5\') }}" />'
        )

        # User writes a task
        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "name": "BlinkTask",
            "steps": [{"verb": "blink_led", "params": {"count": 3, "interval": 0.2}}],
        }))

        # Compile with custom verbs dir
        xml = _compile_task(task_file, verbs_dir=verb_dir)
        root = _parse_xml(xml)

        actions = root.find("BehaviorTree").find("Sequence").findall("Action")
        assert len(actions) == 1
        assert actions[0].attrib["ID"] == "BlinkLed"
        assert actions[0].attrib["count"] == "3"
        assert actions[0].attrib["interval"] == "0.2"

    def test_mixed_builtin_and_custom_verbs(self, tmp_path):
        """User mixes built-in verbs with their custom verb."""
        verb_dir = tmp_path / "verbs"
        verb_dir.mkdir()

        # Copy built-in verbs
        for f in VERB_LIBRARY_DIR.iterdir():
            (verb_dir / f.name).write_text(f.read_text())

        # Add a custom verb
        (verb_dir / "honk.yaml").write_text(yaml.dump({
            "name": "honk",
            "required_capabilities": [],
            "template": "honk.xml.j2",
            "primitives": [],
            "parameters": {},
        }))
        (verb_dir / "honk.xml.j2").write_text('<Action ID="Honk" />')

        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "name": "HonkPatrol",
            "steps": [
                {"verb": "go_to", "params": {"x": 1.0, "y": 2.0}},
                {"verb": "honk", "params": {}},
                {"verb": "wait", "params": {"duration": 1.0}},
            ],
        }))

        xml = _compile_task(task_file, verbs_dir=verb_dir)
        root = _parse_xml(xml)
        seq = root.find("BehaviorTree").find("Sequence")
        ids = [a.attrib["ID"] for a in seq.iter("Action")]
        assert ids == ["GoTo", "Honk", "Wait"]


# ---------------------------------------------------------------------------
# 4. Error paths — things users will get wrong
# ---------------------------------------------------------------------------

class TestErrorPaths:

    def test_task_references_nonexistent_verb(self, tmp_path):
        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "name": "Bad",
            "steps": [{"verb": "dance", "params": {}}],
        }))
        with pytest.raises(ValueError, match="Unknown verb"):
            _compile_task(task_file)

    def test_capability_mismatch_raises(self, tmp_path):
        """Robot lacks 'flying' but task requires it."""
        verb_dir = tmp_path / "verbs"
        verb_dir.mkdir()
        (verb_dir / "fly.yaml").write_text(yaml.dump({
            "name": "fly",
            "required_capabilities": ["flying"],
            "template": "fly.xml.j2",
            "primitives": [],
            "parameters": {},
        }))
        (verb_dir / "fly.xml.j2").write_text('<Action ID="Fly" />')

        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({
            "name": "FlyTask",
            "steps": [{"verb": "fly", "params": {}}],
        }))

        with pytest.raises(RuntimeError, match="missing.*flying"):
            _compile_task(task_file, verbs_dir=verb_dir)

    def test_empty_task_produces_valid_xml(self, tmp_path):
        """Edge case: task with no steps should still produce valid XML."""
        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({"name": "Empty", "steps": []}))
        xml = _compile_task(task_file)
        root = _parse_xml(xml)
        assert root.find("BehaviorTree").attrib["ID"] == "Empty"

    def test_missing_rdf_file_raises(self, tmp_path):
        """User points to nonexistent RDF file."""
        task_file = tmp_path / "task.yaml"
        task_file.write_text(yaml.dump({"name": "T", "steps": []}))
        with pytest.raises(FileNotFoundError):
            robot = load_rdf(tmp_path / "ghost.rdf.yaml")
