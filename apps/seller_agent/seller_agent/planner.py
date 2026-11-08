from __future__ import annotations

from typing import Any, Literal, Protocol, cast

from commerce_core.contracts import RFQ, CounterOffer, Mandate, Offer
from commerce_core.pricing import SellerPolicy
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool as lc_tool
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, field_validator

SELLER_SYSTEM_PROMPT = """You are an autonomous seller agent in MarketMesh.
Choose exactly one action from the allowed options. Never invent a price or warranty
that is not in the allowed list. The buyer's maximum budget is not available to you.
Choose a negotiation strategy (collaborative, competitive, compromise, value-based)
each round and explain it in rationale. When no feasible price move remains (price-stuck),
propose up to 2 non-price trade-offs (warranty_months, split_shipment, shipping_cents, delivery_days). Return a concise rationale for the audit trail. Prefer a final offer when concession
options are exhausted. You may only choose propose, counter, accept, or reject."""


class SellerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["propose", "counter", "accept", "reject"]
    unit_price_cents: int
    warranty_months: int
    rationale: str
    strategy: Literal["collaborative", "competitive", "compromise", "value-based"] = "collaborative"
    requested_changes: dict[str, str | int | bool] = {}

    @field_validator("requested_changes")
    @classmethod
    def validate_requested_changes(
        cls, changes: dict[str, str | int | bool]
    ) -> dict[str, str | int | bool]:
        allowed = {"warranty_months", "split_shipment", "shipping_cents", "delivery_days"}
        unsupported = set(changes) - allowed
        if unsupported:
            raise ValueError(f"unsupported requested changes: {sorted(unsupported)}")
        if "warranty_months" in changes and (not isinstance(changes["warranty_months"], int) or isinstance(changes["warranty_months"], bool)):
            raise ValueError("warranty_months must be an integer")
        if "split_shipment" in changes and not isinstance(changes["split_shipment"], bool):
            raise ValueError("split_shipment must be a boolean")
        if "shipping_cents" in changes:
            v = changes["shipping_cents"]
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError("shipping_cents must be a non-negative integer")
        if "delivery_days" in changes:
            v = changes["delivery_days"]
            if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
                raise ValueError("delivery_days must be a positive integer")
        return changes


class SellerDecisionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    policy: SellerPolicy
    catalog_item: dict
    mandate: Mandate | None = None
    rfq: RFQ | None = None
    counter_offer: CounterOffer | None = None
    current_round: int
    allowed_prices: list[int]
    allowed_warranty_months: list[int]
    previous_offer: Offer | None = None
    requested_warranty_months: int | None = None
    allow_split: bool = False


class SellerPlanner(Protocol):
    async def decide(self, context: SellerDecisionContext) -> SellerDecision: ...


class ScriptedSellerPlanner:
    async def decide(self, context: SellerDecisionContext) -> SellerDecision:
        policy = context.policy
        if context.rfq is not None and context.counter_offer is None:
            return SellerDecision(
                action="propose",
                unit_price_cents=policy.initial_unit_price_cents,
                warranty_months=policy.base_warranty_months,
                rationale="Initial policy quote.",
            )

        counter = context.counter_offer
        if counter is None:
            return SellerDecision(
                action="reject",
                unit_price_cents=policy.floor_unit_price_cents,
                warranty_months=policy.base_warranty_months,
                rationale="No counteroffer context.",
            )
        target = counter.target_unit_price_cents
        previous = context.previous_offer
        previous_base = (
            previous.line_items[0].unit_price_cents
            if previous is not None and previous.line_items
            else policy.initial_unit_price_cents
        )
        previous_warranty = (
            previous.warranty_months if previous else policy.base_warranty_months
        )
        warranty = context.requested_warranty_months or previous_warranty
        if warranty not in context.allowed_warranty_months:
            return SellerDecision(
                action="reject",
                unit_price_cents=previous_base,
                warranty_months=previous_warranty,
                rationale="Requested warranty is not supported.",
            )
        if target is not None and target < policy.floor_unit_price_cents:
            if context.allowed_prices:
                return SellerDecision(
                    action="counter",
                    unit_price_cents=context.allowed_prices[0],
                    warranty_months=warranty,
                    rationale=(
                        "Buyer target is below the seller floor; hold the "
                        "current policy price."
                    ),
                )
            return SellerDecision(
                action="reject",
                unit_price_cents=previous_base,
                warranty_months=warranty,
                rationale="Buyer target is below the seller floor.",
            )
        if not context.allowed_prices:
            if target is not None and target >= policy.floor_unit_price_cents:
                return SellerDecision(
                    action="accept",
                    unit_price_cents=previous_base,
                    warranty_months=warranty,
                    rationale="No concession remains; accept the current final terms.",
                )
            return SellerDecision(
                action="reject",
                unit_price_cents=previous_base,
                warranty_months=warranty,
                rationale="No concession remains and the target is not acceptable.",
            )
        return SellerDecision(
            action="counter",
            unit_price_cents=context.allowed_prices[0],
            warranty_months=warranty,
            rationale="Concede one ladder step while preserving policy margin.",
        )


