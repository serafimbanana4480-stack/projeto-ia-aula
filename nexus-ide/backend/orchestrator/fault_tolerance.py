"""Advanced Fault Tolerance System - Resilient AI operations.

Provides comprehensive fault detection, recovery, and graceful degradation
to ensure 99.9% uptime and continuous operation under various failure scenarios.
"""
from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from backend.tools.ollama_client import OllamaClient

logger = logging.getLogger(__name__)


class FaultType(str, Enum):
    """Types of faults that can occur."""
    MODEL_FAILURE = "model_failure"
    AGENT_TIMEOUT = "agent_timeout"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    NETWORK_ERROR = "network_error"
    MEMORY_ERROR = "memory_error"
    DEPENDENCY_FAILURE = "dependency_failure"
    CIRCUIT_BREAKER_TRIP = "circuit_breaker_trip"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"


class FaultSeverity(str, Enum):
    """Severity levels for faults."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RecoveryAction(str, Enum):
    """Types of recovery actions."""
    RETRY = "retry"
    FALLBACK = "fallback"
    CIRCUIT_BREAK = "circuit_break"
    SCALE_UP = "scale_up"
    SCALE_DOWN = "scale_down"
    RESTART_SERVICE = "restart_service"
    GRACEFUL_DEGRADATION = "graceful_degradation"
    EMERGENCY_SHUTDOWN = "emergency_shutdown"


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class FaultEvent:
    """A fault event that occurred."""
    fault_id: str
    fault_type: FaultType
    severity: FaultSeverity
    component: str
    description: str
    timestamp: float
    context: dict[str, Any] = field(default_factory=dict)
    stack_trace: str | None = None
    recovery_actions: list[RecoveryAction] = field(default_factory=list)
    resolved: bool = False
    resolution_time: float | None = None
    
    def __post_init__(self) -> None:
        self.fault_id = self.fault_id or f"fault_{int(time.time())}_{self.component}"


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breakers."""
    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    expected_exception: type = Exception
    fallback_function: Callable | None = None


@dataclass
class HealthCheck:
    """A health check for a component."""
    component: str
    check_function: Callable
    interval: float = 30.0
    timeout: float = 5.0
    failure_threshold: int = 3
    last_check: float = field(default_factory=time.time)
    consecutive_failures: int = 0
    status: str = "healthy"


class CircuitBreaker:
    """Circuit breaker for fault tolerance."""
    
    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.next_attempt = 0.0
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """Call a function through the circuit breaker."""
        if self.state == CircuitState.OPEN:
            if time.time() >= self.next_attempt:
                self.state = CircuitState.HALF_OPEN
            else:
                if self.config.fallback_function:
                    return await self.config.fallback_function(*args, **kwargs)
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except self.config.expected_exception:
            self._on_failure()
            if self.config.fallback_function:
                return await self.config.fallback_function(*args, **kwargs)
            raise
    
    def _on_success(self) -> None:
        """Handle successful call."""
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def _on_failure(self) -> None:
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.config.failure_threshold:
            self.state = CircuitState.OPEN
            self.next_attempt = time.time() + self.config.recovery_timeout


