from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Outcome = Literal["continue", "propose_alternative", "escalate_human", "terminate"]


@dataclass(frozen=True)
class DeadlockDecision:
    outcome: Outcome
    reason: str


def detect_deadlock(
    *,
    round: int,
    max_rounds: int,
    has_feasible_move: bool,
    has_non_price_alternative: bool,
    expired: bool = False,
    no_progress: bool = False,
) -> DeadlockDecision:
    if expired:
        return DeadlockDecision("terminate", "expired")
    if round >= max_rounds and not has_feasible_move:
        return DeadlockDecision("terminate", "rounds_exhausted")
    if no_progress and not has_feasible_move and not has_non_price_alternative:
        return DeadlockDecision("terminate", "no_progress")
    if not has_feasible_move and has_non_price_alternative:
        return DeadlockDecision("propose_alternative", "price_infeasible")
    if not has_feasible_move:
        return DeadlockDecision("terminate", "no_feasible_move")
    return DeadlockDecision("continue", "feasible")
