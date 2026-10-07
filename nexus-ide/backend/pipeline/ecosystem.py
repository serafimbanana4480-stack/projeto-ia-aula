"""Ecosystem — marketplace, voice assistant, digital twin, auto-evolution, webhooks.

Phase 12: Expansao e Ecosistema
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# 12-01: Agent Marketplace
# ============================================================================

class AgentStatus(Enum):
    PENDING = "pending"
    VALIDATED = "validated"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"


@dataclass
class AgentPlugin:
    """A marketplace agent/plugin entry."""

    plugin_id: str
    name: str
    description: str
    version: str
    author: str
    capabilities: list[str] = field(default_factory=list)
    supported_stacks: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    status: AgentStatus = AgentStatus.PENDING
    downloads: int = 0
    rating: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "capabilities": self.capabilities,
            "supported_stacks": self.supported_stacks,
            "tags": self.tags,
            "status": self.status.value,
            "downloads": self.downloads,
            "rating": self.rating,
        }


class AgentMarketplace:
    """Marketplace for discovering and installing agent plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, AgentPlugin] = {}
        self._lock = threading.Lock()

    def submit(self, plugin: AgentPlugin) -> AgentPlugin:
        """Submit a plugin for validation."""
        with self._lock:
            # Auto-validate if it has required fields
            if plugin.name and plugin.description and plugin.capabilities:
                plugin.status = AgentStatus.VALIDATED
            else:
                plugin.status = AgentStatus.REJECTED
            self._plugins[plugin.plugin_id] = plugin
        logger.info("Plugin submitted: %s (status: %s)", plugin.name, plugin.status.value)
        return plugin

    def search(self, query: str = "", tags: list[str] | None = None,
               capability: str | None = None, stack: str | None = None) -> list[AgentPlugin]:
        """Search for plugins matching criteria."""
        results: list[AgentPlugin] = []

        with self._lock:
            for plugin in self._plugins.values():
                if plugin.status != AgentStatus.VALIDATED:
                    continue

                # Text search
                if query:
                    text = f"{plugin.name} {plugin.description} {' '.join(plugin.tags)}".lower()
                    if query.lower() not in text:
                        continue

                # Tag filter
                if tags and not any(t in plugin.tags for t in tags):
                    continue

                # Capability filter
                if capability and capability not in plugin.capabilities:
                    continue

                # Stack filter
                if stack and stack not in plugin.supported_stacks:
                    continue

                results.append(plugin)

        return sorted(results, key=lambda p: (p.rating, p.downloads), reverse=True)

    def get_plugin(self, plugin_id: str) -> AgentPlugin | None:
        return self._plugins.get(plugin_id)

    def install(self, plugin_id: str) -> AgentPlugin | None:
        """Simulate installing a plugin (increments downloads)."""
        with self._lock:
            plugin = self._plugins.get(plugin_id)
            if plugin and plugin.status == AgentStatus.VALIDATED:
                plugin.downloads += 1
                return plugin
        return None

    def rate(self, plugin_id: str, rating: float) -> bool:
        """Rate a plugin (1-5)."""
        if not 1 <= rating <= 5:
            return False
        with self._lock:
            plugin = self._plugins.get(plugin_id)
            if plugin:
                # Simple moving average
                if plugin.rating == 0:
                    plugin.rating = rating
                else:
                    plugin.rating = (plugin.rating * 0.7) + (rating * 0.3)
                return True
        return False

    def list_plugins(self) -> list[AgentPlugin]:
        with self._lock:
            return list(self._plugins.values())

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "total": len(self._plugins),
                "validated": sum(1 for p in self._plugins.values()
                               if p.status == AgentStatus.VALIDATED),
                "pending": sum(1 for p in self._plugins.values()
                             if p.status == AgentStatus.PENDING),
                "total_downloads": sum(p.downloads for p in self._plugins.values()),
            }


# ============================================================================
# 12-02: Voice Assistant & Digital Twin
# ============================================================================

class VoiceAssistant:
    """Voice interface for querying system state.

    Stub implementation — converts text queries to spoken responses.
    In production, would integrate with TTS/STT services.
    """

    def __init__(self) -> None:
        self._conversation_history: list[dict[str, str]] = []
        self._active = False

    def query(self, text: str) -> str:
        """Process a voice/text query about system state.

        Args:
            text: Natural language query.

        Returns:
            Text response that would be spoken.
        """
        text_lower = text.lower()
        self._conversation_history.append({"role": "user", "content": text})

        response = "I'm not sure how to answer that."

        if "status" in text_lower or "state" in text_lower:
            response = "The system is operational. All agents are running normally."
        elif "agent" in text_lower:
            response = "There are multiple agents active, including CODER, DEBUGGER, and ARCHITECT."
        elif "workflow" in text_lower:
            response = "Current workflows are proceeding as scheduled."
        elif "error" in text_lower or "problem" in text_lower:
            response = "No critical errors detected. The system is healthy."
        elif "help" in text_lower:
            response = "I can tell you about system status, agents, workflows, and errors."

        self._conversation_history.append({"role": "assistant", "content": response})
        return response

    def get_history(self) -> list[dict[str, str]]:
        return list(self._conversation_history)

    def clear_history(self) -> None:
        self._conversation_history.clear()


