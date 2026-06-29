"""Comprehensive Testing Framework for AI Operating System.

Implements unit tests, integration tests, performance tests, security tests,
and end-to-end testing with automated test discovery and execution.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
import unittest
import pytest
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union, Callable
from datetime import datetime
import inspect
import importlib
import sys
from pathlib import Path

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class TestType(str, Enum):
    """Types of tests."""
    UNIT = "unit"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"
    SECURITY = "security"
    END_TO_END = "end_to_end"
    API = "api"
    UI = "ui"
    LOAD = "load"
    STRESS = "stress"


class TestStatus(str, Enum):
    """Test execution status."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


class Priority(str, Enum):
    """Test priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class TestCase:
    """Individual test case."""
    test_id: str = field(default_factory=lambda: f"test-{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    
    # Test classification
    test_type: TestType = TestType.UNIT
    priority: Priority = Priority.MEDIUM
    tags: Set[str] = field(default_factory=set)
    
    # Test location
    module: str = ""
    class_name: str = ""
    function_name: str = ""
    file_path: str = ""
    line_number: int = 0
    
    # Test function
    test_function: Optional[Callable] = None
    setup_function: Optional[Callable] = None
    teardown_function: Optional[Callable] = None
    
    # Test parameters
    parameters: Dict[str, Any] = field(default_factory=dict)
    fixtures: List[str] = field(default_factory=list)
    
    # Dependencies
    dependencies: List[str] = field(default_factory=list)
    
    # Execution metadata
    timeout: float = 30.0
    retries: int = 0
    flaky: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_id": self.test_id,
            "name": self.name,
            "description": self.description,
            "test_type": self.test_type.value,
            "priority": self.priority.value,
            "tags": list(self.tags),
            "module": self.module,
            "class_name": self.class_name,
            "function_name": self.function_name,
            "file_path": self.file_path,
            "line_number": self.line_number,
            "parameters": self.parameters,
            "fixtures": self.fixtures,
            "dependencies": self.dependencies,
            "timeout": self.timeout,
            "retries": self.retries,
            "flaky": self.flaky,
        }


@dataclass
class TestResult:
    """Result of test execution."""
    result_id: str = field(default_factory=lambda: f"result-{uuid.uuid4().hex[:12]}")
    test_id: str = ""
    
    # Execution details
    status: TestStatus = TestStatus.PENDING
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    duration: float = 0.0
    
    # Results
    passed: bool = False
    failed: bool = False
    skipped: bool = False
    error: bool = False
    
    # Output
    stdout: str = ""
    stderr: str = ""
    traceback: str = ""
    assertion_message: str = ""
    
    # Metrics
    assertions: int = 0
    coverage: float = 0.0  # 0.0-1.0
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    
    # Environment
    python_version: str = ""
    platform: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "result_id": self.result_id,
            "test_id": self.test_id,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "error": self.error,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "traceback": self.traceback,
            "assertion_message": self.assertion_message,
            "assertions": self.assertions,
            "coverage": self.coverage,
            "performance_metrics": self.performance_metrics,
            "python_version": self.python_version,
            "platform": self.platform,
        }


@dataclass
class TestSuite:
    """Collection of test cases."""
    suite_id: str = field(default_factory=lambda: f"suite-{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    
    # Suite classification
    test_type: TestType = TestType.UNIT
    tags: Set[str] = field(default_factory=set)
    
    # Test cases
    test_cases: List[TestCase] = field(default_factory=list)
    
    # Suite configuration
    parallel: bool = False
    max_workers: int = 4
    timeout: float = 300.0
    
    # Dependencies
    dependencies: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "description": self.description,
            "test_type": self.test_type.value,
            "tags": list(self.tags),
            "test_cases": [tc.to_dict() for tc in self.test_cases],
            "parallel": self.parallel,
            "max_workers": self.max_workers,
            "timeout": self.timeout,
            "dependencies": self.dependencies,
        }


@dataclass
class TestReport:
    """Comprehensive test report."""
    report_id: str = field(default_factory=lambda: f"report-{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    
    # Execution summary
    started_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    total_duration: float = 0.0
    
    # Test statistics
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    error_tests: int = 0
    
    # Coverage
    line_coverage: float = 0.0
    branch_coverage: float = 0.0
    function_coverage: float = 0.0
    
    # Performance
    slowest_tests: List[Dict[str, Any]] = field(default_factory=list)
    performance_summary: Dict[str, float] = field(default_factory=dict)
    
    # Results
    test_results: List[TestResult] = field(default_factory=list)
    suite_results: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    
    # Environment
    environment: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "report_id": self.report_id,
            "name": self.name,
            "description": self.description,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_duration": self.total_duration,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "skipped_tests": self.skipped_tests,
            "error_tests": self.error_tests,
            "line_coverage": self.line_coverage,
            "branch_coverage": self.branch_coverage,
            "function_coverage": self.function_coverage,
            "slowest_tests": self.slowest_tests,
            "performance_summary": self.performance_summary,
            "test_results": [tr.to_dict() for tr in self.test_results],
            "suite_results": self.suite_results,
            "environment": self.environment,
        }


class TestDiscovery:
    """Automated test discovery system."""
    
    def __init__(self):
        self.discovered_tests: List[TestCase] = []
        self.test_suites: Dict[str, TestSuite] = {}
        
    def discover_tests(self, test_paths: List[str]) -> List[TestCase]:
        """Discover tests from given paths."""
        discovered_tests = []
        
        for test_path in test_paths:
            path = Path(test_path)
            if path.is_file() and path.suffix == '.py':
                tests = self._discover_tests_from_file(path)
                discovered_tests.extend(tests)
            elif path.is_dir():
                tests = self._discover_tests_from_directory(path)
                discovered_tests.extend(tests)
                
        self.discovered_tests = discovered_tests
        return discovered_tests
        
    def _discover_tests_from_file(self, file_path: Path) -> List[TestCase]:
        """Discover tests from a Python file."""
        tests = []
        
        try:
            # Import the module
            spec = importlib.util.spec_from_file_location(file_path.stem, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Find test functions and classes
            for name, obj in inspect.getmembers(module):
                if inspect.isclass(obj) and name.startswith('Test'):
                    # Test class - find test methods
                    class_tests = self._discover_tests_from_class(obj, str(file_path))
                    tests.extend(class_tests)
                elif inspect.isfunction(obj) and name.startswith('test_'):
                    # Test function
                    test_case = self._create_test_case_from_function(obj, str(file_path))
                    tests.append(test_case)
                    
        except Exception as exc:
            logger.error("Failed to discover tests in %s: %s", file_path, exc)
            
        return tests
        
    def _discover_tests_from_directory(self, dir_path: Path) -> List[TestCase]:
        """Discover tests from a directory."""
        tests = []
        
        # Find all Python files
        for file_path in dir_path.rglob("*.py"):
            if file_path.name.startswith("test_") or file_path.name.endswith("_test.py"):
                file_tests = self._discover_tests_from_file(file_path)
                tests.extend(file_tests)
                
        return tests
        
    def _discover_tests_from_class(self, test_class: type, file_path: str) -> List[TestCase]:
        """Discover tests from a test class."""
        tests = []
        
        for name, method in inspect.getmembers(test_class):
            if inspect.isfunction(method) and name.startswith('test_'):
                test_case = self._create_test_case_from_method(method, test_class, file_path)
                tests.append(test_case)
                
        return tests
        
    def _create_test_case_from_function(self, test_func: Callable, file_path: str) -> TestCase:
        """Create test case from function."""
        return TestCase(
            name=test_func.__name__,
            description=test_func.__doc__ or "",
            test_type=self._infer_test_type(test_func),
            priority=self._infer_priority(test_func),
            module=test_func.__module__,
            function_name=test_func.__name__,
            file_path=file_path,
            line_number=inspect.getsourcelines(test_func)[1],
            test_function=test_func,
            tags=self._extract_tags(test_func),
            timeout=self._extract_timeout(test_func),
            flaky=self._is_flaky(test_func),
        )
        
    def _create_test_case_from_method(self, test_method: Callable, test_class: type, file_path: str) -> TestCase:
        """Create test case from class method."""
        return TestCase(
            name=f"{test_class.__name__}.{test_method.__name__}",
            description=test_method.__doc__ or "",
            test_type=self._infer_test_type(test_method),
            priority=self._infer_priority(test_method),
            module=test_method.__module__,
            class_name=test_class.__name__,
            function_name=test_method.__name__,
            file_path=file_path,
            line_number=inspect.getsourcelines(test_method)[1],
            test_function=test_method,
            tags=self._extract_tags(test_method),
            timeout=self._extract_timeout(test_method),
            flaky=self._is_flaky(test_method),
        )
        
    def _infer_test_type(self, func: Callable) -> TestType:
        """Infer test type from function name and attributes."""
        name = func.__name__.lower()
        
        if 'integration' in name:
            return TestType.INTEGRATION
        elif 'performance' in name or 'perf' in name:
            return TestType.PERFORMANCE
        elif 'security' in name or 'sec' in name:
            return TestType.SECURITY
        elif 'api' in name:
            return TestType.API
        elif 'load' in name:
            return TestType.LOAD
        elif 'stress' in name:
            return TestType.STRESS
        elif 'e2e' in name or 'end_to_end' in name:
            return TestType.END_TO_END
        else:
            return TestType.UNIT
            
    def _infer_priority(self, func: Callable) -> Priority:
        """Infer test priority from function attributes."""
        if hasattr(func, 'priority'):
            return Priority(func.priority)
        elif 'critical' in func.__name__.lower():
            return Priority.CRITICAL
        elif 'important' in func.__name__.lower():
            return Priority.HIGH
        else:
            return Priority.MEDIUM
            
    def _extract_tags(self, func: Callable) -> Set[str]:
        """Extract tags from function attributes."""
        tags = set()
        
        if hasattr(func, 'tags'):
            tags.update(func.tags)
            
        # Extract from name
        name_parts = func.__name__.split('_')
        tags.update(name_parts)
        
        return tags
        
    def _extract_timeout(self, func: Callable) -> float:
        """Extract timeout from function attributes."""
        return getattr(func, 'timeout', 30.0)
        
    def _is_flaky(self, func: Callable) -> bool:
        """Check if test is marked as flaky."""
        return getattr(func, 'flaky', False)
        
    def create_test_suites(self) -> Dict[str, TestSuite]:
        """Create test suites from discovered tests."""
        suites = {}
        
        # Group by test type
        for test_type in TestType:
            type_tests = [t for t in self.discovered_tests if t.test_type == test_type]
            if type_tests:
                suite = TestSuite(
                    name=f"{test_type.value.title()} Tests",
                    description=f"All {test_type.value} tests",
                    test_type=test_type,
                    test_cases=type_tests,
                    parallel=test_type in [TestType.UNIT, TestType.INTEGRATION],
                )
                suites[suite.suite_id] = suite
                
        # Group by module
        module_groups = {}
        for test in self.discovered_tests:
            if test.module not in module_groups:
                module_groups[test.module] = []
            module_groups[test.module].append(test)
            
        for module, tests in module_groups.items():
            suite = TestSuite(
                name=f"{module} Tests",
                description=f"Tests for {module}",
                test_type=TestType.UNIT,
                test_cases=tests,
                parallel=True,
            )
            suites[suite.suite_id] = suite
            
        self.test_suites = suites
        return suites


class TestExecutor:
    """Test execution engine."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Execution state
        self.current_results: List[TestResult] = []
        self.execution_stats: Dict[str, Any] = {}
        
        # Fixtures
        self.fixtures: Dict[str, Any] = {}
        
    async def initialize(self) -> None:
        """Initialize test executor."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Setup common fixtures
        await self._setup_fixtures()
        
        logger.info("TestExecutor initialized")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def _setup_fixtures(self) -> None:
        """Setup common test fixtures."""
        self.fixtures = {
            "redis_client": self._redis,
            "test_data": {},
            "mock_services": {},
        }
        
    async def execute_test(self, test_case: TestCase) -> TestResult:
        """Execute a single test case."""
        result = TestResult(test_id=test_case.test_id)
        result.status = TestStatus.RUNNING
        
        try:
            # Setup
            if test_case.setup_function:
                await self._run_setup(test_case.setup_function)
                
            # Execute test
            start_time = time.time()
            
            if asyncio.iscoroutinefunction(test_case.test_function):
                await self._execute_async_test(test_case, result)
            else:
                await self._execute_sync_test(test_case, result)
                
            result.duration = time.time() - start_time
            result.status = TestStatus.PASSED
            result.passed = True
            
        except AssertionError as exc:
            result.status = TestStatus.FAILED
            result.failed = True
            result.assertion_message = str(exc)
            result.traceback = traceback.format_exc()
            
        except Exception as exc:
            result.status = TestStatus.ERROR
            result.error = True
            result.traceback = traceback.format_exc()
            
        finally:
            # Teardown
            if test_case.teardown_function:
                await self._run_teardown(test_case.teardown_function)
                
            result.completed_at = time.time()
            self.current_results.append(result)
            
        return result
        
    async def _run_setup(self, setup_func: Callable) -> None:
        """Run setup function."""
        if asyncio.iscoroutinefunction(setup_func):
            await setup_func(**self.fixtures)
        else:
            setup_func(**self.fixtures)
            
    async def _run_teardown(self, teardown_func: Callable) -> None:
        """Run teardown function."""
        if asyncio.iscoroutinefunction(teardown_func):
            await teardown_func(**self.fixtures)
        else:
            teardown_func(**self.fixtures)
            
    async def _execute_async_test(self, test_case: TestCase, result: TestResult) -> None:
        """Execute async test function."""
        # Prepare fixtures
        fixtures = {}
        for fixture_name in test_case.fixtures:
            if fixture_name in self.fixtures:
                fixtures[fixture_name] = self.fixtures[fixture_name]
                
        # Execute with timeout
        try:
            await asyncio.wait_for(
                test_case.test_function(**fixtures),
                timeout=test_case.timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"Test timed out after {test_case.timeout} seconds")
            
    async def _execute_sync_test(self, test_case: TestCase, result: TestResult) -> None:
        """Execute sync test function."""
        # Prepare fixtures
        fixtures = {}
        for fixture_name in test_case.fixtures:
            if fixture_name in self.fixtures:
                fixtures[fixture_name] = self.fixtures[fixture_name]
                
        # Execute in thread pool
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, lambda: test_case.test_function(**fixtures)),
                timeout=test_case.timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"Test timed out after {test_case.timeout} seconds")
            
    async def execute_suite(self, test_suite: TestSuite) -> Dict[str, Any]:
        """Execute a test suite."""
        suite_results = {
            "suite_id": test_suite.suite_id,
            "suite_name": test_suite.name,
            "started_at": time.time(),
            "test_results": [],
            "summary": {}
        }
        
        if test_suite.parallel:
            # Execute tests in parallel
            semaphore = asyncio.Semaphore(test_suite.max_workers)
            tasks = []
            
            for test_case in test_suite.test_cases:
                task = self._execute_with_semaphore(semaphore, test_case)
                tasks.append(task)
                
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    # Handle exception
                    error_result = TestResult(
                        test_id="error",
                        status=TestStatus.ERROR,
                        error=True,
                        traceback=str(result)
                    )
                    suite_results["test_results"].append(error_result)
                else:
                    suite_results["test_results"].append(result)
        else:
            # Execute tests sequentially
            for test_case in test_suite.test_cases:
                try:
                    result = await self.execute_test(test_case)
                    suite_results["test_results"].append(result)
                except Exception as exc:
                    logger.error("Test execution error: %s", exc)
                    
        # Calculate summary
        suite_results["completed_at"] = time.time()
        suite_results["duration"] = suite_results["completed_at"] - suite_results["started_at"]
        suite_results["summary"] = self._calculate_suite_summary(suite_results["test_results"])
        
        return suite_results
        
    async def _execute_with_semaphore(self, semaphore: asyncio.Semaphore, test_case: TestCase) -> TestResult:
        """Execute test with semaphore limiting."""
        async with semaphore:
            return await self.execute_test(test_case)
            
    def _calculate_suite_summary(self, test_results: List[TestResult]) -> Dict[str, Any]:
        """Calculate suite summary statistics."""
        total = len(test_results)
        passed = len([r for r in test_results if r.passed])
        failed = len([r for r in test_results if r.failed])
        skipped = len([r for r in test_results if r.skipped])
        error = len([r for r in test_results if r.error])
        
        total_duration = sum(r.duration for r in test_results)
        avg_duration = total_duration / total if total > 0 else 0
        
        return {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "error": error,
            "success_rate": passed / total if total > 0 else 0,
            "total_duration": total_duration,
            "average_duration": avg_duration,
        }


class TestReporter:
    """Test reporting and analysis."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        
        # Report storage
        self.reports: List[TestReport] = {}
        
    async def initialize(self) -> None:
        """Initialize test reporter."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        logger.info("TestReporter initialized")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.close()
            
    async def generate_report(self, suite_results: List[Dict[str, Any]], name: str = "") -> TestReport:
        """Generate comprehensive test report."""
        report = TestReport(
            name=name or f"Test Report {datetime.now().isoformat()}",
            description="Automated test execution report",
        )
        
        # Aggregate all test results
        all_results = []
        for suite_result in suite_results:
            all_results.extend(suite_result["test_results"])
            report.suite_results[suite_result["suite_id"]] = suite_result["summary"]
            
        report.test_results = all_results
        
        # Calculate summary statistics
        report.total_tests = len(all_results)
        report.passed_tests = len([r for r in all_results if r.passed])
        report.failed_tests = len([r for r in all_results if r.failed])
        report.skipped_tests = len([r for r in all_results if r.skipped])
        report.error_tests = len([r for r in all_results if r.error])
        
        # Calculate duration
        if suite_results:
            report.started_at = min(sr["started_at"] for sr in suite_results)
            report.completed_at = max(sr["completed_at"] for sr in suite_results)
            report.total_duration = report.completed_at - report.started_at
            
        # Find slowest tests
        report.slowest_tests = [
            {
                "test_id": r.test_id,
                "duration": r.duration,
                "name": r.test_id
            }
            for r in sorted(all_results, key=lambda x: x.duration, reverse=True)[:10]
        ]
        
        # Performance summary
        if all_results:
            durations = [r.duration for r in all_results]
            report.performance_summary = {
                "min_duration": min(durations),
                "max_duration": max(durations),
                "avg_duration": sum(durations) / len(durations),
                "median_duration": sorted(durations)[len(durations) // 2],
            }
            
        # Environment info
        report.environment = {
            "python_version": sys.version,
            "platform": sys.platform,
            "timestamp": datetime.now().isoformat(),
        }
        
        # Store report
        self.reports[report.report_id] = report
        
        # Store in Redis
        if self._redis:
            key = f"test_reports:{report.report_id}"
            await self._redis.setex(key, 86400 * 7, json.dumps(report.to_dict()))  # 7 days
            
        return report
        
    async def generate_html_report(self, report: TestReport) -> str:
        """Generate HTML test report."""
        html_template = """
