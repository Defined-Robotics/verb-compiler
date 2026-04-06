"""
Capability gating — check task requirements against RDF capabilities.

Validates that every capability required by a verb is present in the
robot's RDF manifest before compilation proceeds. A failed gate causes
the compilation to be rejected rather than producing an invalid BT XML.

Usage:
    from defined_compiler.capability_gate import check

    result = check(registry, ["navigate_2d", "rgb_camera"])
    if not result.passed:
        raise RuntimeError(f"Missing: {result.missing}")
"""

from __future__ import annotations

from defined_rdf.registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# GateResult
# ---------------------------------------------------------------------------


class GateResult:
    """Result of a single capability gate check.

    Attributes:
        passed: ``True`` if all required capabilities are satisfied.
        missing: Names of capabilities that are absent from the registry.
    """

    def __init__(self, passed: bool, missing: list[str]) -> None:
        self.passed = passed
        self.missing = missing

    @property
    def status(self) -> str:
        """Return ``'OK'`` if the gate passed, otherwise ``'REJECTED'``."""
        return "OK" if self.passed else "REJECTED"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check(registry: CapabilityRegistry, required_capabilities: list[str]) -> GateResult:
    """Check whether all required capabilities are present in the registry.

    Args:
        registry: Capability registry built from the robot's RDF manifest.
        required_capabilities: List of capability identifiers that the verb
            requires (e.g. ``["navigate_2d", "rgb_camera"]``).

    Returns:
        A :class:`GateResult` with ``passed=True`` if all requirements are
        met, or ``passed=False`` plus the list of missing capability names.
    """
    all_met, missing = registry.check_requirements(required_capabilities)
    return GateResult(passed=all_met, missing=missing)
