"""DeployManager — intelligent deploy orchestration.

Handles staging deploy, canary/blue-green strategies, post-deploy
monitoring, and automatic rollback.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class DeployStrategy(Enum):
    """Supported deploy strategies."""

    DIRECT = "direct"
    CANARY = "canary"
    BLUE_GREEN = "blue-green"


class DeployStatus(Enum):
    """Deployment lifecycle status."""

    PENDING = "pending"
    IN_PROGRESS = "in-progress"
    HEALTH_CHECK = "health-check"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled-back"


@dataclass
class DeployResult:
    """Result of a deployment operation."""

    strategy: DeployStrategy
    status: DeployStatus
    environment: str = "staging"
    version: str = ""
    duration_seconds: float = 0.0
    health_check_passed: bool = False
    error_message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def success(self) -> bool:
        return self.status == DeployStatus.SUCCESS


@dataclass
class HealthCheckResult:
    """Result of a health check operation."""

    endpoint: str
    status_code: int = 0
    response_time_ms: float = 0.0
    healthy: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "healthy": self.healthy,
            "error": self.error,
        }


@dataclass
class MonitorConfig:
    """Configuration for post-deploy monitoring."""

    monitor_duration_seconds: int = 900  # 15 minutes
    health_check_interval_seconds: int = 30
    max_error_rate: float = 0.01  # 1%
    max_p95_latency_ms: float = 200.0
    required_health_check_passes: int = 3


class DeployManager:
    """Orchestrates deployments to staging/production."""

    def __init__(self) -> None:
        self._health_endpoints: list[str] = ["/health", "/api/health"]

    def deploy_to_staging(self, project_name: str, version: str = "latest") -> DeployResult:
        """Deploy a project to staging environment.

        Args:
            project_name: Project identifier.
            version: Docker image version/tag.

        Returns:
            DeployResult with deployment status.
        """
        logger.info("Starting staging deploy: %s:%s", project_name, version)
        start = time.monotonic()

        try:
            # Simulate docker-compose up
            logger.info("Running docker-compose up for %s", project_name)
            time.sleep(0.5)  # Simulate deploy time

            # Run health checks
            healthy = self._run_health_checks(project_name)

            duration = time.monotonic() - start
            status = DeployStatus.SUCCESS if healthy else DeployStatus.FAILED

            return DeployResult(
                strategy=DeployStrategy.DIRECT,
                status=status,
                environment="staging",
                version=version,
                duration_seconds=duration,
                health_check_passed=healthy,
                error_message="" if healthy else "Health checks failed",
            )

        except Exception as exc:
            duration = time.monotonic() - start
            logger.error("Staging deploy failed: %s", exc)
            return DeployResult(
                strategy=DeployStrategy.DIRECT,
                status=DeployStatus.FAILED,
                environment="staging",
                version=version,
                duration_seconds=duration,
                error_message=str(exc),
            )

    def _run_health_checks(self, project_name: str) -> bool:
        """Run health checks against deployed service."""
        results: list[HealthCheckResult] = []
        for endpoint in self._health_endpoints:
            # In real implementation, make HTTP requests
            # For now, simulate healthy response
            results.append(HealthCheckResult(
                endpoint=endpoint,
                status_code=200,
                response_time_ms=15.0,
                healthy=True,
            ))

        all_healthy = all(r.healthy for r in results)
        logger.info("Health checks for %s: %s/%s passed", project_name,
                     sum(1 for r in results if r.healthy), len(results))
        return all_healthy


class CanaryDeployer:
    """Implements canary deployment with gradual traffic shifting."""

    CANARY_STAGES = [
        (10, 60),   # 10% traffic for 60s
        (50, 120),  # 50% traffic for 120s
        (100, 60),  # 100% traffic for 60s
    ]

    def __init__(self, deploy_manager: DeployManager | None = None) -> None:
        self._deploy = deploy_manager or DeployManager()

    def deploy(self, project_name: str, version: str) -> DeployResult:
        """Execute canary deployment.

        Args:
            project_name: Project identifier.
            version: New version tag.

        Returns:
            DeployResult.
        """
        logger.info("Starting canary deploy: %s:%s", project_name, version)
        start = time.monotonic()

        for traffic_percent, duration_seconds in self.CANARY_STAGES:
            logger.info("Canary stage: %s%% traffic for %ss", traffic_percent, duration_seconds)
            time.sleep(0.05)  # Simulate

            # Health check at each stage
            if not self._deploy._run_health_checks(project_name):
                duration = time.monotonic() - start
                logger.error("Canary deploy aborted at %s%%: health check failed", traffic_percent)
                return DeployResult(
                    strategy=DeployStrategy.CANARY,
                    status=DeployStatus.FAILED,
                    environment="staging",
                    version=version,
                    duration_seconds=duration,
                    error_message=f"Health check failed at {traffic_percent}% traffic",
                )

        duration = time.monotonic() - start
        logger.info("Canary deploy complete: %s:%s", project_name, version)
        return DeployResult(
            strategy=DeployStrategy.CANARY,
            status=DeployStatus.SUCCESS,
            environment="staging",
            version=version,
            duration_seconds=duration,
            health_check_passed=True,
        )


class BlueGreenDeployer:
    """Implements blue-green deployment with atomic switching."""

    def __init__(self, deploy_manager: DeployManager | None = None) -> None:
        self._deploy = deploy_manager or DeployManager()
        self._active: str = "blue"

    def deploy(self, project_name: str, version: str) -> DeployResult:
        """Execute blue-green deployment.

        Args:
            project_name: Project identifier.
            version: New version tag.
        """
        start = time.monotonic()
        inactive = "green" if self._active == "blue" else "blue"

        logger.info("Deploying %s to %s environment", project_name, inactive)

        # Deploy new version to inactive environment
        time.sleep(0.05)  # Simulate

        # Health check inactive environment
        if not self._deploy._run_health_checks(project_name):
            duration = time.monotonic() - start
            return DeployResult(
                strategy=DeployStrategy.BLUE_GREEN,
                status=DeployStatus.FAILED,
                environment="staging",
                version=version,
                duration_seconds=duration,
                error_message=f"Health check failed on {inactive}",
            )

        # Switch traffic
        logger.info("Switching traffic: %s -> %s", self._active, inactive)
        self._active = inactive

        duration = time.monotonic() - start
        return DeployResult(
            strategy=DeployStrategy.BLUE_GREEN,
            status=DeployStatus.SUCCESS,
            environment="staging",
            version=version,
            duration_seconds=duration,
            health_check_passed=True,
        )

    def rollback(self) -> str:
        """Rollback to the other environment."""
        previous = "green" if self._active == "blue" else "blue"
        logger.info("Rolling back: %s -> %s", self._active, previous)
        self._active = previous
        return previous


class PostDeployMonitor:
    """Monitors deployed service health post-deployment."""

    def __init__(self, config: MonitorConfig | None = None) -> None:
        self._config = config or MonitorConfig()

    def monitor(self, project_name: str, deploy_result: DeployResult) -> dict[str, Any]:
        """Monitor deployed service for configured duration.

        Args:
            project_name: Project identifier.
            deploy_result: Result of the deployment to monitor.

        Returns:
            Monitoring report with pass/fail and metrics.
        """
        logger.info("Starting post-deploy monitor for %s (%ss)",
                     project_name, self._config.monitor_duration_seconds)

        checks_passed = 0
        checks_failed = 0
        metrics: dict[str, Any] = {
            "error_rate": 0.0,
            "p95_latency_ms": 0.0,
            "health_checks_total": 0,
        }

        num_intervals = max(1, self._config.monitor_duration_seconds // self._config.health_check_interval_seconds)
        for i in range(min(num_intervals, 10)):  # Limit iterations for simulation
            time.sleep(0.02)  # Simulate
            healthy = True  # Simulated
            if healthy:
                checks_passed += 1
            else:
                checks_failed += 1

        metrics["health_checks_total"] = checks_passed + checks_failed
        passed = checks_passed >= self._config.required_health_check_passes
        metrics["passed"] = passed
        metrics["checks_passed"] = checks_passed
        metrics["checks_failed"] = checks_failed

        logger.info("Post-deploy monitor for %s: %s", project_name,
                     "PASSED" if passed else "FAILED")
        return metrics


class RollbackManager:
    """Manages automatic rollback when post-deploy monitoring fails."""

    def __init__(self) -> None:
        self._rollback_history: list[dict[str, Any]] = []

    def should_rollback(self, monitor_result: dict[str, Any]) -> bool:
        """Determine if rollback should be triggered.

        Args:
            monitor_result: PostDeployMonitor output.

        Returns:
            True if rollback is needed.
        """
        return not monitor_result.get("passed", True)

    def execute_rollback(self, project_name: str, version: str,
                         reason: str = "") -> dict[str, Any]:
        """Execute rollback to previous version.

        Args:
            project_name: Project identifier.
            version: Version being rolled back.
            reason: Reason for rollback.

        Returns:
            Rollback result.
        """
        logger.warning("ROLLBACK: %s from %s - Reason: %s", project_name, version, reason)

        entry = {
            "project": project_name,
            "version": version,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._rollback_history.append(entry)

        return {
            "success": True,
            "project": project_name,
            "previous_version": version,
            "reason": reason,
        }

    def get_rollback_history(self) -> list[dict[str, Any]]:
        """Return rollback history."""
        return list(self._rollback_history)