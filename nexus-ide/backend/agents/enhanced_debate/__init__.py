"""Enhanced Agent Parliament System.

This module provides an enhanced multi-agent debate system with:
- Weighted voting based on agent specialization
- Logical judge for final decisions
- Complete debate transcription
- Decision quality evaluation
- Learning loop for continuous improvement
"""

from .voting_system import (
    DecisionType,
    Vote,
    VoteResult,
    WeightedVotingSystem,
)
from .logical_judge import (
    JudgeDecision,
    JudgeReasoning,
    ClarificationRequest,
    LogicalJudge,
)
from .transcriber import (
    DebateStatus,
    DebateTranscript,
    DebateTranscriber,
)
from .evaluator import (
    EvaluationMetric,
    TaskResult,
    DecisionScore,
    DecisionEvaluator,
)
from .learning_loop import (
    LearningStrategy,
    DecisionPattern,
    AgentSpecialization,
    LearningResult,
    LearningLoop,
)

__all__ = [
    "DecisionType",
    "Vote",
    "VoteResult",
    "WeightedVotingSystem",
    "JudgeDecision",
    "JudgeReasoning",
    "ClarificationRequest",
    "LogicalJudge",
    "DebateStatus",
    "DebateTranscript",
    "DebateTranscriber",
    "EvaluationMetric",
    "TaskResult",
    "DecisionScore",
    "DecisionEvaluator",
    "LearningStrategy",
    "DecisionPattern",
    "AgentSpecialization",
    "LearningResult",
    "LearningLoop",
]
