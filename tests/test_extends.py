"""Tests for verb extends resolution with additive dep merge.

Covers:
- Stub verb with only `extends` → full base definition
- Shallow merge: local fields replace base entirely
- Additive dep merge: local deps added to base deps
- Dep deduplication (apt, pip)
- Unset fields inherited from base
- No extends → local definition as-is
- Project verb shadows built-in of same name
- extends: defined/nonexistent → clear error
- Resolution order: project verbs_dir first → built-in fallback
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from defined_compiler.bt_emitter import render_bt_xml
from defined_compiler.verb_expander import (
    expand_verb,
    load_verb_definition,
    resolve_verb_definition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BUILTIN_VERB_DIR = Path(__file__).resolve().parent.parent / "verb_library"


def _write_verb(tmp_path: Path, name: str, data: dict) -> Path:
    """Write a verb YAML to a temp directory."""
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.dump(data, default_flow_style=False))
    return path


# ---------------------------------------------------------------------------
# resolve_verb_definition (core extends logic)
# ---------------------------------------------------------------------------


class TestExtendsResolution:

    def test_stub_extends_produces_full_definition(self, tmp_path: Path) -> None:
        """A verb with only `extends: defined/go_to` inherits all base fields."""
        _write_verb(tmp_path, "go_to", {"extends": "defined/go_to"})

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)

        assert resolved["name"] == "go_to"
        assert "differential_drive" in resolved.get("required_capabilities", [])
        assert resolved.get("template") == "go_to.xml.j2"
        assert "x" in resolved.get("parameters", {})
        # deps inherited from base
        deps = resolved.get("dependencies", {})
        assert "ros-jazzy-nav2-bringup" in deps.get("apt", [])

    def test_shallow_merge_parameters_replace(self, tmp_path: Path) -> None:
        """Local parameters entirely replace base parameters."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "parameters": {
                "custom_param": {"type": "string", "default": "hello"},
            },
        })

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)

        # Local parameters replace base entirely
        assert "custom_param" in resolved["parameters"]
        assert "x" not in resolved["parameters"]

    def test_shallow_merge_capabilities_replace(self, tmp_path: Path) -> None:
        """Local required_capabilities entirely replace base."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "required_capabilities": ["custom_drive"],
        })

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)
        assert resolved["required_capabilities"] == ["custom_drive"]

    def test_additive_deps_apt(self, tmp_path: Path) -> None:
        """Local apt deps are added to base apt deps."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "dependencies": {
                "apt": ["ros-jazzy-slam-toolbox"],
            },
        })

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)
        apt_deps = resolved["dependencies"]["apt"]

        # Base apt deps preserved
        assert "ros-jazzy-nav2-bringup" in apt_deps
        # Local apt deps added
        assert "ros-jazzy-slam-toolbox" in apt_deps

    def test_additive_deps_source(self, tmp_path: Path) -> None:
        """Local source deps are added to base source deps."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "dependencies": {
                "source": [
                    {"path": "./src/my_planner", "packages": ["my_planner"]},
                ],
            },
        })

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)
        source_deps = resolved["dependencies"]["source"]

        # Base source deps preserved (defined-platform)
        repos = [s.get("repo") for s in source_deps if s.get("repo")]
        assert any("defined-platform" in r for r in repos)
        # Local source deps added
        paths = [s.get("path") for s in source_deps if s.get("path")]
        assert "./src/my_planner" in paths

    def test_additive_deps_pip(self, tmp_path: Path) -> None:
        """Local pip deps are added to base pip deps."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "dependencies": {
                "pip": ["numpy"],
            },
        })

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)
        pip_deps = resolved["dependencies"]["pip"]
        assert "numpy" in pip_deps

    def test_apt_deduplication(self, tmp_path: Path) -> None:
        """Duplicate apt packages are deduplicated."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "dependencies": {
                "apt": ["ros-jazzy-nav2-bringup", "ros-jazzy-slam-toolbox"],
            },
        })

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)
        apt_deps = resolved["dependencies"]["apt"]

        # nav2-bringup appears in both base and local — should appear once
        assert apt_deps.count("ros-jazzy-nav2-bringup") == 1
        assert "ros-jazzy-slam-toolbox" in apt_deps

    def test_pip_deduplication(self, tmp_path: Path) -> None:
        """Duplicate pip packages are deduplicated."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "dependencies": {
                "pip": ["opencv-python"],
            },
        })
        # go_to base has no pip deps, so let's test with capture_image
        _write_verb(tmp_path, "my_verb", {
            "extends": "defined/capture_image",
            "dependencies": {
                "pip": ["opencv-python", "numpy"],
            },
        })

        resolved = resolve_verb_definition("my_verb", verbs_dir=tmp_path)
        pip_deps = resolved["dependencies"]["pip"]
        # No duplicates
        assert len(pip_deps) == len(set(pip_deps))

    def test_unset_fields_inherited(self, tmp_path: Path) -> None:
        """Fields not set locally are inherited from base."""
        _write_verb(tmp_path, "go_to", {
            "extends": "defined/go_to",
            "description": "My custom go_to",
        })

        resolved = resolve_verb_definition("go_to", verbs_dir=tmp_path)

        # Description overridden
        assert resolved["description"] == "My custom go_to"
        # Template inherited
        assert resolved["template"] == "go_to.xml.j2"
        # Capabilities inherited
        assert "differential_drive" in resolved["required_capabilities"]
        # Runtime inherited
        assert resolved.get("runtime") is not None

    def test_no_extends_uses_local(self, tmp_path: Path) -> None:
        """Verb without extends uses local definition as-is."""
        _write_verb(tmp_path, "custom", {
            "name": "custom",
            "description": "A fully local verb",
            "template": "custom.xml.j2",
            "parameters": {"speed": {"type": "float", "default": 1.0}},
        })

        resolved = resolve_verb_definition("custom", verbs_dir=tmp_path)

        assert resolved["name"] == "custom"
        assert resolved["description"] == "A fully local verb"
        assert resolved["template"] == "custom.xml.j2"

    def test_project_verb_shadows_builtin(self, tmp_path: Path) -> None:
        """A project verb with the same name shadows the built-in (no extends)."""
        _write_verb(tmp_path, "wait", {
            "name": "wait",
            "description": "My custom wait",
            "template": "custom_wait.xml.j2",
            "parameters": {"duration": {"type": "float", "default": 99.0}},
        })

        resolved = resolve_verb_definition("wait", verbs_dir=tmp_path)

        assert resolved["description"] == "My custom wait"
        assert resolved["template"] == "custom_wait.xml.j2"

    def test_extends_nonexistent_raises(self, tmp_path: Path) -> None:
        """extends: defined/nonexistent raises a clear error."""
        _write_verb(tmp_path, "bad", {
            "extends": "defined/nonexistent",
        })

        with pytest.raises(ValueError, match="nonexistent"):
            resolve_verb_definition("bad", verbs_dir=tmp_path)

    def test_extends_non_defined_prefix_raises(self, tmp_path: Path) -> None:
        """extends without defined/ prefix raises an error."""
        _write_verb(tmp_path, "bad", {
            "extends": "some_other/go_to",
        })

        with pytest.raises(ValueError, match="defined/"):
            resolve_verb_definition("bad", verbs_dir=tmp_path)


