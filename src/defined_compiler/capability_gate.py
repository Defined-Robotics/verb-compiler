"""Capability gating — check task requirements against RDF capabilities."""

from __future__ import annotations

from defined_rdf.registry import CapabilityRegistry


class GateResult:
    """Result of a capability gate check."""

    def __init__(self, passed: bool, missing: list[str]) -> None:
        self.passed = passed
        self.missing = missing

    @property
    def status(self) -> str:
        return "OK" if self.passed else "REJECTED"


def check(registry: CapabilityRegistry, required_capabilities: list[str]) -> GateResult:
    """Check if all required capabilities are available in the registry."""
    all_met, missing = registry.check_requirements(required_capabilities)
    return GateResult(passed=all_met, missing=missing)