@dataclass
class SimulationScenario:
    """A scenario to simulate in the digital twin."""

    scenario_id: str
    name: str
    description: str
    actions: list[dict[str, Any]]  # List of actions to simulate
    expected_outcome: str = ""
    actual_outcome: str = ""
    passed: bool | None = None
    duration_ms: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class DigitalTwin:
    """Digital twin for simulating scenarios before real execution.

    Allows testing changes in a simulated environment before
    applying them to the real system.
    """

    def __init__(self) -> None:
        self._scenarios: dict[str, SimulationScenario] = {}
        self._lock = threading.Lock()

    def create_scenario(self, name: str, description: str,
                        actions: list[dict[str, Any]]) -> SimulationScenario:
        """Create a new simulation scenario."""
        scenario_id = f"sim-{hashlib.md5(name.encode()).hexdigest()[:8]}"
        scenario = SimulationScenario(
            scenario_id=scenario_id,
            name=name,
            description=description,
            actions=actions,
        )
        with self._lock:
            self._scenarios[scenario_id] = scenario
        return scenario

    def simulate(self, scenario_id: str) -> SimulationScenario | None:
        """Run a simulation and return results."""
        scenario = self._scenarios.get(scenario_id)
        if not scenario:
            return None

        import time
        start = time.time()

        # Simulate each action
        results: list[str] = []
        for action in scenario.actions:
            action_type = action.get("type", "unknown")
            agent_id = action.get("agent_id", "unknown")
            # Simulate success/failure based on action type
            if action_type in ("rm_file", "drop_table", "force_push"):
                results.append(f"BLOCKED: {action_type} by {agent_id}")
            else:
                results.append(f"OK: {action_type} by {agent_id}")

        scenario.duration_ms = (time.time() - start) * 1000
        scenario.actual_outcome = "; ".join(results)

        # Determine if simulation passed (no blocked actions)
        scenario.passed = not any("BLOCKED" in r for r in results)

        logger.info("Simulation %s: %s", scenario_id, "PASSED" if scenario.passed else "FAILED")
        return scenario

    def get_scenario(self, scenario_id: str) -> SimulationScenario | None:
        return self._scenarios.get(scenario_id)

    def list_scenarios(self) -> list[SimulationScenario]:
        return list(self._scenarios.values())

    def compare_scenarios(self, id1: str, id2: str) -> dict[str, Any]:
        """Compare two simulation scenarios."""
        s1 = self._scenarios.get(id1)
        s2 = self._scenarios.get(id2)
        if not s1 or not s2:
            return {}

        return {
            "scenario_1": {"name": s1.name, "passed": s1.passed, "duration_ms": s1.duration_ms},
            "scenario_2": {"name": s2.name, "passed": s2.passed, "duration_ms": s2.duration_ms},
            "duration_diff_ms": s1.duration_ms - s2.duration_ms,
        }


# ============================================================================
# 12-03: Auto-Evolution & Webhooks
# ============================================================================

