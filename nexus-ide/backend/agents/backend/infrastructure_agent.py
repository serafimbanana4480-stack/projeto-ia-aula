"""InfrastructureAgent — deployment, monitoring, and scaling specialist."""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from backend.agents.base import AgentBase, AgentRequest

logger = logging.getLogger(__name__)


@dataclass
class DeploymentStack:
    """Structured deployment stack recommendation."""

    platform: str
    containerization: str
    orchestration: str
    ci_cd: str
    monitoring: str
    scaling: str
    notes: list[str] = field(default_factory=list)


class InfrastructureAgent(AgentBase):
    """Specialist agent for deployment, monitoring, and scaling infrastructure."""

    name = "INFRASTRUCTURE"
    model_key = "coder"
    prompt_file = "infrastructure_system"
    supported_actions = set()

    def __init__(self) -> None:
        super().__init__()
        self._stats: dict[str, int] = {
            "deployment_requests": 0,
            "monitoring_requests": 0,
            "scaling_requests": 0,
        }

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Handle infrastructure queries: deployment, monitoring, scaling."""
        yield f"<event>infrastructure_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if any(k in query for k in ["deploy", "release", "pipeline", "docker", "kubernetes", "k8s"]):
            self._stats["deployment_requests"] += 1
            yield "## Deployment Strategy\n\n"
            yield self._deployment_best_practices()
        elif any(k in query for k in ["monitor", "observability", "metrics", "alert", "log", "trace"]):
            self._stats["monitoring_requests"] += 1
            yield "## Monitoring & Observability\n\n"
            yield self._monitoring_stack_guide()
        elif any(k in query for k in ["scale", "scaling", "autoscale", "load", "traffic", "horizontal", "vertical"]):
            self._stats["scaling_requests"] += 1
            yield "## Scaling Recommendations\n\n"
            yield self._scaling_strategies()
        else:
            yield "Infrastructure Agent ready. Ask for:\n"
            yield "- Deployment strategies (Docker, K8s)\n"
            yield "- Monitoring and observability setup\n"
            yield "- Scaling and autoscaling guidance\n"

        yield "<event>infrastructure_end</event>"

    def _deployment_best_practices(self) -> str:
        """Return deployment best practices."""
        return (
            "### Containerization\n"
            "- Use multi-stage Docker builds to minimize image size\n"
            "- Pin base image tags; avoid `latest` in production\n"
            "- Run containers as non-root user\n\n"
            "### CI/CD Pipeline\n"
            "- Lint → Test → Build → Scan → Deploy\n"
            "- Gate production deploys on test + security scan success\n"
            "- Use blue/green or canary deployments for zero downtime\n\n"
            "### Secrets Management\n"
            "- Inject secrets at runtime (env vars, secret stores)\n"
            "- Never commit credentials to version control\n"
            "- Rotate secrets regularly and audit access\n"
        )

    def _monitoring_stack_guide(self) -> str:
        """Return monitoring and observability guidelines."""
        return (
            "### Metrics (The Three Pillars)\n"
            "- Prometheus + Grafana for time-series metrics\n"
            "- Structured logging (JSON) aggregated to Loki/ELK\n"
            "- Distributed tracing with Jaeger or Tempo\n\n"
            "### Alerts\n"
            "- Define SLOs and error budgets\n"
            "- Page on symptoms (latency, errors), not causes (disk full)\n"
            "- Use on-call rotations with escalation policies\n\n"
            "### Dashboards\n"
            "- RED method: Rate, Errors, Duration per service\n"
            "- USE method: Utilization, Saturation, Errors per resource\n"
            "- Keep a high-level executive dashboard and detailed runbooks\n"
        )

    def _scaling_strategies(self) -> str:
        """Return scaling strategy recommendations."""
        return (
            "### Horizontal Scaling\n"
            "- Scale number of instances behind a load balancer\n"
            "- Stateless services scale best; externalize sessions/cache\n"
            "- Use HPA (Kubernetes) or ASG (AWS) with CPU/memory metrics\n\n"
            "### Vertical Scaling\n"
            "- Increase CPU/memory per instance\n"
            "- Effective for databases and memory-bound workloads\n"
            "- Has limits; often more expensive per unit of capacity\n\n"
            "### Database Scaling\n"
            "- Read replicas for read-heavy workloads\n"
            "- Connection pooling (PgBouncer) to protect the primary\n"
            "- Sharding for write-heavy or tenant-isolated data\n"
        )

    def suggest_deployment_stack(self) -> DeploymentStack:
        """Suggest a production-ready deployment stack.

        Returns:
            Structured deployment stack recommendation.
        """
        stack = DeploymentStack(
            platform="AWS / GCP / Azure",
            containerization="Docker + BuildKit",
            orchestration="Kubernetes (EKS / GKE / AKS)",
            ci_cd="GitHub Actions → ArgoCD",
            monitoring="Prometheus + Grafana + Loki + Jaeger",
            scaling="HPA + Cluster Autoscaler + Karpenter",
            notes=[
                "Use Terraform or Pulumi for infrastructure as code.",
                "Adopt a service mesh (Istio/Linkerd) for advanced traffic management.",
                "Evaluate serverless (Lambda/Cloud Run) for event-driven workloads.",
            ],
        )
        logger.info("Deployment stack suggested: platform=%s", stack.platform)
        return stack

    def stats(self) -> dict[str, Any]:
        """Return agent usage statistics."""
        return {
            "agent": self.name,
            **self._stats,
            "total_requests": sum(self._stats.values()),
        }
