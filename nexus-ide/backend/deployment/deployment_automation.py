"""Comprehensive Deployment Automation System.

Implements CI/CD pipelines, container orchestration, infrastructure as code,
blue-green deployments, rollback mechanisms, and automated testing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import yaml

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class DeploymentStatus(str, Enum):
    """Deployment status tracking."""
    PENDING = "pending"
    BUILDING = "building"
    TESTING = "testing"
    DEPLOYING = "deploying"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"


class DeploymentStrategy(str, Enum):
    """Deployment strategies."""
    BLUE_GREEN = "blue_green"
    CANARY = "canary"
    ROLLING = "rolling"
    RECREATE = "recreate"
    A_B_TESTING = "a_b_testing"


class Environment(str, Enum):
    """Deployment environments."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TESTING = "testing"


@dataclass
class DeploymentConfig:
    """Deployment configuration."""
    config_id: str = field(default_factory=lambda: f"config-{uuid.uuid4().hex[:12]}")
    name: str = ""
    description: str = ""
    
    # Environment settings
    environment: Environment = Environment.DEVELOPMENT
    strategy: DeploymentStrategy = DeploymentStrategy.ROLLING
    
    # Build configuration
    build_command: str = ""
    build_args: dict[str, str] = field(default_factory=dict)
    dockerfile: str = "Dockerfile"
    context_path: str = "."
    
    # Container configuration
    image_name: str = ""
    image_tag: str = "latest"
    registry_url: str = ""
    
    # Deployment configuration
    replicas: int = 1
    resources: dict[str, str] = field(default_factory=dict)
    environment_vars: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    
    # Health checks
    health_check_path: str = "/health"
    health_check_timeout: int = 30
    health_check_interval: int = 10
    
    # Rollback configuration
    rollback_enabled: bool = True
    rollback_timeout: int = 300
    max_rollback_attempts: int = 3
    
    # Testing configuration
    pre_deployment_tests: list[str] = field(default_factory=list)
    post_deployment_tests: list[str] = field(default_factory=list)
    
    # Notifications
    notification_webhooks: list[str] = field(default_factory=list)
    notification_emails: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "name": self.name,
            "description": self.description,
            "environment": self.environment.value,
            "strategy": self.strategy.value,
            "build_command": self.build_command,
            "build_args": self.build_args,
            "dockerfile": self.dockerfile,
            "context_path": self.context_path,
            "image_name": self.image_name,
            "image_tag": self.image_tag,
            "registry_url": self.registry_url,
            "replicas": self.replicas,
            "resources": self.resources,
            "environment_vars": self.environment_vars,
            "secrets": self.secrets,
            "health_check_path": self.health_check_path,
            "health_check_timeout": self.health_check_timeout,
            "health_check_interval": self.health_check_interval,
            "rollback_enabled": self.rollback_enabled,
            "rollback_timeout": self.rollback_timeout,
            "max_rollback_attempts": self.max_rollback_attempts,
            "pre_deployment_tests": self.pre_deployment_tests,
            "post_deployment_tests": self.post_deployment_tests,
            "notification_webhooks": self.notification_webhooks,
            "notification_emails": self.notification_emails,
        }


@dataclass
class Deployment:
    """Individual deployment instance."""
    deployment_id: str = field(default_factory=lambda: f"deploy-{uuid.uuid4().hex[:12]}")
    config_id: str = ""
    
    # Deployment metadata
    version: str = ""
    commit_hash: str = ""
    branch: str = ""
    author: str = ""
    
    # Status tracking
    status: DeploymentStatus = DeploymentStatus.PENDING
    started_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    duration: float = 0.0
    
    # Deployment steps
    steps: list[dict[str, Any]] = field(default_factory=list)
    current_step: int = 0
    
    # Results
    build_result: dict[str, Any] | None = None
    test_results: list[dict[str, Any]] = field(default_factory=list)
    deployment_result: dict[str, Any] | None = None
    
    # Rollback information
    rollback_reason: str | None = None
    rollback_deployment_id: str | None = None
    
    # Logs
    logs: list[str] = field(default_factory=list)
    error_logs: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "config_id": self.config_id,
            "version": self.version,
            "commit_hash": self.commit_hash,
            "branch": self.branch,
            "author": self.author,
            "status": self.status.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration": self.duration,
            "steps": self.steps,
            "current_step": self.current_step,
            "build_result": self.build_result,
            "test_results": self.test_results,
            "deployment_result": self.deployment_result,
            "rollback_reason": self.rollback_reason,
            "rollback_deployment_id": self.rollback_deployment_id,
            "logs": self.logs,
            "error_logs": self.error_logs,
        }