<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background: #f0f0f0; padding: 20px; border-radius: 5px; }
        .summary { display: flex; gap: 20px; margin: 20px 0; }
        .metric { background: #e8f4fd; padding: 15px; border-radius: 5px; text-align: center; }
        .passed { background: #d4edda; }
        .failed { background: #f8d7da; }
        .error { background: #fff3cd; }
        .skipped { background: #e2e3e5; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background: #f2f2f2; }
        .slow { color: #d9534f; }
    </style>
</head>
<body>
    <div class="header">
        <h1>{title}</h1>
        <p>{description}</p>
        <p>Generated: {timestamp}</p>
    </div>
    
    <div class="summary">
        <div class="metric">
            <h3>{total_tests}</h3>
            <p>Total Tests</p>
        </div>
        <div class="metric passed">
            <h3>{passed_tests}</h3>
            <p>Passed</p>
        </div>
        <div class="metric failed">
            <h3>{failed_tests}</h3>
            <p>Failed</p>
        </div>
        <div class="metric error">
            <h3>{error_tests}</h3>
            <p>Errors</p>
        </div>
        <div class="metric skipped">
            <h3>{skipped_tests}</h3>
            <p>Skipped</p>
        </div>
    </div>
    
    <h2>Test Results</h2>
    <table>
        <tr>
            <th>Test ID</th>
            <th>Status</th>
            <th>Duration</th>
            <th>Assertions</th>
            <th>Coverage</th>
        </tr>
        {test_rows}
    </table>
    
    <h2>Slowest Tests</h2>
    <table>
        <tr>
            <th>Test</th>
            <th>Duration</th>
        </tr>
        {slowest_rows}
    </table>
</body>
</html>
        """
        
        # Generate test rows
        test_rows = ""
        for result in report.test_results:
            status_class = result.status.value
            test_rows += f"""
            <tr>
                <td>{result.test_id}</td>
                <td class="{status_class}">{result.status.value}</td>
                <td>{result.duration:.3f}s</td>
                <td>{result.assertions}</td>
                <td>{result.coverage:.1%}</td>
            </tr>
            """
            
        # Generate slowest rows
        slowest_rows = ""
        for slow_test in report.slowest_tests:
            slowest_rows += f"""
            <tr>
                <td>{slow_test['name']}</td>
                <td class="slow">{slow_test['duration']:.3f}s</td>
            </tr>
            """
            
        return html_template.format(
            title=report.name,
            description=report.description,
            timestamp=datetime.now().isoformat(),
            total_tests=report.total_tests,
            passed_tests=report.passed_tests,
            failed_tests=report.failed_tests,
            error_tests=report.error_tests,
            skipped_tests=report.skipped_tests,
            test_rows=test_rows,
            slowest_rows=slowest_rows,
        )
        
    async def generate_junit_xml(self, report: TestReport) -> str:
        """Generate JUnit XML report."""
        xml_template = """<?xml version="1.0" encoding="UTF-8"?>
<testsuites>
    <testsuite name="{name}" tests="{total_tests}" failures="{failed_tests}" errors="{error_tests}" skipped="{skipped_tests}" time="{total_duration}">
{test_cases}
    </testsuite>
</testsuites>"""
        
        test_cases = ""
        for result in report.test_results:
            status = "passed"
            message = ""
            if result.failed:
                status = "failed"
                message = result.assertion_message
            elif result.error:
                status = "error"
                message = result.traceback
            elif result.skipped:
                status = "skipped"
                
            test_cases += f"""
        <testcase name="{result.test_id}" classname="{result.test_id}" time="{result.duration}">
            <{status} message="{message}"></{status}>
        </testcase>"""
            
        return xml_template.format(
            name=report.name,
            total_tests=report.total_tests,
            failed_tests=report.failed_tests,
            error_tests=report.error_tests,
            skipped_tests=report.skipped_tests,
            total_duration=report.total_duration,
            test_cases=test_cases,
        )


class TestingFramework:
    """Comprehensive testing framework."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        
        # Components
        self.discovery = TestDiscovery()
        self.executor = TestExecutor(redis_url)
        self.reporter = TestReporter(redis_url)
        
        # Configuration
        self.test_paths: List[str] = []
        self.test_patterns: List[str] = []
        self.exclude_patterns: List[str] = []
        
    async def initialize(self) -> None:
        """Initialize testing framework."""
        await self.executor.initialize()
        await self.reporter.initialize()
        
        logger.info("TestingFramework initialized")
        
    async def shutdown(self) -> None:
        """Shutdown testing framework."""
        await self.executor.disconnect()
        await self.reporter.disconnect()
        
        logger.info("TestingFramework shutdown")
        
    async def run_tests(
        self,
        test_paths: Optional[List[str]] = None,
        test_types: Optional[List[TestType]] = None,
        tags: Optional[List[str]] = None,
        parallel: bool = True
    ) -> TestReport:
        """Run tests with specified filters."""
        # Discover tests
        paths = test_paths or self.test_paths or ["tests/"]
        discovered_tests = self.discovery.discover_tests(paths)
        
        # Create test suites
        test_suites = self.discovery.create_test_suites()
        
        # Filter suites
        filtered_suites = []
        for suite in test_suites.values():
            if test_types and suite.test_type not in test_types:
                continue
            if tags and not tags.intersection(suite.tags):
                continue
                
            filtered_suites.append(suite)
            
        # Execute suites
        suite_results = []
        for suite in filtered_suites:
            if parallel:
                suite.parallel = True
            result = await self.executor.execute_suite(suite)
            suite_results.append(result)
            
        # Generate report
        report = await self.reporter.generate_report(
            suite_results,
            f"Test Run {datetime.now().isoformat()}"
        )
        
        return report
        
    async def run_performance_tests(self) -> TestReport:
        """Run performance tests specifically."""
        return await self.run_tests(
            test_types=[TestType.PERFORMANCE, TestType.LOAD, TestType.STRESS]
        )
        
    async def run_security_tests(self) -> TestReport:
        """Run security tests specifically."""
        return await self.run_tests(test_types=[TestType.SECURITY])
        
    async def run_integration_tests(self) -> TestReport:
        """Run integration tests specifically."""
        return await self.run_tests(test_types=[TestType.INTEGRATION])
        
    def get_framework_stats(self) -> Dict[str, Any]:
        """Get framework statistics."""
        return {
            "discovered_tests": len(self.discovery.discovered_tests),
            "test_suites": len(self.discovery.test_suites),
            "current_results": len(self.executor.current_results),
            "generated_reports": len(self.reporter.reports),
        }


# Global testing framework instance
testing_framework: Optional[TestingFramework] = None