class NebiusSellerPlanner:
    def __init__(self, api_key: str, base_url: str, model: str, stock: dict | None = None, policy: SellerPolicy | None = None) -> None:
        common: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "temperature": 0.2,
            "timeout": 30,
            "max_retries": 1,
        }
        self.base_llm = ChatOpenAI(**common)
        self.llm = ChatOpenAI(**common).with_structured_output(SellerDecision)
        self.tools = build_seller_tools(stock or {}, policy)

    async def decide(self, context: SellerDecisionContext) -> SellerDecision:
        messages: list[Any] = [
            SystemMessage(content=SELLER_SYSTEM_PROMPT),
            HumanMessage(content=context.model_dump_json()),
        ]
        try:
            bound = self.base_llm.bind_tools(self.tools)
            for _ in range(2):
                response = await bound.ainvoke(messages)
                tool_calls = getattr(response, "tool_calls", None) or []
                if not tool_calls:
                    break
                messages.append(response)
                tool_by_name = {t.name: t for t in self.tools}
                for call in tool_calls[:2]:
                    name = call.get("name") if isinstance(call, dict) else getattr(call, "name", "")
                    args = call.get("args") if isinstance(call, dict) else getattr(call, "args", {})
                    tool_fn = tool_by_name.get(name)
                    try:
                        result = await tool_fn.ainvoke(args) if tool_fn is not None else {"status": "unavailable"}
                    except Exception:  # noqa: BLE001
                        result = {"status": "unavailable"}
                    messages.append(ToolMessage(content=str(result), tool_call_id=call.get("id", "x") if isinstance(call, dict) else "x"))
        except Exception:  # noqa: BLE001, S110
            pass
        return cast(
            SellerDecision,
            await self.llm.ainvoke(messages),
        )


def get_stock(sku: str, stock: dict) -> dict:
    """Read-only inventory lookup; empty+continue on miss (never raises)."""
    try:
        entry = (stock or {}).get(sku) if isinstance(stock, dict) else None
        if entry is None:
            return {"status": "unavailable", "sku": sku}
        if isinstance(entry, dict):
            return {"status": "ok", "sku": sku, "on_hand": int(entry.get("on_hand", 0)), "incoming": int(entry.get("incoming", 0)), "incoming_days": entry.get("incoming_days")}
        return {"status": "ok", "sku": sku, "on_hand": int(entry)}
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "sku": sku}


def get_policy_bounds(sku: str, policy: SellerPolicy | None) -> dict:
    """Read-only policy bounds for SKU; empty+continue if foreign SKU or no policy."""
    try:
        if policy is None or str(getattr(policy, "sku", "") or "") != sku:
            return {"status": "unavailable", "sku": sku}
        ladders = list(policy.concession_ladder_cents or [])
        ladder_str = [policy.initial_unit_price_cents, *ladders] if policy.initial_unit_price_cents not in ladders else ladders
        return {
            "status": "ok",
            "sku": sku,
            "floor_unit_price_cents": policy.floor_unit_price_cents,
            "allowed_prices": ladder_str,
            "allowed_warranty_months": sorted(int(k) for k in (policy.warranty_addons_cents or {})),
            "max_rounds": policy.max_rounds,
            "stock_on_hand": policy.stock_on_hand,
        }
    except Exception:  # noqa: BLE001
        return {"status": "unavailable", "sku": sku}


def build_seller_tools(stock: dict, policy: SellerPolicy | None):
    """LangChain tools bound to inventory + policy snapshots."""

    @lc_tool
    def get_stock_tool(sku: str) -> dict:
        """Return inventory (on_hand/incoming) for SKU, or unavailable."""
        return get_stock(sku, stock or {})

    @lc_tool
    def get_policy_bounds_tool(sku: str) -> dict:
        """Return floor/ladder/warranties/max_rounds for SKU, or unavailable."""
        return get_policy_bounds(sku, policy)

    get_stock_tool.name = "get_stock"  # type: ignore[attr-defined]
    get_policy_bounds_tool.name = "get_policy_bounds"  # type: ignore[attr-defined]
    return [get_stock_tool, get_policy_bounds_tool]


def select_seller_planner(
    llm_mode: str,
    api_key: str | None,
    base_url: str,
    model: str,
) -> SellerPlanner:
    if llm_mode == "live" and api_key:
        return NebiusSellerPlanner(api_key, base_url, model)
    return ScriptedSellerPlanner()
