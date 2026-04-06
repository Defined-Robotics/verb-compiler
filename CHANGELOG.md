# Changelog

All notable changes to `defined-compiler` are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `validate_urdf_structure(xml_str)` in `urdf_emitter` — structural validator (backlog 999.8):
  well-formed XML, `base_footprint` declared, no dangling joint refs, exactly one tree root,
  at least 2 continuous joints. Raises `URDFStructureError` on failure.
  Called automatically at the end of `render_urdf()`.
- `URDFStructureError` exception class for structured URDF validation failures.
- 11 new tests in `tests/test_urdf_validator.py` covering all 5 structural checks.

## [0.0.2] — 2026-04-06

### Changed
- Bump `requires-python` to `>=3.12` to match project-wide Python convention.
- Expand module docstrings and add `from __future__ import annotations` to `__init__.py`.

## [0.0.1] — 2026-03-22

### Added
- Initial verb compiler: YAML task parser, verb expander, capability gate.
- BT XML emitter (`bt_emitter`) — renders BehaviorTree.CPP v4 XML via Jinja2 verb templates.
- URDF xacro emitter (`urdf_emitter`) — generates URDF from RDF physical description (DR-014 PoC).
- `defined-compile` CLI: compiles task YAML to BT XML, with `--generate-urdf` mode.
- `verb_library/wait.yaml` — first built-in verb definition.
- Full test suite: unit + integration + e2e chain tests.
