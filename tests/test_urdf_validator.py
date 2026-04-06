"""
Tests for URDF structural validation (backlog 999.8).

Validates that urdf_emitter.validate_urdf_structure() catches structural
errors before a broken URDF reaches ROS2/Gz Sim.

Checks covered:
  1. Well-formed XML
  2. base_footprint link declared
  3. No dangling joint parent/child references
  4. Exactly one tree root (no disconnected sub-trees, no cycles)
  5. At least 2 continuous joints (robot is movable)
"""

from __future__ import annotations

import pytest

from defined_compiler.urdf_emitter import URDFStructureError, validate_urdf_structure

# ---------------------------------------------------------------------------
# Minimal valid URDF helpers
# ---------------------------------------------------------------------------

_VALID_URDF = """\
<?xml version="1.0"?>
<robot name="test_robot">
  <link name="base_footprint"/>
  <link name="base_link"/>
  <link name="wheel_left_link"/>
  <link name="wheel_right_link"/>

  <joint name="base_joint" type="fixed">
    <parent link="base_footprint"/>
    <child link="base_link"/>
  </joint>
  <joint name="wheel_left_joint" type="continuous">
    <parent link="base_link"/>
    <child link="wheel_left_link"/>
    <axis xyz="0 1 0"/>
  </joint>
  <joint name="wheel_right_joint" type="continuous">
    <parent link="base_link"/>
    <child link="wheel_right_link"/>
    <axis xyz="0 1 0"/>
  </joint>
</robot>
"""


def _urdf_without(tag_snippet: str) -> str:
    """Return _VALID_URDF with a specific line removed."""
    return "\n".join(
        line for line in _VALID_URDF.splitlines()
        if tag_snippet not in line
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidUrdf:

    def test_valid_urdf_passes(self):
        """A structurally correct URDF raises no error."""
        validate_urdf_structure(_VALID_URDF)  # must not raise


# ---------------------------------------------------------------------------
# Check 1: Well-formed XML
# ---------------------------------------------------------------------------


class TestMalformedXml:

    def test_malformed_xml_raises(self):
        with pytest.raises(URDFStructureError, match="not valid XML"):
            validate_urdf_structure("<robot><link name='a'></robot>")

    def test_empty_string_raises(self):
        with pytest.raises(URDFStructureError, match="not valid XML"):
            validate_urdf_structure("")


# ---------------------------------------------------------------------------
# Check 2: base_footprint must be declared
# ---------------------------------------------------------------------------


class TestBaseFootprintRequired:

    def test_missing_base_footprint_raises(self):
        urdf = _urdf_without('name="base_footprint"')
        with pytest.raises(URDFStructureError, match="base_footprint"):
            validate_urdf_structure(urdf)


# ---------------------------------------------------------------------------
# Check 3: No dangling joint refs
# ---------------------------------------------------------------------------


class TestDanglingJointRefs:

    def test_joint_child_references_undeclared_link_raises(self):
        urdf = _VALID_URDF.replace(
            '<link name="wheel_left_link"/>',
            '',
        )
        with pytest.raises(URDFStructureError, match="wheel_left_link"):
            validate_urdf_structure(urdf)

    def test_joint_parent_references_undeclared_link_raises(self):
        urdf = _VALID_URDF.replace(
            '<link name="base_link"/>',
            '',
        )
        with pytest.raises(URDFStructureError, match="base_link"):
            validate_urdf_structure(urdf)


# ---------------------------------------------------------------------------
# Check 4: Exactly one root (link never appearing as a joint child)
# ---------------------------------------------------------------------------


class TestSingleRoot:

    def test_disconnected_link_raises(self):
        """A link with no joint connecting it to the tree is an orphan."""
        urdf = _VALID_URDF.replace(
            "</robot>",
            '  <link name="orphan_link"/>\n</robot>',
        )
        with pytest.raises(URDFStructureError, match="orphan|disconnected|root"):
            validate_urdf_structure(urdf)

    def test_two_roots_raises(self):
        """Two links that are never a joint child = two roots = broken tree."""
        urdf = _VALID_URDF.replace(
            "</robot>",
            '  <link name="second_root"/>\n</robot>',
        )
        with pytest.raises(URDFStructureError, match="root|disconnected"):
            validate_urdf_structure(urdf)


# ---------------------------------------------------------------------------
# Check 5: At least 2 continuous joints (robot is movable)
# ---------------------------------------------------------------------------


class TestDriveCapability:

    def test_zero_continuous_joints_raises(self):
        urdf = _VALID_URDF.replace('type="continuous"', 'type="fixed"')
        with pytest.raises(URDFStructureError, match="continuous|movable|drive"):
            validate_urdf_structure(urdf)

    def test_one_continuous_joint_raises(self):
        urdf = _VALID_URDF.replace(
            '<joint name="wheel_right_joint" type="continuous">',
            '<joint name="wheel_right_joint" type="fixed">',
        )
        with pytest.raises(URDFStructureError, match="continuous|movable|drive"):
            validate_urdf_structure(urdf)

    def test_two_continuous_joints_passes(self):
        """Exactly 2 continuous joints is the minimum valid drive config."""
        validate_urdf_structure(_VALID_URDF)  # must not raise