# ---------------------------------------------------------------------------
# Resolution order: project verbs_dir first → built-in fallback
# ---------------------------------------------------------------------------


class TestResolutionOrder:

    def test_project_dir_tried_first(self, tmp_path: Path) -> None:
        """Verb in project dir is found before built-in."""
        _write_verb(tmp_path, "go_to", {
            "name": "go_to",
            "description": "project override",
            "template": "go_to.xml.j2",
        })

        definition = load_verb_definition("go_to", verbs_dir=tmp_path)
        assert definition["description"] == "project override"

    def test_builtin_fallback(self) -> None:
        """Verb not in project dir falls back to built-in library."""
        definition = load_verb_definition("go_to")
        assert definition["name"] == "go_to"
        assert "differential_drive" in definition.get("required_capabilities", [])


# ---------------------------------------------------------------------------
# expand_verb still works (backward compat)
# ---------------------------------------------------------------------------


class TestExpandVerbBackwardCompat:

    def test_expand_builtin_verb(self) -> None:
        """expand_verb still works for built-in verbs."""
        result = expand_verb("go_to", {"x": 1.0, "y": 2.0})
        assert result["verb"] == "go_to"
        assert result["template"] == "go_to.xml.j2"
        assert result["params"] == {"x": 1.0, "y": 2.0}

    def test_expand_verb_with_extends(self, tmp_path: Path) -> None:
        """expand_verb resolves extends before expanding."""
        _write_verb(tmp_path, "go_to", {"extends": "defined/go_to"})

        result = expand_verb("go_to", {"x": 1.0, "y": 2.0}, verbs_dir=tmp_path)
        assert result["verb"] == "go_to"
        assert result["template"] == "go_to.xml.j2"
        assert "differential_drive" in result["required_capabilities"]


# ---------------------------------------------------------------------------
# BT emitter fallback — project dir stubs resolve built-in templates
# ---------------------------------------------------------------------------


class TestBTEmitterBuiltinFallback:

    def test_render_with_project_stub_uses_builtin_template(self, tmp_path: Path) -> None:
        """A project verbs_dir with only a stub still renders via built-in template."""
        _write_verb(tmp_path, "go_to", {"extends": "defined/go_to"})

        expanded = [expand_verb("go_to", {"x": 1.0, "y": 2.0}, verbs_dir=tmp_path)]
        xml = render_bt_xml(expanded, task_name="FallbackTest", verbs_dir=tmp_path)

        assert 'ID="GoTo"' in xml
        assert 'x="1.0"' in xml

    def test_tree_nodes_model_with_project_stub(self, tmp_path: Path) -> None:
        """TreeNodesModel resolves verb YAML from built-in when project dir has only a stub."""
        _write_verb(tmp_path, "go_to", {"extends": "defined/go_to"})

        expanded = [expand_verb("go_to", {"x": 1.0, "y": 2.0}, verbs_dir=tmp_path)]
        xml = render_bt_xml(expanded, task_name="FallbackTest", verbs_dir=tmp_path)

        assert "TreeNodesModel" in xml
        assert 'ID="GoTo"' in xml
        assert "input_port" in xml