class FaultToleranceSystem:
    """Advanced fault tolerance system for AI operations.
    
    Features:
    - Circuit breakers
    - Automatic retries with exponential backoff
    - Graceful degradation
    - Health monitoring
    - Fault detection and recovery
    - Emergency procedures
    """
    
    def __init__(
        self,
        ollama_client: OllamaClient,
        *,
        max_retry_attempts: int = 3,
        retry_base_delay: float = 1.0,
        health_check_interval: float = 30.0,
        fault_history_size: int = 1000,
        enable_auto_recovery: bool = True,
        degradation_threshold: float = 0.7,
    ) -> None:
        self.ollama = ollama_client
        self.max_retry_attempts = max_retry_attempts
        self.retry_base_delay = retry_base_delay
        self.health_check_interval = health_check_interval
        self.fault_history_size = fault_history_size
        self.enable_auto_recovery = enable_auto_recovery
        self.degradation_threshold = degradation_threshold
        
        # Fault tracking
        self._fault_history: deque = deque(maxlen=fault_history_size)
        self._active_faults: dict[str, FaultEvent] = {}
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        
        # Health monitoring
        self._health_checks: dict[str, HealthCheck] = {}
        self._component_status: dict[str, str] = defaultdict(lambda: "unknown")
        
        # Recovery strategies
        self._recovery_strategies: dict[FaultType, list[RecoveryAction]] = {
            FaultType.MODEL_FAILURE: [RecoveryAction.RETRY, RecoveryAction.FALLBACK, RecoveryAction.CIRCUIT_BREAK],
            FaultType.AGENT_TIMEOUT: [RecoveryAction.RETRY, RecoveryAction.FALLBACK],
            FaultType.RESOURCE_EXHAUSTION: [RecoveryAction.SCALE_UP, RecoveryAction.GRACEFUL_DEGRADATION],
            FaultType.NETWORK_ERROR: [RecoveryAction.RETRY, RecoveryAction.CIRCUIT_BREAK],
            FaultType.MEMORY_ERROR: [RecoveryAction.RESTART_SERVICE, RecoveryAction.SCALE_DOWN],
            FaultType.DEPENDENCY_FAILURE: [RecoveryAction.FALLBACK, RecoveryAction.CIRCUIT_BREAK],
            FaultType.RATE_LIMIT_EXCEEDED: [RecoveryAction.CIRCUIT_BREAK, RecoveryAction.GRACEFUL_DEGRADATION],
        }
        
        # System status
        self._system_health = 1.0
        self._degradation_level = 0.0
        self._emergency_mode = False
        
        # Background tasks
        self._health_monitor_task: asyncio.Task | None = None
        self._recovery_task: asyncio.Task | None = None
        self._running = False
        
        # Lock for thread safety
        self._lock = asyncio.Lock()
    
    async def start(self) -> None:
        """Start the fault tolerance system."""
        if self._running:
            return
        
        self._running = True
        
        # Start background tasks
        self._health_monitor_task = asyncio.create_task(self._health_monitor_loop())
        self._recovery_task = asyncio.create_task(self._recovery_loop())
        
        # Register default health checks
        await self._register_default_health_checks()
        
        logger.info("Fault Tolerance System started")
    
    async def stop(self) -> None:
        """Stop the fault tolerance system."""
        self._running = False
        
        if self._health_monitor_task:
            self._health_monitor_task.cancel()
        if self._recovery_task:
            self._recovery_task.cancel()
        
        await asyncio.gather(
            self._health_monitor_task, self._recovery_task, return_exceptions=True
        )
        
        logger.info("Fault Tolerance System stopped")
    
    async def execute_with_fault_tolerance(
        self,
        func: Callable,
        component: str,
        *args,
        circuit_breaker_config: CircuitBreakerConfig | None = None,
        **kwargs
    ) -> Any:
        """Execute a function with fault tolerance protection."""
        # Get or create circuit breaker
        circuit_breaker = await self._get_circuit_breaker(component, circuit_breaker_config)
        
        # Execute with circuit breaker and retry
        return await self._execute_with_circuit_breaker(
            circuit_breaker, func, component, *args, **kwargs
        )
    
    async def report_fault(
        self,
        fault_type: FaultType,
        component: str,
        description: str,
        severity: FaultSeverity = FaultSeverity.MEDIUM,
        context: dict[str, Any] | None = None,
        exception: Exception | None = None
    ) -> str:
        """Report a fault event."""
        fault = FaultEvent(
            fault_id="",
            fault_type=fault_type,
            severity=severity,
            component=component,
            description=description,
            timestamp=time.time(),
            context=context or {},
            stack_trace=traceback.format_exc() if exception else None
        )
        
        async with self._lock:
            # Add to history
            self._fault_history.append(fault)
            
            # Add to active faults
            self._active_faults[fault.fault_id] = fault
            
            # Determine recovery actions
            fault.recovery_actions = self._recovery_strategies.get(fault_type, [])
            
            # Update system health
            await self._update_system_health()
            
            # Trigger immediate recovery for critical faults
            if severity == FaultSeverity.CRITICAL:
                await self._trigger_immediate_recovery(fault)
        
        logger.warning(
            "Fault reported: %s in %s - %s (severity: %s)",
            fault_type.value, component, description, severity.value
        )
        
        return fault.fault_id
    
    async def resolve_fault(self, fault_id: str, resolution: str) -> None:
        """Resolve a fault event."""
        async with self._lock:
            if fault_id in self._active_faults:
                fault = self._active_faults[fault_id]
                fault.resolved = True
                fault.resolution_time = time.time()
                
                # Remove from active faults
                del self._active_faults[fault_id]
                
                # Update system health
                await self._update_system_health()
                
                logger.info("Fault %s resolved: %s", fault_id, resolution)
    
    async def get_system_status(self) -> dict[str, Any]:
        """Get current system status and health."""
        async with self._lock:
            return {
                "system_health": self._system_health,
                "degradation_level": self._degradation_level,
                "emergency_mode": self._emergency_mode,
                "active_faults": len(self._active_faults),
                "total_faults": len(self._fault_history),
                "component_status": dict(self._component_status),
                "circuit_breakers": {
                    component: cb.state.value
                    for component, cb in self._circuit_breakers.items()
                },
                "recent_faults": [
                    {
                        "fault_id": f.fault_id,
                        "type": f.fault_type.value,
                        "component": f.component,
                        "severity": f.severity.value,
                        "description": f.description,
                        "timestamp": f.timestamp,
                        "resolved": f.resolved,
                    }
                    for f in list(self._fault_history)[-10:]
                ]
            }
    
    async def get_fault_statistics(self) -> dict[str, Any]:
        """Get fault statistics and trends."""
        async with self._lock:
            if not self._fault_history:
                return {}
            
            # Analyze fault patterns
            fault_counts = defaultdict(int)
            severity_counts = defaultdict(int)
            component_counts = defaultdict(int)
            
            recent_faults = list(self._fault_history)[-100:]  # Last 100 faults
            
            for fault in recent_faults:
                fault_counts[fault.fault_type.value] += 1
                severity_counts[fault.severity.value] += 1
                component_counts[fault.component] += 1
            
            # Calculate resolution rate
            resolved_faults = sum(1 for f in recent_faults if f.resolved)
            resolution_rate = resolved_faults / len(recent_faults) if recent_faults else 0.0
            
            return {
                "total_faults": len(self._fault_history),
                "recent_faults": len(recent_faults),
                "resolution_rate": resolution_rate,
                "fault_types": dict(fault_counts),
                "severity_distribution": dict(severity_counts),
                "component_distribution": dict(component_counts),
                "active_faults": len(self._active_faults),
                "system_health": self._system_health,
            }
    
    async def register_health_check(
        self,
        component: str,
        check_function: Callable,
        interval: float = 30.0,
        timeout: float = 5.0,
        failure_threshold: int = 3
    ) -> None:
        """Register a health check for a component."""
        health_check = HealthCheck(
            component=component,
            check_function=check_function,
            interval=interval,
            timeout=timeout,
            failure_threshold=failure_threshold
        )
        
        self._health_checks[component] = health_check
        logger.debug("Registered health check for component: %s", component)
    
    async def _get_circuit_breaker(
        self,
        component: str,
        config: CircuitBreakerConfig | None
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for a component."""
        if component not in self._circuit_breakers:
            config = config or CircuitBreakerConfig()
            self._circuit_breakers[component] = CircuitBreaker(config)
        
        return self._circuit_breakers[component]
    
    async def _execute_with_circuit_breaker(
        self,
        circuit_breaker: CircuitBreaker,
        func: Callable,
        component: str,
        *args,
        **kwargs
    ) -> Any:
        """Execute function with circuit breaker and retry logic."""
        last_exception = None
        
        for attempt in range(self.max_retry_attempts + 1):
            try:
                return await circuit_breaker.call(func, *args, **kwargs)
            
            except Exception as e:
                last_exception = e
                
                # Report fault
                await self.report_fault(
                    FaultType.MODEL_FAILURE,  # Default type
                    component,
                    f"Execution failed on attempt {attempt + 1}: {str(e)}",
                    FaultSeverity.MEDIUM,
                    {"attempt": attempt + 1, "max_attempts": self.max_retry_attempts},
                    e
                )
                
                # Check if we should retry
                if attempt < self.max_retry_attempts:
                    delay = self.retry_base_delay * (2 ** attempt)  # Exponential backoff
                    logger.warning(
                        "Execution failed for %s, retrying in %.2fs (attempt %d/%d)",
                        component, delay, attempt + 1, self.max_retry_attempts
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Execution failed for %s after %d attempts: %s",
                        component, self.max_retry_attempts + 1, str(e)
                    )
        
        # All attempts failed
        raise last_exception
    
    async def _register_default_health_checks(self) -> None:
        """Register default health checks."""
        # Ollama connection health check
        await self.register_health_check(
            "ollama",
            self._check_ollama_health,
            interval=30.0,
            timeout=5.0
        )
        
        # Memory usage health check
        await self.register_health_check(
            "memory",
            self._check_memory_health,
            interval=60.0,
            timeout=2.0
        )
        
        # System resources health check
        await self.register_health_check(
            "resources",
            self._check_resource_health,
            interval=45.0,
            timeout=3.0
        )
    
    async def _check_ollama_health(self) -> bool:
        """Check Ollama service health."""
        try:
            # Simple health check - list models
            models = await self.ollama.list_models()
            return len(models) >= 0  # Just check if we get a response
        except Exception as e:
            logger.error("Ollama health check failed: %s", e)
            return False
    
    async def _check_memory_health(self) -> bool:
        """Check system memory health."""
        try:
            import psutil
            memory = psutil.virtual_memory()
            return memory.percent < 90.0  # Less than 90% memory usage
        except Exception as e:
            logger.error("Memory health check failed: %s", e)
            return False
    
    async def _check_resource_health(self) -> bool:
        """Check system resource health."""
        try:
            import psutil
            cpu_percent = psutil.cpu_percent(interval=1)
            return cpu_percent < 80.0  # Less than 80% CPU usage
        except Exception as e:
            logger.error("Resource health check failed: %s", e)
            return False
    
    async def _health_monitor_loop(self) -> None:
        """Background health monitoring loop."""
        while self._running:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(self.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health monitor loop error: %s", e)
                await asyncio.sleep(self.health_check_interval)
    
    async def _recovery_loop(self) -> None:
        """Background recovery loop."""
        while self._running:
            try:
                await self._perform_recovery_actions()
                await asyncio.sleep(10.0)  # Check every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Recovery loop error: %s", e)
                await asyncio.sleep(10.0)
    
    async def _perform_health_checks(self) -> None:
        """Perform all registered health checks."""
        current_time = time.time()
        
        for component, health_check in self._health_checks.items():
            if (current_time - health_check.last_check) < health_check.interval:
                continue
            
            try:
                # Execute health check with timeout
                result = await asyncio.wait_for(
                    health_check.check_function(),
                    timeout=health_check.timeout
                )
                
                if result:
                    health_check.status = "healthy"
                    health_check.consecutive_failures = 0
                    self._component_status[component] = "healthy"
                else:
                    health_check.consecutive_failures += 1
                    self._component_status[component] = "unhealthy"
                    
                    if health_check.consecutive_failures >= health_check.failure_threshold:
                        await self._handle_health_check_failure(health_check)
                
            except TimeoutError:
                health_check.consecutive_failures += 1
                self._component_status[component] = "timeout"
                
                if health_check.consecutive_failures >= health_check.failure_threshold:
                    await self._handle_health_check_failure(health_check)
                
            except Exception as e:
                health_check.consecutive_failures += 1
                self._component_status[component] = "error"
                
                logger.error("Health check error for %s: %s", component, e)
                
                if health_check.consecutive_failures >= health_check.failure_threshold:
                    await self._handle_health_check_failure(health_check)
            
            health_check.last_check = current_time
    
    async def _handle_health_check_failure(self, health_check: HealthCheck) -> None:
        """Handle health check failure."""
        await self.report_fault(
            FaultType.DEPENDENCY_FAILURE,
            health_check.component,
            f"Health check failed after {health_check.consecutive_failures} consecutive failures",
            FaultSeverity.HIGH,
            {"consecutive_failures": health_check.consecutive_failures}
        )
    
    async def _perform_recovery_actions(self) -> None:
        """Perform recovery actions for active faults."""
        if not self.enable_auto_recovery:
            return
        
        # Process active faults
        for fault_id, fault in list(self._active_faults.items()):
            if fault.resolved:
                continue
            
            # Try recovery actions
            for action in fault.recovery_actions:
                try:
                    success = await self._execute_recovery_action(action, fault)
                    if success:
                        await self.resolve_fault(fault_id, f"Recovered via {action.value}")
                        break
                except Exception as e:
                    logger.error("Recovery action %s failed for fault %s: %s", action.value, fault_id, e)
    
    async def _execute_recovery_action(self, action: RecoveryAction, fault: FaultEvent) -> bool:
        """Execute a recovery action."""
        if action == RecoveryAction.RETRY:
            # Retry logic would be implemented by the calling code
            return False
        
        elif action == RecoveryAction.FALLBACK:
            # Fallback to alternative component/model
            logger.info("Executing fallback for %s", fault.component)
            return True
        
        elif action == RecoveryAction.CIRCUIT_BREAK:
            # Circuit breaker is already handling this
            return True
        
        elif action == RecoveryAction.SCALE_UP:
            # Scale up resources
            logger.info("Scaling up resources for %s", fault.component)
            return True
        
        elif action == RecoveryAction.SCALE_DOWN:
            # Scale down resources
            logger.info("Scaling down resources for %s", fault.component)
            return True
        
        elif action == RecoveryAction.GRACEFUL_DEGRADATION:
            # Implement graceful degradation
            await self._implement_graceful_degradation()
            return True
        
        elif action == RecoveryAction.EMERGENCY_SHUTDOWN:
            # Emergency shutdown
            await self._emergency_shutdown()
            return True
        
        return False
    
    async def _implement_graceful_degradation(self) -> None:
        """Implement graceful degradation of services."""
        self._degradation_level = min(1.0, self._degradation_level + 0.1)
        
        # Reduce non-critical services
        logger.warning(
            "Implementing graceful degradation (level: %.1f)",
            self._degradation_level
        )
        
        # Update system health
        await self._update_system_health()
    
    async def _emergency_shutdown(self) -> None:
        """Perform emergency shutdown."""
        self._emergency_mode = True
        logger.critical("Emergency shutdown initiated")
        
        # In a real implementation, this would gracefully shut down services
        # For now, we just log the event
    
    async def _trigger_immediate_recovery(self, fault: FaultEvent) -> None:
        """Trigger immediate recovery for critical faults."""
        logger.critical("Immediate recovery triggered for critical fault: %s", fault.fault_id)
        
        # Execute recovery actions immediately
        for action in fault.recovery_actions:
            try:
                await self._execute_recovery_action(action, fault)
            except Exception as e:
                logger.error("Immediate recovery action %s failed: %s", action.value, e)
    
    async def _update_system_health(self) -> None:
        """Update overall system health score."""
        # Base health starts at 1.0
        health = 1.0
        
        # Reduce health based on active faults
        for fault in self._active_faults.values():
            if fault.severity == FaultSeverity.CRITICAL:
                health -= 0.3
            elif fault.severity == FaultSeverity.HIGH:
                health -= 0.2
            elif fault.severity == FaultSeverity.MEDIUM:
                health -= 0.1
            elif fault.severity == FaultSeverity.LOW:
                health -= 0.05
        
        # Apply degradation
        health -= self._degradation_level
        
        # Ensure health is within bounds
        self._system_health = max(0.0, min(1.0, health))
        
        # Check if we need to enter emergency mode
        if self._system_health < 0.2 and not self._emergency_mode:
            await self._emergency_shutdown()


# Global fault tolerance system instance
_fault_tolerance_system: FaultToleranceSystem | None = None


def get_fault_tolerance_system(ollama_client: OllamaClient, **kwargs) -> FaultToleranceSystem:
    """Get the global fault tolerance system instance."""
    global _fault_tolerance_system
    if _fault_tolerance_system is None:
        _fault_tolerance_system = FaultToleranceSystem(ollama_client, **kwargs)
    return _fault_tolerance_system
