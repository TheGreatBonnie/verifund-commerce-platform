from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from buyer_agent.graph import BuyerState, interpret_brief
from langchain_core.messages import HumanMessage


class FakeTrace:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, dict[str, Any]]] = []

    async def upsert_run(self, run_id: str, **fields: Any) -> None:
        self.upserts.append((run_id, fields))

    async def record(self, *args: Any, **kwargs: Any) -> None:
        return None


async def test_interpret_brief_strips_sentence_period_from_sku() -> None:
    trace = FakeTrace()
    services = SimpleNamespace(trace=trace)
    state = cast(
        BuyerState,
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Find and negotiate the best terms for Mirrorless "
                        "Creator Camera. Product SKU: "
                        "MM-MIRRORLESS-CREATOR-CAMERA. Product details: "
                        "4K video, interchangeable lens."
                    )
                )
            ]
        },
    )
    config = {"configurable": {"thread_id": "run-1", "services": services}}

    result = await interpret_brief(state, config)

    assert result["mandate"]["product_sku"] == "MM-MIRRORLESS-CREATOR-CAMERA"
    assert trace.upserts[-1][1]["mandate"]["product_sku"] == (
        "MM-MIRRORLESS-CREATOR-CAMERA"
    )
