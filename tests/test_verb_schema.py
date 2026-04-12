"""Tests for 5-layer verb manifest schema.

Covers:
- Backward compatibility with existing 2-layer verb YAMLs
- Full 5-layer manifest parsing
- Layer 3 SourceDep validation (repo vs path, packages field)
- Optional layers 3-5
"""

from pathlib import Path

import pytest
import yaml

from defined_compiler.verb_schema import (
    Dependencies,
    InterfaceContract,
    RuntimeConfig,
    SourceDep,
    VerbManifest,
)

VERB_LIBRARY = Path(__file__).parent.parent / "verb_library"


# ---------------------------------------------------------------------------
# Backward compatibility — existing verb YAMLs must parse unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb_name", ["go_to", "explore", "wait", "report", "capture_image"])
def test_parse_existing_verb_yaml(verb_name: str) -> None:
    """All 5 verb YAMLs validate against the new schema."""
    path = VERB_LIBRARY / f"{verb_name}.yaml"
    raw = yaml.safe_load(path.read_text())
    manifest = VerbManifest.model_validate(raw)

    assert manifest.name == verb_name
    assert manifest.template is not None
    assert isinstance(manifest.parameters, dict)


def test_existing_go_to_preserves_fields() -> None:
    """go_to verb keeps all existing layer 0-2 fields intact."""
    raw = yaml.safe_load((VERB_LIBRARY / "go_to.yaml").read_text())
    manifest = VerbManifest.model_validate(raw)

    assert manifest.name == "go_to"
    assert manifest.description == "Navigate the robot to a specified position"
    assert "differential_drive" in manifest.required_capabilities
    assert manifest.template == "go_to.xml.j2"
    assert "x" in manifest.parameters
    assert manifest.parameters["x"]["type"] == "float"
    assert manifest.parameters["x"]["required"] is True
    assert "error_code" in manifest.output_parameters


# ---------------------------------------------------------------------------
# Layers 3-5 are optional
# ---------------------------------------------------------------------------


def test_minimal_verb_validates() -> None:
    """A verb with only name + template validates (layers 3-5 absent)."""
    raw = {"name": "noop", "template": "noop.xml.j2"}
    manifest = VerbManifest.model_validate(raw)

    assert manifest.name == "noop"
    assert manifest.dependencies is None
    assert manifest.runtime is None
    assert manifest.interface is None


def test_layers_3_5_default_to_none() -> None:
    """Layers 3-5 default to None when not provided."""
    raw = {
        "name": "wait",
        "template": "wait.xml.j2",
        "required_capabilities": [],
        "parameters": {"duration": {"type": "float", "required": True}},
    }
    manifest = VerbManifest.model_validate(raw)

    assert manifest.dependencies is None
    assert manifest.runtime is None
    assert manifest.interface is None


# ---------------------------------------------------------------------------
# Full 5-layer manifest
# ---------------------------------------------------------------------------


def test_parse_full_manifest() -> None:
    """A complete 5-layer manifest parses all fields."""
    raw = {
        "name": "go_to",
        "description": "Navigate to a waypoint",
        "version": "0.1.0",
        "required_capabilities": ["differential_drive"],
        "template": "go_to.xml.j2",
        "primitives": ["navigate_to_pose"],
        "parameters": {
            "x": {"type": "float", "required": True},
        },
        "output_parameters": {
            "error_code": {"type": "int", "description": "Nav2 error code"},
        },
        "dependencies": {
            "apt": ["ros-jazzy-nav2-bringup"],
            "source": [
                {
                    "repo": "https://github.com/Defined-Robotics/defined-runtime",
                    "ref": "v0.1.0",
                    "packages": ["defined_runtime"],
                }
            ],
            "pip": ["some-package"],
        },
        "runtime": {
            "nodes": [
                {
                    "package": "nav2_bringup",
                    "executable": "navigation_launch.py",
                    "parameters": {"use_sim_time": True},
                }
            ],
        },
        "interface": {
            "actions": [{"name": "/navigate_to_pose"}],
            "topics": {
                "subscribes": [],
                "publishes": [],
            },
            "outputs": [],
        },
    }
    manifest = VerbManifest.model_validate(raw)

    assert manifest.name == "go_to"
    assert manifest.version == "0.1.0"
    assert manifest.dependencies is not None
    assert manifest.dependencies.apt == ["ros-jazzy-nav2-bringup"]
    assert len(manifest.dependencies.source) == 1
    assert manifest.dependencies.source[0].repo == "https://github.com/Defined-Robotics/defined-runtime"
    assert manifest.dependencies.source[0].packages == ["defined_runtime"]
    assert manifest.dependencies.pip == ["some-package"]
    assert manifest.runtime is not None
    assert len(manifest.runtime.nodes) == 1
    assert manifest.interface is not None
    assert len(manifest.interface.actions) == 1