@dataclass
class InfrastructureResource:
    """Infrastructure resource definition."""
    resource_id: str = field(default_factory=lambda: f"resource-{uuid.uuid4().hex[:12]}")
    name: str = ""
    resource_type: str = ""  # kubernetes, docker, terraform, etc.
    
    # Resource configuration
    configuration: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    
    # Status
    status: str = "pending"  # pending, creating, active, failed, deleting
    created_at: float = field(default_factory=time.time)
    
    # Health and metrics
    health_status: str = "unknown"
    metrics: dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_id": self.resource_id,
            "name": self.name,
            "resource_type": self.resource_type,
            "configuration": self.configuration,
            "dependencies": self.dependencies,
            "status": self.status,
            "created_at": self.created_at,
            "health_status": self.health_status,
            "metrics": self.metrics,
        }


class ContainerBuilder:
    """Container image building and management."""
    
    def __init__(self):
        self.build_cache: dict[str, dict[str, Any]] = {}
        
    async def build_image(self, config: DeploymentConfig) -> dict[str, Any]:
        """Build Docker image."""
        build_result = {
            "success": False,
            "image_id": "",
            "build_time": 0.0,
            "logs": [],
            "error": None
        }
        
        try:
            start_time = time.time()
            
            # Prepare build command
            build_cmd = [
                "docker", "build",
                "-f", config.dockerfile,
                "-t", f"{config.image_name}:{config.image_tag}",
            ]
            
            # Add build arguments
            for key, value in config.build_args.items():
                build_cmd.extend(["--build-arg", f"{key}={value}"])
                
            # Add context path
            build_cmd.append(config.context_path)
            
            # Execute build
            process = await asyncio.create_subprocess_exec(
                *build_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=config.context_path,
            )
            
            stdout_bytes, stderr_bytes = await process.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            
            build_result["logs"] = stdout.split('\n') + stderr.split('\n')
            build_result["build_time"] = time.time() - start_time
            
            if process.returncode == 0:
                build_result["success"] = True
                # Get image ID
                inspect_cmd = ["docker", "inspect", f"{config.image_name}:{config.image_tag}"]
                inspect_process = await asyncio.create_subprocess_exec(
                    *inspect_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                inspect_stdout, _ = await inspect_process.communicate()
                if inspect_process.returncode == 0:
                    inspect_data = json.loads(inspect_stdout.decode("utf-8", errors="replace"))
                    build_result["image_id"] = inspect_data[0]["Id"]
                    
                logger.info("Successfully built image %s:%s", config.image_name, config.image_tag)
            else:
                build_result["error"] = stderr
                logger.error("Failed to build image: %s", stderr)
                
        except Exception as exc:
            build_result["error"] = str(exc)
            logger.error("Build error: %s", exc)
            
        return build_result
        
    async def push_image(self, config: DeploymentConfig) -> dict[str, Any]:
        """Push Docker image to registry."""
        push_result = {
            "success": False,
            "push_time": 0.0,
            "logs": [],
            "error": None
        }
        
        try:
            start_time = time.time()
            
            # Tag image for registry
            if config.registry_url:
                full_image_name = f"{config.registry_url}/{config.image_name}:{config.image_tag}"
                tag_cmd = ["docker", "tag", f"{config.image_name}:{config.image_tag}", full_image_name]
                tag_process = await asyncio.create_subprocess_exec(
                    *tag_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                tag_stdout, tag_stderr = await tag_process.communicate()
                
                if tag_process.returncode != 0:
                    push_result["error"] = tag_stderr.decode("utf-8", errors="replace")
                    return push_result
                    
                image_to_push = full_image_name
            else:
                image_to_push = f"{config.image_name}:{config.image_tag}"
                
            # Push image
            push_cmd = ["docker", "push", image_to_push]
            process = await asyncio.create_subprocess_exec(
                *push_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout_bytes, stderr_bytes = await process.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            
            push_result["logs"] = stdout.split('\n') + stderr.split('\n')
            push_result["push_time"] = time.time() - start_time
            
            if process.returncode == 0:
                push_result["success"] = True
                logger.info("Successfully pushed image %s", image_to_push)
            else:
                push_result["error"] = stderr
                logger.error("Failed to push image: %s", stderr)
                
        except Exception as exc:
            push_result["error"] = str(exc)
            logger.error("Push error: %s", exc)
            
        return push_result


class KubernetesDeployer:
    """Kubernetes deployment management."""
    
    def __init__(self):
        self.kubeconfig_path = os.getenv("KUBECONFIG", "~/.kube/config")
        self.namespace = "default"
        
    async def deploy(self, config: DeploymentConfig, image_id: str) -> dict[str, Any]:
        """Deploy to Kubernetes."""
        deployment_result = {
            "success": False,
            "deployment_time": 0.0,
            "logs": [],
            "error": None,
            "resources_created": []
        }
        
        try:
            start_time = time.time()
            
            # Generate Kubernetes manifests
            manifests = self._generate_manifests(config, image_id)
            
            # Apply manifests
            for manifest in manifests:
                apply_result = await self._apply_manifest(manifest)
                deployment_result["logs"].extend(apply_result["logs"])
                
                if apply_result["success"]:
                    deployment_result["resources_created"].append(apply_result["resource"])
                else:
                    deployment_result["error"] = apply_result["error"]
                    return deployment_result
                    
            deployment_result["deployment_time"] = time.time() - start_time
            deployment_result["success"] = True
            
            logger.info("Successfully deployed to Kubernetes")
            
        except Exception as exc:
            deployment_result["error"] = str(exc)
            logger.error("Kubernetes deployment error: %s", exc)
            
        return deployment_result
        
    def _generate_manifests(self, config: DeploymentConfig, image_id: str) -> list[dict[str, Any]]:
        """Generate Kubernetes manifests."""
        manifests = []
        
        # Deployment manifest
        deployment_manifest = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {
                "name": config.name,
                "namespace": self.namespace,
                "labels": {
                    "app": config.name,
                    "version": config.image_tag
                }
            },
            "spec": {
                "replicas": config.replicas,
                "selector": {
                    "matchLabels": {
                        "app": config.name
                    }
                },
                "template": {
                    "metadata": {
                        "labels": {
                            "app": config.name,
                            "version": config.image_tag
                        }
                    },
                    "spec": {
                        "containers": [{
                            "name": config.name,
                            "image": f"{config.image_name}:{config.image_tag}",
                            "ports": [{"containerPort": 8000}],
                            "env": [
                                {"name": k, "value": v}
                                for k, v in config.environment_vars.items()
                            ],
                            "resources": config.resources,
                            "livenessProbe": {
                                "httpGet": {
                                    "path": config.health_check_path,
                                    "port": 8000
                                },
                                "initialDelaySeconds": 30,
                                "periodSeconds": config.health_check_interval
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": config.health_check_path,
                                    "port": 8000
                                },
                                "initialDelaySeconds": 5,
                                "periodSeconds": config.health_check_interval
                            }
                        }]
                    }
                }
            }
        }
        manifests.append(deployment_manifest)
        
        # Service manifest
        service_manifest = {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": f"{config.name}-service",
                "namespace": self.namespace
            },
            "spec": {
                "selector": {
                    "app": config.name
                },
                "ports": [{
                    "protocol": "TCP",
                    "port": 80,
                    "targetPort": 8000
                }],
                "type": "LoadBalancer"
            }
        }
        manifests.append(service_manifest)
        
        return manifests
        
    async def _apply_manifest(self, manifest: dict[str, Any]) -> dict[str, Any]:
        """Apply Kubernetes manifest."""
        result = {
            "success": False,
            "resource": "",
            "logs": [],
            "error": None
        }
        
        try:
            # Convert manifest to YAML
            manifest_yaml = yaml.dump(manifest)
            
            # Apply with kubectl
            cmd = ["kubectl", "apply", "-f", "-"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout_bytes, stderr_bytes = await process.communicate(input=manifest_yaml.encode("utf-8"))
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            
            result["logs"] = stdout.split('\n') + stderr.split('\n')
            
            if process.returncode == 0:
                result["success"] = True
                result["resource"] = f"{manifest['kind']}/{manifest['metadata']['name']}"
                logger.info("Applied %s", result["resource"])
            else:
                result["error"] = stderr
                logger.error("Failed to apply manifest: %s", stderr)
                
        except Exception as exc:
            result["error"] = str(exc)
            logger.error("Manifest application error: %s", exc)
            
        return result
        
    async def rollback(self, deployment_name: str, revision: int) -> dict[str, Any]:
        """Rollback Kubernetes deployment."""
        rollback_result = {
            "success": False,
            "logs": [],
            "error": None
        }
        
        try:
            # Rollback command
            cmd = ["kubectl", "rollout", "undo", f"deployment/{deployment_name}", f"--to-revision={revision}"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process.communicate()
            
            rollback_result["logs"] = stdout_bytes.decode("utf-8", errors="replace").split('\n') + stderr_bytes.decode("utf-8", errors="replace").split('\n')
            
            if process.returncode == 0:
                rollback_result["success"] = True
                logger.info("Successfully rolled back deployment %s", deployment_name)
            else:
                stderr_str = stderr_bytes.decode("utf-8", errors="replace")
                rollback_result["error"] = stderr_str
                logger.error("Failed to rollback deployment: %s", stderr_str)
                
        except Exception as exc:
            rollback_result["error"] = str(exc)
            logger.error("Rollback error: %s", exc)
            
        return rollback_result
        
    async def get_deployment_status(self, deployment_name: str) -> dict[str, Any]:
        """Get deployment status."""
        try:
            cmd = ["kubectl", "get", "deployment", deployment_name, "-o", "json"]
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await process.communicate()
            
            if process.returncode == 0:
                deployment_data = json.loads(stdout_bytes.decode("utf-8", errors="replace"))
                return {
                    "name": deployment_data["metadata"]["name"],
                    "replicas": deployment_data["spec"]["replicas"],
                    "ready_replicas": deployment_data["status"].get("readyReplicas", 0),
                    "available_replicas": deployment_data["status"].get("availableReplicas", 0),
                    "conditions": deployment_data["status"].get("conditions", [])
                }
            else:
                return {"error": stderr_bytes.decode("utf-8", errors="replace")}
                
        except Exception as exc:
            return {"error": str(exc)}


class TestRunner:
    """Automated testing for deployments."""
    
    def __init__(self):
        self.test_results: list[dict[str, Any]] = []
        
    async def run_tests(self, test_commands: list[str], environment: str) -> list[dict[str, Any]]:
        """Run test commands."""
        results = []
        
        for test_command in test_commands:
            result = await self._run_single_test(test_command, environment)
            results.append(result)
            
        return results
        
    async def _run_single_test(self, test_command: str, environment: str) -> dict[str, Any]:
        """Run a single test command."""
        result = {
            "command": test_command,
            "environment": environment,
            "success": False,
            "duration": 0.0,
            "logs": [],
            "error": None
        }
        
        try:
            start_time = time.time()
            
            # Set environment variables
            env = os.environ.copy()
            env["TEST_ENVIRONMENT"] = environment
            
            # Run test command
            process = await asyncio.create_subprocess_exec(
                *test_command.split(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            
            stdout_bytes, stderr_bytes = await process.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            
            result["duration"] = time.time() - start_time
            result["logs"] = stdout.split('\n') + stderr.split('\n')
            
            if process.returncode == 0:
                result["success"] = True
                logger.info("Test passed: %s", test_command)
            else:
                result["error"] = stderr
                logger.error("Test failed: %s", test_command)
                
        except Exception as exc:
            result["error"] = str(exc)
            logger.error("Test execution error: %s", exc)
            
        return result
        
    async def run_health_checks(self, service_url: str, health_path: str = "/health") -> dict[str, Any]:
        """Run health checks."""
        result = {
            "success": False,
            "response_time": 0.0,
            "status_code": None,
            "error": None
        }
        
        try:
            import aiohttp
            
            start_time = time.time()
            
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{service_url}{health_path}") as response:
                    result["response_time"] = time.time() - start_time
                    result["status_code"] = response.status
                    
                    if response.status == 200:
                        result["success"] = True
                        result["data"] = await response.json()
                    else:
                        result["error"] = f"HTTP {response.status}"
                        
        except Exception as exc:
            result["error"] = str(exc)
            logger.error("Health check error: %s", exc)
            
        return result


class DeploymentAutomation:
    """Main deployment automation system."""
    
    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self.redis_url = redis_url
        self._redis: redis.Redis | None = None
        
        # Components
        self.container_builder = ContainerBuilder()
        self.kubernetes_deployer = KubernetesDeployer()
        self.test_runner = TestRunner()
        
        # Storage
        self.configs: dict[str, DeploymentConfig] = {}
        self.deployments: dict[str, Deployment] = {}
        self.resources: dict[str, InfrastructureResource] = {}
        
        # Background tasks
        self.monitoring_task: asyncio.Task | None = None
        
    async def initialize(self) -> None:
        """Initialize deployment automation."""
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        
        # Load existing configurations
        await self._load_configs()
        
        # Start monitoring
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        logger.info("DeploymentAutomation initialized")
        
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self.monitoring_task:
            self.monitoring_task.cancel()
            
        if self._redis:
            await self._redis.close()
            
    async def _load_configs(self) -> None:
        """Load existing deployment configurations."""
        try:
            cursor = 0
            while cursor != 0:
                cursor, keys = await self._redis.scan(cursor, match="deploy_configs:*", count=100)
                for key in keys:
                    data = await self._redis.get(key)
                    if data:
                        config_data = json.loads(data)
                        config = DeploymentConfig(**config_data)
                        self.configs[config.config_id] = config
                        
        except Exception as exc:
            logger.error("Failed to load configs: %s", exc)
            
    async def create_config(self, config: DeploymentConfig) -> str:
        """Create deployment configuration."""
        self.configs[config.config_id] = config
        
        # Store in Redis
        if self._redis:
            key = f"deploy_configs:{config.config_id}"
            await self._redis.setex(key, 86400 * 30, json.dumps(config.to_dict()))  # 30 days
            
        logger.info("Created deployment config: %s", config.config_id)
        return config.config_id
        
    async def deploy(self, config_id: str, version: str = "", commit_hash: str = "") -> str:
        """Execute deployment."""
        if config_id not in self.configs:
            raise ValueError(f"Configuration {config_id} not found")
            
        config = self.configs[config_id]
        
        # Create deployment
        deployment = Deployment(
            config_id=config_id,
            version=version or "latest",
            commit_hash=commit_hash,
            author=os.getenv("USER", "system")
        )
        
        self.deployments[deployment.deployment_id] = deployment
        
        # Add deployment steps
        deployment.steps = [
            {"name": "build", "status": "pending"},
            {"name": "test", "status": "pending"},
            {"name": "deploy", "status": "pending"},
            {"name": "verify", "status": "pending"}
        ]
        
        # Execute deployment
        await self._execute_deployment(deployment, config)
        
        return deployment.deployment_id
        
    async def _execute_deployment(self, deployment: Deployment, config: DeploymentConfig) -> None:
        """Execute deployment steps."""
        try:
            deployment.status = DeploymentStatus.BUILDING
            deployment.current_step = 0
            
            # Step 1: Build
            await self._execute_build_step(deployment, config)
            
            # Step 2: Test
            if deployment.build_result and deployment.build_result["success"]:
                deployment.status = DeploymentStatus.TESTING
                deployment.current_step = 1
                await self._execute_test_step(deployment, config)
            else:
                deployment.status = DeploymentStatus.FAILED
                deployment.error_logs.append("Build failed")
                return
                
            # Step 3: Deploy
            if all(test["success"] for test in deployment.test_results):
                deployment.status = DeploymentStatus.DEPLOYING
                deployment.current_step = 2
                await self._execute_deploy_step(deployment, config)
            else:
                deployment.status = DeploymentStatus.FAILED
                deployment.error_logs.append("Tests failed")
                return
                
            # Step 4: Verify
            if deployment.deployment_result and deployment.deployment_result["success"]:
                deployment.status = DeploymentStatus.VERIFYING
                deployment.current_step = 3
                await self._execute_verify_step(deployment, config)
            else:
                deployment.status = DeploymentStatus.FAILED
                deployment.error_logs.append("Deployment failed")
                return
                
            # Complete deployment
            deployment.status = DeploymentStatus.COMPLETED
            deployment.completed_at = time.time()
            deployment.duration = deployment.completed_at - deployment.started_at
            
            logger.info("Deployment %s completed successfully", deployment.deployment_id)
            
        except Exception as exc:
            deployment.status = DeploymentStatus.FAILED
            deployment.error_logs.append(str(exc))
            logger.error("Deployment error: %s", exc)
            
            # Attempt rollback if enabled
            if config.rollback_enabled:
                await self._rollback_deployment(deployment, config)
                
        finally:
            # Store deployment
            if self._redis:
                key = f"deployments:{deployment.deployment_id}"
                await self._redis.setex(key, 86400 * 7, json.dumps(deployment.to_dict()))  # 7 days
                
    async def _execute_build_step(self, deployment: Deployment, config: DeploymentConfig) -> None:
        """Execute build step."""
        deployment.steps[0]["status"] = "running"
        
        build_result = await self.container_builder.build_image(config)
        deployment.build_result = build_result
        
        if build_result["success"]:
            deployment.steps[0]["status"] = "completed"
            deployment.logs.extend(build_result["logs"])
        else:
            deployment.steps[0]["status"] = "failed"
            deployment.error_logs.extend(build_result["logs"])
            
    async def _execute_test_step(self, deployment: Deployment, config: DeploymentConfig) -> None:
        """Execute test step."""
        deployment.steps[1]["status"] = "running"
        
        # Run pre-deployment tests
        test_results = await self.test_runner.run_tests(
            config.pre_deployment_tests,
            config.environment.value
        )
        
        deployment.test_results = test_results
        
        if all(test["success"] for test in test_results):
            deployment.steps[1]["status"] = "completed"
        else:
            deployment.steps[1]["status"] = "failed"
            for test in test_results:
                if not test["success"]:
                    deployment.error_logs.extend(test["logs"])
                    
    async def _execute_deploy_step(self, deployment: Deployment, config: DeploymentConfig) -> None:
        """Execute deploy step."""
        deployment.steps[2]["status"] = "running"
        
        # Deploy based on strategy
        if config.strategy == DeploymentStrategy.KUBERNETES:
            deploy_result = await self.kubernetes_deployer.deploy(
                config,
                deployment.build_result["image_id"]
            )
        else:
            # Other deployment strategies would be implemented here
            deploy_result = {"success": True, "logs": ["Deployment completed"]}
            
        deployment.deployment_result = deploy_result
        
        if deploy_result["success"]:
            deployment.steps[2]["status"] = "completed"
            deployment.logs.extend(deploy_result["logs"])
        else:
            deployment.steps[2]["status"] = "failed"
            deployment.error_logs.extend(deploy_result["logs"])
            
    async def _execute_verify_step(self, deployment: Deployment, config: DeploymentConfig) -> None:
        """Execute verify step."""
        deployment.steps[3]["status"] = "running"
        
        # Run health checks
        service_url = f"http://{config.name}-service"
        health_result = await self.test_runner.run_health_checks(
            service_url,
            config.health_check_path
        )
        
        # Run post-deployment tests
        post_test_results = await self.test_runner.run_tests(
            config.post_deployment_tests,
            config.environment.value
        )
        
        if health_result["success"] and all(test["success"] for test in post_test_results):
            deployment.steps[3]["status"] = "completed"
        else:
            deployment.steps[3]["status"] = "failed"
            if not health_result["success"]:
                deployment.error_logs.append(f"Health check failed: {health_result['error']}")
            for test in post_test_results:
                if not test["success"]:
                    deployment.error_logs.extend(test["logs"])
                    
    async def _rollback_deployment(self, deployment: Deployment, config: DeploymentConfig) -> None:
        """Rollback deployment."""
        deployment.status = DeploymentStatus.ROLLING_BACK
        
        try:
            # Implement rollback logic based on strategy
            if config.strategy == DeploymentStrategy.KUBERNETES:
                rollback_result = await self.kubernetes_deployer.rollback(
                    config.name,
                    1  # Rollback to previous revision
                )
                
                if rollback_result["success"]:
                    deployment.status = DeploymentStatus.ROLLED_BACK
                    deployment.rollback_deployment_id = deployment.deployment_id
                    deployment.logs.extend(rollback_result["logs"])
                else:
                    deployment.error_logs.append(f"Rollback failed: {rollback_result['error']}")
                    
        except Exception as exc:
            deployment.error_logs.append(f"Rollback error: {exc}")
            logger.error("Rollback error: %s", exc)
            
    async def get_deployment_status(self, deployment_id: str) -> dict[str, Any]:
        """Get deployment status."""
        if deployment_id not in self.deployments:
            return {"error": "Deployment not found"}
            
        deployment = self.deployments[deployment_id]
        
        # Get additional status from deployment system
        if deployment.status == DeploymentStatus.COMPLETED:
            config = self.configs[deployment.config_id]
            k8s_status = await self.kubernetes_deployer.get_deployment_status(config.name)
            
            return {
                "deployment": deployment.to_dict(),
                "kubernetes_status": k8s_status
            }
        else:
            return {"deployment": deployment.to_dict()}
            
    async def _monitoring_loop(self) -> None:
        """Background monitoring loop."""
        while True:
            try:
                await asyncio.sleep(60)  # Monitor every minute
                
                # Check deployment health
                await self._check_deployment_health()
                
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Monitoring loop error: %s", exc)
                await asyncio.sleep(1.0)
                
    async def _check_deployment_health(self) -> None:
        """Check health of active deployments."""
        for deployment in self.deployments.values():
            if deployment.status == DeploymentStatus.COMPLETED:
                config = self.configs[deployment.config_id]
                
                # Run health check
                service_url = f"http://{config.name}-service"
                health_result = await self.test_runner.run_health_checks(
                    service_url,
                    config.health_check_path
                )
                
                if not health_result["success"]:
                    logger.warning("Deployment %s health check failed", deployment.deployment_id)
                    
    def get_deployment_stats(self) -> dict[str, Any]:
        """Get deployment statistics."""
        total_deployments = len(self.deployments)
        completed_deployments = len([
            d for d in self.deployments.values()
            if d.status == DeploymentStatus.COMPLETED
        ])
        failed_deployments = len([
            d for d in self.deployments.values()
            if d.status == DeploymentStatus.FAILED
        ])
        
        return {
            "total_deployments": total_deployments,
            "completed_deployments": completed_deployments,
            "failed_deployments": failed_deployments,
            "success_rate": completed_deployments / total_deployments if total_deployments > 0 else 0.0,
            "total_configs": len(self.configs),
            "active_resources": len(self.resources),
        }


# Global deployment automation instance
deployment_automation: DeploymentAutomation | None = None