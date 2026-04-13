"""End-to-end chain tests: RDF → Registry, RDF → URDF, Task → BT XML."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import re

import pytest

from defined_rdf.parser import load as load_rdf
from defined_rdf.registry import CapabilityRegistry

from defined_compiler import bt_emitter, capability_gate, parser, verb_expander
from defined_compiler.urdf_emitter import render_urdf


def _strip_xacro(urdf: str) -> str:
    """Strip xacro namespace declarations and xacro: elements for XML parsing."""
    # Remove xmlns:xacro attribute
    urdf = re.sub(r'\s+xmlns:xacro="[^"]*"', '', urdf)
    # Remove xacro:property elements entirely
    urdf = re.sub(r'<xacro:property[^/]*/>', '', urdf)
    return urdf

VERB_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "src" / "defined_compiler" / "verb_library"
RDF_TB3 = Path(__file__).resolve().parent.parent.parent / "rdf" / "examples" / "turtlebot3_burger.rdf.yaml"
RDF_MVP = Path(__file__).resolve().parent.parent.parent / "rdf" / "examples" / "defined_mvp.rdf.yaml"
PATROL_TASK = Path(__file__).resolve().parent.parent / "examples" / "patrol_task.yaml"
SURVEY_TASK = Path(__file__).resolve().parent.parent / "examples" / "survey_task.yaml"


@pytest.fixture
def tb3_robot():
    return load_rdf(RDF_TB3)


@pytest.fixture
def tb3_registry(tb3_robot):
    return CapabilityRegistry(tb3_robot)


# ---------------------------------------------------------------------------
# Test 1: RDF → Capability Registry
# ---------------------------------------------------------------------------

class TestRDFToRegistry:

    def test_has_differential_drive(self, tb3_registry):
        assert tb3_registry.has("differential_drive")

    def test_has_lidar_2d(self, tb3_registry):
        assert tb3_registry.has("lidar_2d")

    def test_physical_links_present(self, tb3_robot):
        assert tb3_robot.physical is not None
        link_names = [l.name for l in tb3_robot.physical.links]
        for expected in ["base_link", "wheel_left_link", "wheel_right_link", "base_scan"]:
            assert expected in link_names, f"Missing link: {expected}"

    def test_wheel_separation_value(self, tb3_robot):
        dd_cap = next(c for c in tb3_robot.capabilities if c.type == "differential_drive")
        assert dd_cap.parameters["wheel_separation"] == 0.160

    def test_wheel_radius_value(self, tb3_robot):
        dd_cap = next(c for c in tb3_robot.capabilities if c.type == "differential_drive")
        assert dd_cap.parameters["wheel_radius"] == 0.033


# ---------------------------------------------------------------------------
# Test 2: RDF → Generated URDF
# ---------------------------------------------------------------------------

class TestRDFToURDF:

    def test_urdf_is_valid_xml(self, tb3_robot):
        urdf = render_urdf(tb3_robot)
        root = ET.fromstring(_strip_xacro(urdf))
        assert root.tag == "robot"

    def test_urdf_has_expected_links(self, tb3_robot):
        urdf = render_urdf(tb3_robot)
        root = ET.fromstring(_strip_xacro(urdf))
        link_names = {l.get("name") for l in root.findall("link")}
        for expected in ["base_link", "wheel_left_link", "wheel_right_link", "base_scan"]:
            assert expected in link_names, f"Missing URDF link: {expected}"

    def test_urdf_has_expected_joints(self, tb3_robot):
        urdf = render_urdf(tb3_robot)
        root = ET.fromstring(_strip_xacro(urdf))
        joints = {j.get("name"): j.get("type") for j in root.findall("joint")}
        assert joints.get("wheel_left_joint") == "continuous"
        assert joints.get("wheel_right_joint") == "continuous"
        assert joints.get("scan_joint") == "fixed"

    def test_gz_sim_diff_drive_plugin(self, tb3_robot):
        urdf = render_urdf(tb3_robot)
        root = ET.fromstring(_strip_xacro(urdf))
        # Find diff drive plugin
        for gazebo in root.findall("gazebo"):
            for plugin in gazebo.findall("plugin"):
                if "diff-drive" in (plugin.get("filename") or ""):
                    ws = plugin.find("wheel_separation")
                    assert ws is not None
                    assert float(ws.text) == 0.160
                    wr = plugin.find("wheel_radius")
                    assert wr is not None
                    assert float(wr.text) == 0.033
                    return
        pytest.fail("gz-sim-diff-drive-system plugin not found in generated URDF")

    def test_gz_sim_gpu_lidar_sensor(self, tb3_robot):
        urdf = render_urdf(tb3_robot)
        root = ET.fromstring(_strip_xacro(urdf))
        for gazebo in root.findall("gazebo"):
            for sensor in gazebo.findall("sensor"):
                if sensor.get("type") == "gpu_lidar":
                    # Check gz_frame_id is present
                    gz_frame = sensor.find("gz_frame_id")
                    assert gz_frame is not None
                    assert gz_frame.text is not None
                    # Check range
                    range_max = sensor.find("ray/range/max")
                    assert range_max is not None
                    assert float(range_max.text) == 3.5
                    return
        pytest.fail("gpu_lidar sensor not found in generated URDF")

    def test_no_gazebo_classic_plugins(self, tb3_robot):
        urdf = render_urdf(tb3_robot)
        assert "libgazebo_ros" not in urdf
        assert 'type="ray"' not in urdf


# ---------------------------------------------------------------------------
# Test 3: Task → BT XML structure
# ---------------------------------------------------------------------------

class TestTaskToBTXML:

    def _compile_patrol(self, tb3_registry):
        task = parser.load_task(PATROL_TASK)
        expanded = []
        for step in task["steps"]:
            verb_data = verb_expander.expand_verb(
                step["verb"], step.get("params", {}), verbs_dir=VERB_LIBRARY_DIR
            )
            result = capability_gate.check(tb3_registry, verb_data["required_capabilities"])
            assert result.passed
            expanded.append(verb_data)
        return bt_emitter.render_bt_xml(expanded, task_name="PatrolTask", verbs_dir=VERB_LIBRARY_DIR)

    def test_bt_xml_well_formed(self, tb3_registry):
        xml = self._compile_patrol(tb3_registry)
        root = ET.fromstring(xml)
        assert root.get("BTCPP_format") == "4"

    def test_sequence_children_count(self, tb3_registry):
        xml = self._compile_patrol(tb3_registry)
        root = ET.fromstring(xml)
        bt = root.find("BehaviorTree")
        seq = bt.find("Sequence")
        # 3 GoTo (each wrapped in RetryUntilSuccessful) + 3 Report + 2 Wait = 8 children
        assert len(list(seq)) == 8

    def test_goto_has_correct_attributes(self, tb3_registry):
        xml = self._compile_patrol(tb3_registry)
        root = ET.fromstring(xml)
        seq = root.find("BehaviorTree/Sequence")
        # First child is RetryUntilSuccessful wrapping GoTo
        retry = seq[0]
        assert retry.tag == "RetryUntilSuccessful"
        assert retry.get("num_attempts") == "3"
        goto = retry.find("Action")
        assert goto.get("ID") == "GoTo"
        assert goto.get("x") == "1.0"
        assert goto.get("y") == "0.0"
        assert goto.get("server_name") == "/navigate_to_pose"

    def test_report_messages(self, tb3_registry):
        xml = self._compile_patrol(tb3_registry)
        root = ET.fromstring(xml)
        seq = root.find("BehaviorTree/Sequence")
        reports = [
            child for child in seq
            if child.tag == "Action" and child.get("ID") == "Report"
        ]
        messages = [r.get("message") for r in reports]
        assert "arrived_at_wp1" in messages
        assert "arrived_at_wp2" in messages
        assert "patrol_complete" in messages

    def test_wait_duration(self, tb3_registry):
        xml = self._compile_patrol(tb3_registry)
        root = ET.fromstring(xml)
        seq = root.find("BehaviorTree/Sequence")
        waits = [
            child for child in seq
            if child.tag == "Action" and child.get("ID") == "Wait"
        ]
        assert len(waits) == 2
        for w in waits:
            assert w.get("duration") == "2.0"


# ---------------------------------------------------------------------------
# Test 4: Capability gate rejects bad tasks
# ---------------------------------------------------------------------------

class TestCapabilityGateRejects:

    def test_reject_missing_capability(self, tb3_registry):
        result = capability_gate.check(tb3_registry, ["robotic_arm"])
        assert not result.passed
        assert "robotic_arm" in result.missing

    def test_reject_with_clear_status(self, tb3_registry):
        result = capability_gate.check(tb3_registry, ["robotic_arm"])
        assert result.status == "REJECTED"


# ---------------------------------------------------------------------------
# Test 5: Generated URDF matches RDF parameters (cross-check)
# ---------------------------------------------------------------------------

class TestURDFRDFParameterMatch:

    def test_wheel_separation_matches(self, tb3_robot):
        dd_cap = next(c for c in tb3_robot.capabilities if c.type == "differential_drive")
        urdf = render_urdf(tb3_robot)
        root = ET.fromstring(_strip_xacro(urdf))
        for gazebo in root.findall("gazebo"):
            for plugin in gazebo.findall("plugin"):
                ws = plugin.find("wheel_separation")
                if ws is not None:
                    assert float(ws.text) == dd_cap.parameters["wheel_separation"]
                    return
        pytest.fail("wheel_separation not found in URDF")

    def test_lidar_range_matches(self, tb3_robot):
        lidar_cap = next(c for c in tb3_robot.capabilities if c.type == "lidar_2d")
        urdf = render_urdf(tb3_robot)
        root = ET.fromstring(_strip_xacro(urdf))
        for gazebo in root.findall("gazebo"):
            for sensor in gazebo.findall("sensor"):
                range_max = sensor.find("ray/range/max")
                if range_max is not None:
                    assert float(range_max.text) == lidar_cap.parameters["range_max"]
                    return
        pytest.fail("lidar range not found in URDF")


# ---------------------------------------------------------------------------
# Test 6: CaptureImage — survey task compiles for robot with camera
# ---------------------------------------------------------------------------


@pytest.fixture
def mvp_robot():
    return load_rdf(RDF_MVP)


@pytest.fixture
def mvp_registry(mvp_robot):
    return CapabilityRegistry(mvp_robot)


class TestSurveyTaskWithCamera:

    def _compile_survey(self, registry):
        task = parser.load_task(SURVEY_TASK)
        expanded = []
        for step in task["steps"]:
            verb_data = verb_expander.expand_verb(
                step["verb"], step.get("params", {}), verbs_dir=VERB_LIBRARY_DIR
            )
            result = capability_gate.check(registry, verb_data["required_capabilities"])
            assert result.passed, f"Capability gate failed: missing {result.missing}"
            expanded.append(verb_data)
        return bt_emitter.render_bt_xml(expanded, task_name="SurveyTask", verbs_dir=VERB_LIBRARY_DIR)

    def test_survey_compiles_for_mvp_robot(self, mvp_registry):
        """MVP robot (has rgb_camera) compiles the survey task."""
        xml = self._compile_survey(mvp_registry)
        root = ET.fromstring(xml)
        assert root.get("BTCPP_format") == "4"

    def test_survey_has_capture_image_action(self, mvp_registry):
        """Compiled BT XML contains a CaptureImage action node."""
        xml = self._compile_survey(mvp_registry)
        root = ET.fromstring(xml)
        seq = root.find("BehaviorTree/Sequence")
        actions = [child for child in seq.iter() if child.get("ID") == "CaptureImage"]
        assert len(actions) == 1

    def test_capture_image_has_correct_attributes(self, mvp_registry):
        """CaptureImage action has topic, save_path, timeout from task params."""
        xml = self._compile_survey(mvp_registry)
        root = ET.fromstring(xml)
        capture = next(el for el in root.iter() if el.get("ID") == "CaptureImage")
        assert capture.get("topic") == "/camera/image_raw"
        assert capture.get("save_path") == "/tmp/survey"
        assert capture.get("timeout") == "5.0"

    def test_survey_has_tree_nodes_model(self, mvp_registry):
        """TreeNodesModel includes CaptureImage port declarations."""
        xml = self._compile_survey(mvp_registry)
        root = ET.fromstring(xml)
        model = root.find("TreeNodesModel")
        assert model is not None
        action_ids = {a.get("ID") for a in model.findall("Action")}
        assert "CaptureImage" in action_ids

    def test_capture_image_rejected_without_camera(self, tb3_registry):
        """TB3 Burger (no rgb_camera) rejects capture_image verb."""
        verb_data = verb_expander.expand_verb(
            "capture_image", {"topic": "/camera/image_raw"}, verbs_dir=VERB_LIBRARY_DIR
        )
        result = capability_gate.check(tb3_registry, verb_data["required_capabilities"])
        assert not result.passed
        assert "rgb_camera" in result.missing
