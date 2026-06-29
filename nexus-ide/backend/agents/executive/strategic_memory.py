"""StrategicMemory — persistent memory for strategic decisions and vision."""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

MEMORY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "strategic_memory.json"


@dataclass
class StrategicDecision:
    """A recorded strategic decision."""

    decision_id: str
    timestamp: float
    context: str
    options: list[str]
    chosen: str
    reasoning: str
    confidence: float
    outcome: Optional[str] = None
    metrics: dict[str, Any] = field(default_factory=dict)


class StrategicMemory:
    """Persistent memory for strategic decisions, vision, and long-term goals.

    Stores decisions in a JSON file with automatic save/restore.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or MEMORY_PATH
        self._decisions: list[StrategicDecision] = []
        self._vision: str = ""
        self._load()

    # ── Vision ────────────────────────────────────────────────────────

    @property
    def vision(self) -> str:
        return self._vision

    def set_vision(self, vision: str) -> None:
        self._vision = vision
        self._save()

    # ── Decisions ─────────────────────────────────────────────────────

    def record_decision(
        self,
        context: str,
        options: list[str],
        chosen: str,
        reasoning: str,
        confidence: float,
        metrics: dict[str, Any] | None = None,
    ) -> StrategicDecision:
        decision = StrategicDecision(
            decision_id=f"sd-{int(time.time() * 1000)}",
            timestamp=time.time(),
            context=context,
            options=options,
            chosen=chosen,
            reasoning=reasoning,
            confidence=confidence,
            metrics=metrics or {},
        )
        self._decisions.append(decision)
        self._save()
        logger.info("Strategic decision recorded: %s", decision.decision_id)
        return decision

    def get_decisions(
        self,
        limit: int = 50,
        min_confidence: float = 0.0,
    ) -> list[StrategicDecision]:
        filtered = [
            d for d in self._decisions
            if d.confidence >= min_confidence
        ]
        return sorted(filtered, key=lambda d: d.timestamp, reverse=True)[:limit]

    def update_outcome(self, decision_id: str, outcome: str) -> bool:
        for d in self._decisions:
            if d.decision_id == decision_id:
                d.outcome = outcome
                self._save()
                return True
        return False

    # ── Similar decisions ─────────────────────────────────────────────

    def find_similar(self, context: str, top_k: int = 3) -> list[StrategicDecision]:
        """Simple keyword overlap similarity for retrieval."""
        context_words = set(context.lower().split())
        scored: list[tuple[float, StrategicDecision]] = []
        for d in self._decisions:
            decision_words = set(d.context.lower().split())
            overlap = len(context_words & decision_words)
            if overlap > 0:
                scored.append((overlap, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:top_k]]

    # ── Persistence ─────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._vision = data.get("vision", "")
            self._decisions = [
                StrategicDecision(**d) for d in data.get("decisions", [])
            ]
        except Exception as e:
            logger.warning("Failed to load strategic memory: %s", e)

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "vision": self._vision,
            "decisions": [
                {
                    "decision_id": d.decision_id,
                    "timestamp": d.timestamp,
                    "context": d.context,
                    "options": d.options,
                    "chosen": d.chosen,
                    "reasoning": d.reasoning,
                    "confidence": d.confidence,
                    "outcome": d.outcome,
                    "metrics": d.metrics,
                }
                for d in self._decisions
            ],
        }
        self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def stats(self) -> dict[str, Any]:
        if not self._decisions:
            return {"total_decisions": 0, "avg_confidence": 0.0}
        confidences = [d.confidence for d in self._decisions]
        return {
            "total_decisions": len(self._decisions),
            "avg_confidence": sum(confidences) / len(confidences),
            "high_confidence_rate": sum(1 for c in confidences if c >= 0.8) / len(confidences),
        }
