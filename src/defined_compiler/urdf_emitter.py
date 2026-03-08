"""URDF xacro emitter — render a URDF xacro from an RDF Robot model.

PoC for the RDF-as-robot-manifest pattern (DR-014).
Requires the Robot model to have a `physical` section.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, PackageLoader

from defined_rdf.models import Robot

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_TEMPLATE_NAME = "robot.urdf.xacro.j2"


def render_urdf(robot: Robot) -> str:
    """Render a URDF xacro string from a Robot model.

    Raises ValueError if the Robot has no physical description.
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
    )
