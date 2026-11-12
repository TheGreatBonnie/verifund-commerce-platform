from __future__ import annotations

from collections.abc import Sequence
from typing import Any

SENSITIVE_KEYS = {"max_total_cents", "budget", "seller_token", "settlement_token", "token"}


def build_negotiation_history_artifact(
    turns: Sequence[dict[str, Any]],
    *,
    max_total_cents: int | None = None,
) -> dict[str, Any]:
    safe_turns = []
    for turn in turns:
        safe_turns.append({k: v for k, v in turn.items() if k not in SENSITIVE_KEYS})
    return {"schema_version": "1.0", "kind": "negotiation_history", "turns": safe_turns}
