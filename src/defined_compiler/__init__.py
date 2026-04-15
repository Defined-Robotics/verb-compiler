"""
Defined Compiler — YAML verb tasks to BehaviorTree.CPP XML.

Compiles high-level verb task YAML files into BehaviorTree.CPP v4 XML,
performing capability gating against the robot RDF manifest along the way.

Usage:
    from defined_compiler import bt_emitter, parser, verb_expander
"""

from __future__ import annotations

__version__ = "0.0.1"
