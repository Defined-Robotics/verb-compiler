"""Tests for the verb compiler: parser, expander, capability gate, emitter, and CLI."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from defined_rdf.parser import load as load_rdf
from defined_rdf.registry import CapabilityRegistry

from defined_compiler import bt_emitter, capability_gate, parser, verb_expander

# Directories shared across tests
VERB_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "src" / "defined_compiler" / "verb_library"
RDF_MVP = Path(__file__).resolve().parent.parent.parent / "rdf" / "examples" / "defined_mvp.rdf.yaml"
PATROL_TASK = Path(__file__).resolve().parent.parent / "examples" / "patrol_task.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mvp_registry() -> CapabilityRegistry:
    robot = load_rdf(RDF_MVP)
    return CapabilityRegistry(robot)


# ---------------------------------------------------------------------------
# Task parser
# ---------------------------------------------------------------------------

class TestParser:

    def test_load_patrol_task(self):
        task = parser.load_task(PATROL_TASK)
        assert task["name"] == "PatrolTask"
        assert len(task["steps"]) == 8

    def test_load_missing_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parser.load_task(tmp_path / "nonexistent.yaml")

    def test_load_minimal_task(self, tmp_path):
        f = tmp_path / "t.yaml"
        f.write_text("name: T\nsteps:\n  - verb: wait\n    params:\n      duration: 1.0\n")
        task = parser.load_task(f)
        assert task["steps"][0]["verb"] == "wait"


# ---------------------------------------------------------------------------
# Verb expander
# ---------------------------------------------------------------------------

class TestVerbExpander:

    def test_expand_go_to(self):
        data = verb_expander.expand_verb("go_to", {"x": 1.0, "y": 2.0}, verbs_dir=VERB_LIBRARY_DIR)
        assert data["verb"] == "go_to"
        assert "differential_drive" in data["required_capabilities"]
        assert data["params"]["x"] == 1.0

    def test_expand_wait(self):
        data = verb_expander.expand_verb("wait", {"duration": 3.0}, verbs_dir=VERB_LIBRARY_DIR)
        assert data["verb"] == "wait"
        assert data["required_capabilities"] == []

    def test_expand_report(self):
        data = verb_expander.expand_verb("report", {"message": "ok"}, verbs_dir=VERB_LIBRARY_DIR)
        assert data["verb"] == "report"

    def test_unknown_verb_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown verb"):
            verb_expander.expand_verb("fly", {}, verbs_dir=tmp_path)

    def test_custom_verbs_dir(self, tmp_path):
        # Create a minimal custom verb definition
        verb_def = {"name": "spin", "required_capabilities": [], "template": "spin.xml.j2", "primitives": []}
        (tmp_path / "spin.yaml").write_text(yaml.dump(verb_def))
        data = verb_expander.expand_verb("spin", {}, verbs_dir=tmp_path)
        assert data["verb"] == "spin"


# ---------------------------------------------------------------------------
# Capability gate
# ---------------------------------------------------------------------------

class TestCapabilityGate:

    def test_go_to_passes_on_mvp(self):
        registry = _mvp_registry()
        result = capability_gate.check(registry, ["differential_drive"])
        assert result.passed
        assert result.missing == []
        assert result.status == "OK"

    def test_missing_capability_rejected(self):
        registry = _mvp_registry()
        result = capability_gate.check(registry, ["flying"])
        assert not result.passed
        assert "flying" in result.missing
        assert result.status == "REJECTED"

    def test_empty_requirements_pass(self):
        registry = _mvp_registry()
        result = capability_gate.check(registry, [])
        assert result.passed


# ---------------------------------------------------------------------------
# BT emitter
# ---------------------------------------------------------------------------

class TestBTEmitter:

    def _expand(self, verb: str, params: dict) -> dict:
        return verb_expander.expand_verb(verb, params, verbs_dir=VERB_LIBRARY_DIR)

    def test_go_to_renders_action(self):
        expanded = [self._expand("go_to", {"x": 1.0, "y": 0.0, "theta": 0.0})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        assert 'ID="GoTo"' in xml
        assert 'x="1.0"' in xml
        assert '<RetryUntilSuccessful num_attempts="3">' in xml
        assert 'frame_id="map"' in xml
        assert 'server_name="/navigate_to_pose"' in xml

    def test_full_patrol_xml(self):
        steps = [
            ("go_to", {"x": 1.0, "y": 0.0, "theta": 0.0}),
            ("report", {"message": "arrived"}),
            ("wait", {"duration": 2.0}),
        ]
        expanded = [self._expand(v, p) for v, p in steps]
        xml = bt_emitter.render_bt_xml(expanded, task_name="PatrolTask", verbs_dir=VERB_LIBRARY_DIR)
        assert '<?xml version="1.0"' in xml
        assert 'BTCPP_format="4"' in xml
        assert 'ID="PatrolTask"' in xml
        assert 'ID="GoTo"' in xml
        assert 'ID="Report"' in xml
        assert 'ID="Wait"' in xml

    def test_task_name_appears_in_xml(self):
        expanded = [self._expand("wait", {"duration": 1.0})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="MyTask", verbs_dir=VERB_LIBRARY_DIR)
        assert "MyTask" in xml

    def test_tree_nodes_model_present(self):
        expanded = [self._expand("go_to", {"x": 1.0, "y": 0.0})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        assert "<TreeNodesModel>" in xml
        assert 'input_port name="x"' in xml
        assert 'input_port name="y"' in xml
        assert 'input_port name="theta"' in xml
        assert 'input_port name="timeout"' in xml
        assert 'input_port name="frame_id"' in xml
        assert 'input_port name="server_name"' in xml
        assert 'input_port name="retries"' in xml
        assert 'output_port name="error_code"' in xml

    def test_tree_nodes_model_deduplicates(self):
        expanded = [
            self._expand("go_to", {"x": 1.0, "y": 0.0}),
            self._expand("go_to", {"x": 2.0, "y": 3.0}),
        ]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        assert xml.count('Action ID="GoTo"') == 3  # 2 actions + 1 in model

    def test_report_has_topic_and_level(self):
        expanded = [self._expand("report", {"message": "ok"})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        assert 'topic="/task_reports"' in xml
        assert 'level="info"' in xml

    def test_report_output_port(self):
        expanded = [self._expand("report", {"message": "ok"})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        assert 'output_port name="success"' in xml

    def test_go_to_timeout_default(self):
        expanded = [self._expand("go_to", {"x": 1.0, "y": 0.0})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        assert 'timeout="60.0"' in xml

    def test_go_to_timeout_custom(self):
        expanded = [self._expand("go_to", {"x": 1.0, "y": 0.0, "timeout": 30.0})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        assert 'timeout="30.0"' in xml

    def test_xml_indentation(self):
        expanded = [self._expand("wait", {"duration": 1.0})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        # Single-line action nodes inside <Sequence> should be indented 12 spaces
        assert '            <Action ID="Wait"' in xml

    def test_retry_node_indentation(self):
        expanded = [self._expand("go_to", {"x": 1.0, "y": 0.0})]
        xml = bt_emitter.render_bt_xml(expanded, task_name="T", verbs_dir=VERB_LIBRARY_DIR)
        # RetryUntilSuccessful wrapper should be indented 12 spaces
        assert '            <RetryUntilSuccessful' in xml


# ---------------------------------------------------------------------------
# End-to-end: full compile pipeline
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_compile_patrol_task(self):
        registry = _mvp_registry()
        task = parser.load_task(PATROL_TASK)

        expanded = []
        for step in task["steps"]:
            verb_data = verb_expander.expand_verb(step["verb"], step.get("params", {}), verbs_dir=VERB_LIBRARY_DIR)
            result = capability_gate.check(registry, verb_data["required_capabilities"])
            assert result.passed, f"capability gate failed for verb '{step['verb']}': {result.missing}"
            expanded.append(verb_data)

        xml = bt_emitter.render_bt_xml(expanded, task_name="PatrolTask", verbs_dir=VERB_LIBRARY_DIR)
        assert xml.strip().startswith("<?xml")
        assert "PatrolTask" in xml
