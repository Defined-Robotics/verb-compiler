"""
URDF xacro emitter — render a URDF xacro from an RDF Robot model.

PoC for the RDF-as-robot-manifest pattern (DR-014).
Requires the Robot model to have a ``physical`` section.

Also provides :func:`validate_urdf_structure` for structural correctness
checks on any rendered URDF string (backlog 999.8).

Usage:
    from defined_compiler.urdf_emitter import render_urdf, validate_urdf_structure

    xacro = render_urdf(robot)          # renders and validates
    validate_urdf_structure(xacro)      # raises URDFStructureError if broken
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from defined_rdf.models import Robot

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "robot.urdf.xacro.j2"

# ---------------------------------------------------------------------------
# Structural validation (backlog 999.8)
# ---------------------------------------------------------------------------


class URDFStructureError(ValueError):
    """Raised when a URDF string fails structural validation.

    Attributes:
        message: Human-readable description of what failed and why.
    """


def validate_urdf_structure(xml_str: str) -> None:
    """Validate that a URDF XML string is structurally sound.

    Performs five checks (in order):

    1. **Well-formed XML** — the string parses without error.
    2. **base_footprint declared** — a ``<link name="base_footprint"/>``
       element exists (required by ROS2/Nav2 TF chain).
    3. **No dangling joint refs** — every ``<parent link="…"/>`` and
       ``<child link="…"/>`` names a declared link.
    4. **Exactly one root** — exactly one link is never referenced as a
       joint child (disconnected links = broken kinematic tree).
    5. **At least 2 continuous joints** — the robot has a differential
       drive (or equivalent) and is physically movable.

    Args:
        xml_str: A rendered URDF XML string (not a file path).

    Raises:
        URDFStructureError: On the first structural violation found,
            with a message naming the offending element.
    """
    # 1. Well-formed XML
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as exc:
        raise URDFStructureError(f"URDF is not valid XML: {exc}") from exc

    declared_links = {el.get("name") for el in root.findall("link")}
    joints = root.findall("joint")

    # 2. base_footprint must be declared
    if "base_footprint" not in declared_links:
        raise URDFStructureError(
            "URDF has no <link name='base_footprint'/>. "
            "ROS2 Nav2 requires base_footprint as the kinematic tree root."
        )

    # 3. No dangling joint references
    for joint in joints:
        for role in ("parent", "child"):
            ref_el = joint.find(role)
            if ref_el is None:
                continue
            ref = ref_el.get("link", "")
            if ref not in declared_links:
                raise URDFStructureError(
                    f"Joint '{joint.get('name')}' {role} references undeclared "
                    f"link '{ref}'. Declare it with <link name='{ref}'/>."
                )

    # 4. Exactly one root (link never appearing as a joint child)
    child_links = {j.find("child").get("link") for j in joints if j.find("child") is not None}
    roots = declared_links - child_links
    if len(roots) != 1:
        raise URDFStructureError(
            f"Expected exactly 1 root link (link with no parent joint), "
            f"found {len(roots)}: {sorted(roots)}. "
            "Check for disconnected or orphaned links."
        )

    # 5. At least 2 continuous joints (robot must be movable)
    continuous = [j for j in joints if j.get("type") == "continuous"]
    if len(continuous) < 2:
        raise URDFStructureError(
            f"Found {len(continuous)} continuous joint(s); need at least 2 for "
            "differential drive. Robot is not movable."
        )


def _find_wheel_joints(robot: Robot) -> list[str]:
    """Return names of continuous wheel joints from the physical description.

    Looks for continuous joints whose child link name contains 'wheel'.
    Falls back to ``['wheel_left_joint', 'wheel_right_joint']`` if none found.

    Args:
        robot: Robot model with physical description.

    Returns:
        List of wheel joint names (left first, then right by y-offset).
    """
    if robot.physical is None:
        return ["wheel_left_joint", "wheel_right_joint"]

    wheel_joints = [
        j for j in robot.physical.joints
        if j.type == "continuous" and "wheel" in j.child.lower()
    ]
    if len(wheel_joints) < 2:
        return ["wheel_left_joint", "wheel_right_joint"]

    # Sort by y-offset descending so left (positive y) comes first.
    wheel_joints.sort(key=lambda j: j.origin.xyz[1], reverse=True)
    return [j.name for j in wheel_joints[:2]]


def _find_link_for_capability(robot: Robot, keywords: list[str]) -> str:
    """Find a link name matching any of the given keywords.

    Args:
        robot: Robot model with physical description.
        keywords: Substrings to search for in link names (case-insensitive).

    Returns:
        The matching link name, or the first keyword as fallback.
    """
    if robot.physical is None:
        return keywords[0]

    for link in robot.physical.links:
        name_lower = link.name.lower()
        if any(kw in name_lower for kw in keywords):
            return link.name

    return keywords[0]


def render_urdf(robot: Robot) -> str:
    """Render a URDF xacro string from a Robot model.

    Derives Gazebo plugin references (wheel joints, lidar link, camera
    link) from the physical description rather than hardcoding names.

    Args:
        robot: A validated Robot model with a ``physical`` section.

    Returns:
        The rendered URDF xacro XML as a string.

    Raises:
        ValueError: If the Robot has no ``physical`` section.
        URDFStructureError: If the rendered URDF fails structural validation
            (missing base_footprint, dangling joint refs, disconnected tree,
            or fewer than 2 continuous joints).
    """
    if robot.physical is None:
        raise ValueError(
            f"Robot '{robot.name}' has no `physical` section in its RDF. "
            "Add links and joints to generate a URDF."
        )

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template(_TEMPLATE_NAME)

    xacro = template.render(
        robot=robot,
        physical=robot.physical,
        capabilities=robot.capabilities,
        wheel_joints=_find_wheel_joints(robot),
        lidar_link=_find_link_for_capability(robot, ["lidar", "scan", "laser"]),
        camera_link=_find_link_for_capability(robot, ["camera", "cam"]),
    )
    validate_urdf_structure(xacro)
    return xacro
