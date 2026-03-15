"""URDF xacro emitter — render a URDF xacro from an RDF Robot model.

PoC for the RDF-as-robot-manifest pattern (DR-014).
Requires the Robot model to have a ``physical`` section.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from defined_rdf.models import Robot

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "robot.urdf.xacro.j2"


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

    return template.render(
        robot=robot,
        physical=robot.physical,
        capabilities=robot.capabilities,
        wheel_joints=_find_wheel_joints(robot),
        lidar_link=_find_link_for_capability(robot, ["lidar", "scan", "laser"]),
        camera_link=_find_link_for_capability(robot, ["camera", "cam"]),
    )
