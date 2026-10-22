from __future__ import annotations

from typing import Literal, Protocol

from commerce_core.contracts import RFQ, CounterOffer, Mandate, Offer
from commerce_core.pricing import SellerPolicy
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict

SELLER_SYSTEM_PROMPT = """You are an autonomous seller agent in MarketMesh.
Choose exactly one action from the allowed options. Never invent a price or warranty
that is not in the allowed list. The buyer's maximum budget is not available to you.
Return a concise rationale for the audit trail. Prefer a final offer when concession
options are exhausted. You may only choose propose, counter, accept, or reject."""


class SellerDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["propose", "counter", "accept", "reject"]
    unit_price_cents: int
    warranty_months: int
    rationale: str


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
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self.llm = ChatOpenAI(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=0.2,
            timeout=30,
            max_retries=1,
        ).with_structured_output(SellerDecision)

    async def decide(self, context: SellerDecisionContext) -> SellerDecision:
        return await self.llm.ainvoke(
            [
                SystemMessage(content=SELLER_SYSTEM_PROMPT),
                HumanMessage(content=context.model_dump_json()),
            ]
        )


def select_seller_planner(
    llm_mode: str,
    api_key: str | None,
    base_url: str,
    model: str,
) -> SellerPlanner:
    if llm_mode == "live" and api_key:
        return NebiusSellerPlanner(api_key, base_url, model)
    return ScriptedSellerPlanner()
