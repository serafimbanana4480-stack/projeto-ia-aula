"""Tests for deploy_manager.py."""
from __future__ import annotations

from backend.pipeline.deploy_manager import (
    BlueGreenDeployer,
    CanaryDeployer,
    DeployManager,
    DeployResult,
    DeployStatus,
    DeployStrategy,
    HealthCheckResult,
    MonitorConfig,
    PostDeployMonitor,
    RollbackManager,
)


class TestDeployManager:
    """Tests for DeployManager."""

    def test_deploy_to_staging_success(self) -> None:
        dm = DeployManager()
        result = dm.deploy_to_staging("test-project", "v1.0")

        assert result.strategy == DeployStrategy.DIRECT
        assert result.status == DeployStatus.SUCCESS
        assert result.environment == "staging"
        assert result.health_check_passed is True
        assert result.duration_seconds > 0

    def test_deploy_result_success_property(self) -> None:
        result = DeployResult(
            strategy=DeployStrategy.DIRECT,
            status=DeployStatus.SUCCESS,
        )
        assert result.success is True

        failed = DeployResult(
            strategy=DeployStrategy.DIRECT,
            status=DeployStatus.FAILED,
        )
        assert failed.success is False


class TestCanaryDeployer:
    """Tests for CanaryDeployer."""

    def test_deploy_success(self) -> None:
        deployer = CanaryDeployer()
        result = deployer.deploy("test-project", "v2.0")

        assert result.strategy == DeployStrategy.CANARY
        assert result.status == DeployStatus.SUCCESS
        assert result.health_check_passed is True


class TestBlueGreenDeployer:
    """Tests for BlueGreenDeployer."""

    def test_deploy_success(self) -> None:
        deployer = BlueGreenDeployer()
        result = deployer.deploy("test-project", "v3.0")

        assert result.strategy == DeployStrategy.BLUE_GREEN
        assert result.status == DeployStatus.SUCCESS
        assert result.health_check_passed is True

    def test_rollback(self) -> None:
        deployer = BlueGreenDeployer()
        assert deployer._active == "blue"

        deployer.deploy("test-project", "v3.0")
        assert deployer._active == "green"

        env = deployer.rollback()
        assert env == "blue"
        assert deployer._active == "blue"


class TestHealthCheckResult:
    """Tests for HealthCheckResult."""

    def test_to_dict(self) -> None:
        hc = HealthCheckResult(
            endpoint="/health",
            status_code=200,
            response_time_ms=10.0,
            healthy=True,
        )
        d = hc.to_dict()
        assert d["endpoint"] == "/health"
        assert d["status_code"] == 200
        assert d["healthy"] is True

    def test_unhealthy(self) -> None:
        hc = HealthCheckResult(
            endpoint="/api/health",
            status_code=500,
            response_time_ms=5000.0,
            healthy=False,
            error="Connection refused",
        )
        assert hc.healthy is False
        assert hc.error == "Connection refused"


class TestPostDeployMonitor:
    """Tests for PostDeployMonitor."""

    def test_monitor_passes(self) -> None:
        config = MonitorConfig(
            monitor_duration_seconds=5,
            health_check_interval_seconds=1,
            required_health_check_passes=2,
        )
        monitor = PostDeployMonitor(config)
        result = DeployResult(
            strategy=DeployStrategy.DIRECT,
            status=DeployStatus.SUCCESS,
        )
        report = monitor.monitor("test-project", result)

        assert report["passed"] is True
        assert report["checks_passed"] >= config.required_health_check_passes

    def test_monitor_custom_config(self) -> None:
        config = MonitorConfig(
            max_error_rate=0.05,
            max_p95_latency_ms=500.0,
        )
        monitor = PostDeployMonitor(config)
        result = DeployResult(strategy=DeployStrategy.DIRECT, status=DeployStatus.SUCCESS)
        report = monitor.monitor("test-project", result)
        assert report["passed"] is True


class TestRollbackManager:
    """Tests for RollbackManager."""

    def test_should_rollback_when_failed(self) -> None:
        rm = RollbackManager()
        assert rm.should_rollback({"passed": False}) is True

    def test_should_not_rollback_when_passed(self) -> None:
        rm = RollbackManager()
        assert rm.should_rollback({"passed": True}) is False

    def test_execute_rollback(self) -> None:
        rm = RollbackManager()
        result = rm.execute_rollback("test-project", "v5.0", "Health check timeout")

        assert result["success"] is True
        assert result["project"] == "test-project"
        assert result["reason"] == "Health check timeout"

    def test_rollback_history(self) -> None:
        rm = RollbackManager()
        rm.execute_rollback("proj-a", "v1", "reason 1")
        rm.execute_rollback("proj-b", "v2", "reason 2")

        history = rm.get_rollback_history()
        assert len(history) == 2
        assert history[0]["project"] == "proj-a"
        assert history[1]["project"] == "proj-b"


class TestDeployResult:
    """Tests for DeployResult dataclass."""

    def test_fields(self) -> None:
        result = DeployResult(
            strategy=DeployStrategy.CANARY,
            status=DeployStatus.SUCCESS,
            environment="production",
            version="v42",
            duration_seconds=120.5,
            health_check_passed=True,
        )
        assert result.strategy == DeployStrategy.CANARY
        assert result.environment == "production"
        assert result.version == "v42"
        assert result.duration_seconds == 120.5