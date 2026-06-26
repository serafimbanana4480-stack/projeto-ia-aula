"""QualityGate — architecture quality checks and validation."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class CheckSeverity(str, Enum):
    BLOCKER = "blocker"
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class QualityCheck:
    """A single quality check result."""

    check_id: str
    name: str
    severity: CheckSeverity
    message: str
    location: str = ""
    recommendation: str = ""
    passed: bool = False


class QualityGate:
    """Validates architecture quality against best practices."""

    def __init__(self) -> None:
        self._checks: list[QualityCheck] = []

    def check_modularity(self, components: list[dict[str, Any]]) -> QualityCheck:
        """Check if components have clear responsibilities."""
        issues = []
        for c in components:
            resp_count = len(c.get("responsibilities", []))
            if resp_count == 0:
                issues.append(f"{c['name']} has no defined responsibilities")
            elif resp_count > 5:
                issues.append(f"{c['name']} has too many responsibilities ({resp_count})")

        passed = len(issues) == 0
        return QualityCheck(
            check_id="QG-MOD-001",
            name="Modularity Check",
            severity=CheckSeverity.CRITICAL if issues else CheckSeverity.INFO,
            message="; ".join(issues) if issues else "All components have clear responsibilities",
            recommendation="Apply Single Responsibility Principle" if issues else "",
            passed=passed,
        )

    def check_coupling(self, data_flows: list[dict[str, Any]]) -> QualityCheck:
        """Check for excessive coupling between components."""
        if not data_flows:
            return QualityCheck(
                check_id="QG-COU-001",
                name="Coupling Check",
                severity=CheckSeverity.WARNING,
                message="No data flows defined — cannot assess coupling",
                recommendation="Document component interactions",
                passed=False,
            )

        # Check for hub components (too many connections)
        connection_counts: dict[str, int] = {}
        for f in data_flows:
            connection_counts[f.get("source", "")] = connection_counts.get(f.get("source", ""), 0) + 1
            connection_counts[f.get("target", "")] = connection_counts.get(f.get("target", ""), 0) + 1

        issues = []
        for comp, count in connection_counts.items():
            if count > 5:
                issues.append(f"{comp} has {count} connections — consider decoupling")

        passed = len(issues) == 0
        return QualityCheck(
            check_id="QG-COU-001",
            name="Coupling Check",
            severity=CheckSeverity.WARNING if issues else CheckSeverity.INFO,
            message="; ".join(issues) if issues else "Coupling levels acceptable",
            recommendation="Introduce message bus or event-driven architecture" if issues else "",
            passed=passed,
        )

    def check_security(self, components: list[dict[str, Any]]) -> QualityCheck:
        """Check for security best practices."""
        has_auth = any("auth" in str(c).lower() for c in components)
        has_gateway = any("gateway" in str(c).lower() for c in components)

        issues = []
        if not has_auth:
            issues.append("No authentication component detected")
        if not has_gateway:
            issues.append("No API gateway detected")

        passed = len(issues) == 0
        return QualityCheck(
            check_id="QG-SEC-001",
            name="Security Check",
            severity=CheckSeverity.BLOCKER if not has_auth else CheckSeverity.INFO,
            message="; ".join(issues) if issues else "Security measures adequate",
            recommendation="Add authentication and API gateway" if issues else "",
            passed=passed,
        )

    def check_scalability(self, components: list[dict[str, Any]]) -> QualityCheck:
        """Check for scalability considerations."""
        has_cache = any("cache" in str(c).lower() for c in components)
        has_queue = any("queue" in str(c).lower() for c in components)

        passed = has_cache and has_queue
        return QualityCheck(
            check_id="QG-SCA-001",
            name="Scalability Check",
            severity=CheckSeverity.WARNING if not passed else CheckSeverity.INFO,
            message="Missing cache or queue components" if not passed else "Scalability patterns present",
            recommendation="Add Redis cache and message queue" if not passed else "",
            passed=passed,
        )

    def run_all_checks(self, components: list[dict[str, Any]], data_flows: list[dict[str, Any]]) -> list[QualityCheck]:
        """Run all quality checks."""
        self._checks = [
            self.check_modularity(components),
            self.check_coupling(data_flows),
            self.check_security(components),
            self.check_scalability(components),
        ]
        return self._checks

    def get_summary(self) -> dict[str, Any]:
        if not self._checks:
            return {"total": 0, "passed": 0, "failed": 0, "score": 0.0}
        passed = sum(1 for c in self._checks if c.passed)
        blockers = sum(1 for c in self._checks if c.severity == CheckSeverity.BLOCKER and not c.passed)
        return {
            "total": len(self._checks),
            "passed": passed,
            "failed": len(self._checks) - passed,
            "blockers": blockers,
            "score": passed / len(self._checks),
        }
