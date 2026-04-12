"""5-layer verb manifest schema.

Pydantic v2 models for the full verb package format:

- Layer 0: Identity (name, version, description)
- Layer 1: Capability gate (required_capabilities)
- Layer 2: BT template + parameters
- Layer 3: Software dependencies (apt, source, pip)
- Layer 4: Runtime configuration (ROS2 nodes, parameters)
- Layer 5: Interface contract (actions, topics, outputs)

Layers 3-5 are optional for backward compatibility with existing
verb YAMLs that only define layers 0-2.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator


# ---------------------------------------------------------------------------
# Layer 3: Software dependencies
# ---------------------------------------------------------------------------


class SourceDep(BaseModel):
    """A source dependency — either a remote git repo or a local path.

    Exactly one of ``repo`` or ``path`` must be set.
    """

    repo: str | None = None
    path: str | None = None
    ref: str = "main"
    packages: list[str] = []
    patches: list[str] = []

    @model_validator(mode="after")
    def _exactly_one_source(self) -> SourceDep:
        has_repo = self.repo is not None
        has_path = self.path is not None
        if has_repo == has_path:
            raise ValueError(
                "Exactly one of 'repo' or 'path' must be set, "
                f"got repo={self.repo!r}, path={self.path!r}"
            )
        return self


class Dependencies(BaseModel):
    """Layer 3 — software dependencies required by a verb."""

    apt: list[str] = []
    source: list[SourceDep] = []
    pip: list[str] = []


# ---------------------------------------------------------------------------
# Layer 4: Runtime configuration
# ---------------------------------------------------------------------------


class NodeConfig(BaseModel):
    """A ROS2 node to launch for this verb."""

    package: str
    executable: str
    parameters: dict[str, Any] = {}


class RuntimeConfig(BaseModel):
    """Layer 4 — runtime configuration (ROS2 nodes and parameters)."""

    nodes: list[NodeConfig] = []


# ---------------------------------------------------------------------------
# Layer 5: Interface contract
# ---------------------------------------------------------------------------


class ActionInterface(BaseModel):
    """A ROS2 action this verb uses."""

    name: str


class TopicInterface(BaseModel):
    """Topics this verb subscribes to or publishes."""

    subscribes: list[str] = []
    publishes: list[str] = []


class InterfaceContract(BaseModel):
    """Layer 5 — interface contract declaring actions, topics, outputs."""

    actions: list[ActionInterface] = []
    topics: TopicInterface = TopicInterface()
    outputs: list[str] = []


# ---------------------------------------------------------------------------
# Full verb manifest
# ---------------------------------------------------------------------------


class VerbManifest(BaseModel):
    """Complete 5-layer verb manifest.

    Layers 0-2 match the existing verb YAML format. Layers 3-5 are
    new optional fields that carry dependency and runtime information.
    """

    # Layer 0: Identity
    name: str
    description: str = ""
    version: str = "0.1.0"

    # Layer 1: Capability gate
    required_capabilities: list[str] = []

    # Layer 2: BT template + parameters
    template: str | None = None
    primitives: list[str] = []
    parameters: dict[str, dict[str, Any]] = {}
    output_parameters: dict[str, dict[str, Any]] = {}

    # extends (resolution handled by verb_expander, not here)
    extends: str | None = None

    # Layer 3: Software dependencies (optional)
    dependencies: Dependencies | None = None

    # Layer 4: Runtime configuration (optional)
    runtime: RuntimeConfig | None = None

    # Layer 5: Interface contract (optional)
    interface: InterfaceContract | None = None
