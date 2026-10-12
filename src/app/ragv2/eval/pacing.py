"""Rate-safe pacing for cloud-backed RAG benchmarks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import sleep


@dataclass(frozen=True, slots=True)
class PacingPause:
    """Describes one pause inserted between benchmark batches."""

    completed_cases: int
    total_cases: int
    seconds: float
    reason: str = "batch-boundary"


class FixedBatchPacer:
    """Pauses after each fixed-size batch of benchmark cases.

    A RAG case can issue several model requests. Limiting whole cases is
    intentionally more conservative and predictable than limiting request
    count when using Groq's small free-plan token-per-minute allowance.
    """

    def __init__(
        self,
        *,
        cases_per_batch: int = 2,
        pause_seconds: float = 60.0,
        initial_cooldown_seconds: float = 0.0,
        sleep_function: Callable[[float], None] = sleep,
        on_pause: Callable[[PacingPause], None] | None = None,
    ) -> None:
        if cases_per_batch < 1:
            raise ValueError("cases_per_batch must be at least one")
        if pause_seconds < 0:
            raise ValueError("pause_seconds cannot be negative")
        if initial_cooldown_seconds < 0:
            raise ValueError("initial_cooldown_seconds cannot be negative")

        self.cases_per_batch = cases_per_batch
        self.pause_seconds = pause_seconds
        self.initial_cooldown_seconds = initial_cooldown_seconds
        self.sleep_function = sleep_function
        self.on_pause = on_pause

    def before_run(self, *, total_cases: int) -> float:
        """Starts a cloud run only after a clean provider window."""

        if total_cases < 1 or self.initial_cooldown_seconds == 0:
            return 0.0

        pause = PacingPause(
            completed_cases=0,
            total_cases=total_cases,
            seconds=self.initial_cooldown_seconds,
            reason="initial-cooldown",
        )
        if self.on_pause is not None:
            self.on_pause(pause)

        self.sleep_function(self.initial_cooldown_seconds)
        return self.initial_cooldown_seconds

    def after_case(
        self,
        *,
        completed_cases: int,
        total_cases: int,
    ) -> float:
        """Pauses after a full batch unless the run has finished."""

        should_pause = (
            completed_cases < total_cases
            and completed_cases % self.cases_per_batch == 0
            and self.pause_seconds > 0
        )
        if not should_pause:
            return 0.0

        pause = PacingPause(
            completed_cases=completed_cases,
            total_cases=total_cases,
            seconds=self.pause_seconds,
        )
        if self.on_pause is not None:
            self.on_pause(pause)

        self.sleep_function(self.pause_seconds)
        return self.pause_seconds