# ---------------------------------------------------------------------------
# Layer 3: SourceDep validation
# ---------------------------------------------------------------------------


def test_source_dep_with_repo_validates() -> None:
    """A source dep with repo (no path) validates."""
    dep = SourceDep.model_validate({
        "repo": "https://github.com/org/repo",
        "ref": "main",
    })
    assert dep.repo == "https://github.com/org/repo"
    assert dep.ref == "main"
    assert dep.path is None


def test_source_dep_with_path_validates() -> None:
    """A source dep with path (no repo) validates."""
    dep = SourceDep.model_validate({
        "path": "./src/my_custom_nodes",
    })
    assert dep.path == "./src/my_custom_nodes"
    assert dep.repo is None


def test_source_dep_with_both_repo_and_path_errors() -> None:
    """Setting both repo and path is invalid."""
    with pytest.raises(ValueError, match="[Ee]xactly one"):
        SourceDep.model_validate({
            "repo": "https://github.com/org/repo",
            "path": "./src/local",
        })


def test_source_dep_with_neither_repo_nor_path_errors() -> None:
    """Setting neither repo nor path is invalid."""
    with pytest.raises(ValueError, match="[Ee]xactly one"):
        SourceDep.model_validate({})


def test_source_dep_packages_field() -> None:
    """packages field specifies which colcon packages to build."""
    dep = SourceDep.model_validate({
        "repo": "https://github.com/org/repo",
        "packages": ["pkg_a", "pkg_b"],
    })
    assert dep.packages == ["pkg_a", "pkg_b"]


def test_source_dep_packages_defaults_empty() -> None:
    """packages defaults to empty list (build all)."""
    dep = SourceDep.model_validate({
        "repo": "https://github.com/org/repo",
    })
    assert dep.packages == []


def test_source_dep_patches_field() -> None:
    """patches field lists patch files to apply."""
    dep = SourceDep.model_validate({
        "repo": "https://github.com/org/repo",
        "patches": ["fix_autostart.patch"],
    })
    assert dep.patches == ["fix_autostart.patch"]


def test_source_dep_ref_defaults_to_main() -> None:
    """ref defaults to 'main' when not specified."""
    dep = SourceDep.model_validate({
        "repo": "https://github.com/org/repo",
    })
    assert dep.ref == "main"


# ---------------------------------------------------------------------------
# Layer 3: Dependencies model
# ---------------------------------------------------------------------------


def test_dependencies_all_empty() -> None:
    """Empty dependencies model is valid."""
    deps = Dependencies.model_validate({})
    assert deps.apt == []
    assert deps.source == []
    assert deps.pip == []


def test_dependencies_apt_only() -> None:
    """Dependencies with only apt packages."""
    deps = Dependencies.model_validate({"apt": ["ros-jazzy-nav2-bringup"]})
    assert deps.apt == ["ros-jazzy-nav2-bringup"]
    assert deps.source == []
    assert deps.pip == []


# ---------------------------------------------------------------------------
# extends field (parsed but not resolved here — resolution is in verb_expander)
# ---------------------------------------------------------------------------


def test_extends_field_parsed() -> None:
    """The extends field is captured in the manifest."""
    raw = {
        "name": "my_go_to",
        "extends": "defined/go_to",
    }
    manifest = VerbManifest.model_validate(raw)
    assert manifest.extends == "defined/go_to"


def test_extends_field_optional() -> None:
    """extends defaults to None when not provided."""
    raw = {"name": "wait", "template": "wait.xml.j2"}
    manifest = VerbManifest.model_validate(raw)
    assert manifest.extends is None


# ---------------------------------------------------------------------------
# Upgraded verbs have layers 3-5 populated
# ---------------------------------------------------------------------------


def test_upgraded_go_to_has_dependencies() -> None:
    """go_to verb now declares Nav2 apt dep and defined-runtime source dep."""
    raw = yaml.safe_load((VERB_LIBRARY / "go_to.yaml").read_text())
    manifest = VerbManifest.model_validate(raw)

    assert manifest.dependencies is not None
    assert "ros-jazzy-nav2-bringup" in manifest.dependencies.apt
    assert len(manifest.dependencies.source) > 0
    assert manifest.interface is not None
    assert len(manifest.interface.actions) > 0


def test_capture_image_requires_camera() -> None:
    """capture_image verb requires rgb_camera capability."""
    raw = yaml.safe_load((VERB_LIBRARY / "capture_image.yaml").read_text())
    manifest = VerbManifest.model_validate(raw)

    assert "rgb_camera" in manifest.required_capabilities
    assert manifest.dependencies is not None
    assert "ros-jazzy-cv-bridge" in manifest.dependencies.apt
    assert "topic" in manifest.parameters
