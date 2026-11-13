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


class FakeRegistry:
    def __init__(self, products: list[dict[str, Any]]) -> None:
        self._products = products

    async def marketplace_products(self, **_: Any) -> list[dict[str, Any]]:
        return self._products


CATALOG = [
    {
        "sku": "EX-MACBOOK-AIR",
        "name": "MacBook Air",
        "category": "MacBook",
        "seller": "Northwind Audio",
        "description": "Lightweight laptop",
    }
]


async def test_interpret_brief_grounds_sku_and_category_from_the_catalog() -> None:
    trace = FakeTrace()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Negotiate for this product. SKU: EX-MACBOOK-AIR. "
                        "Name: MacBook Air. Unit price: $1,199.99."
                    )
                )
            ]
        },
    )
    config = {"configurable": {"thread_id": "run-1", "services": services}}

    result = await interpret_brief(state, config)

    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"
    assert result["mandate"]["category"] == "MacBook"


async def test_interpret_brief_grounds_the_catalog_when_the_planner_fails() -> None:
    trace = FakeTrace()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {
            "messages": [
                HumanMessage(content="Negotiate for the MacBook Air, quantity 2.")
            ]
        },
    )
    config = {"configurable": {"thread_id": "run-1", "services": services}}

    result = await interpret_brief(state, config)

    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"
    assert result["mandate"]["category"] == "MacBook"


async def test_interpret_brief_accepts_a_bare_sku_label() -> None:
    """The brief may name the SKU without the 'Product ' prefix."""
    trace = FakeTrace()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {
            "messages": [
                HumanMessage(content="Negotiate for the MacBook Air. SKU: EX-MACBOOK-AIR.")
            ]
        },
    )
    config = {"configurable": {"thread_id": "run-1", "services": services}}

    result = await interpret_brief(state, config)

    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"
    assert result["mandate"]["category"] == "MacBook"


async def test_interpret_brief_distrusts_a_sku_the_catalog_does_not_list() -> None:
    """A SKU the catalog does not list cannot identify a seller.

    Discovery filters on the SKU, so believing a wrong one would hide every
    seller — the failure the catalog grounding exists to prevent.
    """
    trace = FakeTrace()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {
            "messages": [
                HumanMessage(
                    content=(
                        "Negotiate for the MacBook Air. "
                        "Product SKU: EX-NOT-IN-CATALOG."
                    )
                )
            ]
        },
    )
    config = {"configurable": {"thread_id": "run-1", "services": services}}

    result = await interpret_brief(state, config)

    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"
    assert result["mandate"]["category"] == "MacBook"


class FailingPlanner:
    """A brief parser that always fails, to measure the retry budget."""

    def __init__(self) -> None:
        self.calls = 0

    async def parse_brief(self, text, products=None):
        self.calls += 1
        raise TimeoutError("llm timed out")


async def test_interpret_brief_does_not_retry_a_failed_planner() -> None:
    trace = FakeTrace()
    planner = FailingPlanner()
    services = SimpleNamespace(trace=trace, registry=FakeRegistry(CATALOG))
    state = cast(
        BuyerState,
        {"messages": [HumanMessage(content="Negotiate for the MacBook Air.")]},
    )
    config = {
        "configurable": {
            "thread_id": "run-1",
            "services": services,
            "planner": planner,
        }
    }

    result = await interpret_brief(state, config)

    assert planner.calls == 1
    assert result["mandate"]["product_sku"] == "EX-MACBOOK-AIR"


def test_nebius_planner_does_not_retry_inside_the_sdk() -> None:
    from buyer_agent.planner import NebiusBuyerPlanner

    planner = NebiusBuyerPlanner("key", "https://example.invalid/v1", "a-model")

    assert planner.base_llm.max_retries == 0
    assert planner.base_llm.request_timeout == 45
