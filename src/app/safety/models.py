from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar


class RiskLevel(str, Enum):
    READ_ONLY = "read_only"
    LOW_IMPACT = "low_impact"
    REVERSIBLE_WRITE = "reversible_write"
    SENSITIVE = "sensitive"
    DESTRUCTIVE = "destructive"


class ActionOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True)
class ActionPolicy:
    key: str
    risk: RiskLevel
    description: str

    @property
    def requires_confirmation(self) -> bool:
        return self.risk not in {RiskLevel.READ_ONLY, RiskLevel.LOW_IMPACT}


@dataclass(frozen=True)
class ActionRequest:
    action_id: str
    policy: ActionPolicy
    summary: str
    session_id: str
    metadata: dict[str, str] = field(default_factory=dict)


T = TypeVar("T")


@dataclass(frozen=True)
class ExecutionResult(Generic[T]):
    outcome: ActionOutcome
    value: T | None = None
    error_type: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is ActionOutcome.SUCCEEDED