@dataclass
class EvolutionProposal:
    """A proposal for the system to evolve its own code."""

    proposal_id: str
    target_file: str
    description: str
    proposed_change: str
    rationale: str
    risk_level: str = "low"  # low, medium, high, critical
    status: str = "pending"  # pending, approved, rejected, applied, rolled_back
    approved_by: str = ""
    applied_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class AutoEvolution:
    """Manages self-evolution proposals under supervision.

    The system can propose changes to its own code, but all
    changes require human approval (or GovernanceCouncil at level 3+).
    """

    MAX_PROPOSALS_PER_DAY = 5

    def __init__(self) -> None:
        self._proposals: list[EvolutionProposal] = []
        self._applied: list[EvolutionProposal] = []
        self._lock = threading.Lock()
        self._daily_count = 0
        self._last_reset_day = datetime.now(UTC).strftime("%Y-%m-%d")

    def propose(self, target_file: str, description: str,
                proposed_change: str, rationale: str,
                risk_level: str = "low") -> EvolutionProposal | None:
        """Propose a code change for self-evolution.

        Returns None if daily limit exceeded.
        """
        self._reset_daily_count_if_needed()

        with self._lock:
            if self._daily_count >= self.MAX_PROPOSALS_PER_DAY:
                logger.warning("Daily evolution proposal limit reached")
                return None

            proposal = EvolutionProposal(
                proposal_id=f"evol-{len(self._proposals):04d}",
                target_file=target_file,
                description=description,
                proposed_change=proposed_change,
                rationale=rationale,
                risk_level=risk_level,
            )
            self._proposals.append(proposal)
            self._daily_count += 1
            logger.info("Evolution proposed: %s -> %s", proposal.proposal_id, target_file)
            return proposal

    def approve(self, proposal_id: str, approver: str) -> EvolutionProposal | None:
        """Approve an evolution proposal."""
        with self._lock:
            for p in self._proposals:
                if p.proposal_id == proposal_id and p.status == "pending":
                    p.status = "approved"
                    p.approved_by = approver
                    return p
        return None

    def reject(self, proposal_id: str, approver: str) -> EvolutionProposal | None:
        """Reject an evolution proposal."""
        with self._lock:
            for p in self._proposals:
                if p.proposal_id == proposal_id and p.status == "pending":
                    p.status = "rejected"
                    p.approved_by = approver
                    return p
        return None

    def apply(self, proposal_id: str) -> EvolutionProposal | None:
        """Apply an approved proposal."""
        with self._lock:
            for p in self._proposals:
                if p.proposal_id == proposal_id and p.status == "approved":
                    p.status = "applied"
                    p.applied_at = datetime.now(UTC).isoformat()
                    self._applied.append(p)
                    logger.info("Evolution applied: %s", proposal_id)
                    return p
        return None

    def rollback(self, proposal_id: str) -> EvolutionProposal | None:
        """Rollback an applied proposal."""
        with self._lock:
            for p in self._proposals:
                if p.proposal_id == proposal_id and p.status == "applied":
                    p.status = "rolled_back"
                    logger.info("Evolution rolled back: %s", proposal_id)
                    return p
        return None

    def get_pending(self) -> list[EvolutionProposal]:
        with self._lock:
            return [p for p in self._proposals if p.status == "pending"]

    def get_history(self) -> list[EvolutionProposal]:
        return list(self._proposals)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "total_proposals": len(self._proposals),
                "pending": sum(1 for p in self._proposals if p.status == "pending"),
                "approved": sum(1 for p in self._proposals if p.status == "approved"),
                "applied": sum(1 for p in self._proposals if p.status == "applied"),
                "rejected": sum(1 for p in self._proposals if p.status == "rejected"),
                "rolled_back": sum(1 for p in self._proposals if p.status == "rolled_back"),
                "daily_remaining": max(0, self.MAX_PROPOSALS_PER_DAY - self._daily_count),
            }

    def _reset_daily_count_if_needed(self) -> None:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        if today != self._last_reset_day:
            self._daily_count = 0
            self._last_reset_day = today


@dataclass
class WebhookConfig:
    """Configuration for a webhook endpoint."""

    hook_id: str
    url: str
    events: list[str]  # Events to subscribe to
    secret: str = ""
    active: bool = True
    retry_count: int = 3
    timeout_seconds: int = 10
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "hook_id": self.hook_id,
            "url": self.url,
            "events": self.events,
            "active": self.active,
            "retry_count": self.retry_count,
        }


class WebhookManager:
    """Manages webhook registrations and event delivery."""

    def __init__(self) -> None:
        self._hooks: dict[str, WebhookConfig] = {}
        self._delivery_log: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def register(self, url: str, events: list[str],
                 secret: str = "") -> WebhookConfig:
        """Register a new webhook."""
        hook_id = f"hook-{hashlib.md5(url.encode()).hexdigest()[:8]}"
        config = WebhookConfig(
            hook_id=hook_id,
            url=url,
            events=events,
            secret=secret,
        )
        with self._lock:
            self._hooks[hook_id] = config
        logger.info("Webhook registered: %s -> %s", hook_id, url)
        return config

    def unregister(self, hook_id: str) -> bool:
        with self._lock:
            if hook_id in self._hooks:
                del self._hooks[hook_id]
                return True
        return False

    def dispatch(self, event_type: str, payload: dict[str, Any]) -> list[str]:
        """Dispatch an event to all matching webhooks.

        Returns list of hook_ids that received the event.
        """
        delivered: list[str] = []

        with self._lock:
            for hook_id, config in self._hooks.items():
                if not config.active:
                    continue
                if event_type not in config.events:
                    continue

                # In production, this would do an HTTP POST
                # Here we just log the delivery
                self._delivery_log.append({
                    "hook_id": hook_id,
                    "event": event_type,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "payload": payload,
                    "status": "delivered",
                })
                delivered.append(hook_id)

        if delivered:
            logger.debug("Event %s dispatched to %d hooks", event_type, len(delivered))
        return delivered

    def get_delivery_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._delivery_log[-limit:]

    def list_hooks(self) -> list[WebhookConfig]:
        with self._lock:
            return list(self._hooks.values())

    def get_hooks_for_event(self, event_type: str) -> list[WebhookConfig]:
        with self._lock:
            return [h for h in self._hooks.values()
                   if h.active and event_type in h.events]