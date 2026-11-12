"""Locks the latency property: one model call per negotiation decision, no tool loop."""
from buyer_agent.planner import CounterChoice, NebiusBuyerPlanner
from commerce_core.contracts import (
    CounterOffer,
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    Preferences,
)
from seller_agent.planner import (
    NebiusSellerPlanner,
    SellerDecision,
    SellerDecisionContext,
)


class _RecordingBaseLLM:
    """Counts bind_tools; a decision must not need a second generation."""

    def __init__(self) -> None:
        self.bound = 0

    def bind_tools(self, tools):
        self.bound += 1
        raise RuntimeError("tool use removed")

    async def ainvoke(self, messages):
        raise AssertionError("base_llm must not be called for a decision")


class _CountingStructuredLLM:
    def __init__(self, result) -> None:
        self.result = result
        self.calls = 0
        self.messages = None

    async def ainvoke(self, messages):
        self.calls += 1
        self.messages = messages
        return self.result


def _mandate() -> Mandate:
    return Mandate(
        run_id="r",
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        max_total_cents=340000,
        deadline_days=14,
        min_warranty_months=12,
        min_returns_days=30,
        preferences=Preferences(),
    )


def _offer() -> Offer:
    return Offer(
        offer_id="o1",
        request_id="r1",
        seller_id="s1",
        seller_name="S1",
        seller_rating=4.0,
        line_items=[
            OfferLineItem(
                sku="SKU",
                name="I",
                quantity=12,
                unit_price_cents=200,
                list_unit_price_cents=220,
            )
        ],
        subtotal_cents=2400,
        shipping_cents=0,
        total_cents=2400,
        delivery_days=7,
        warranty_months=12,
        returns_days=30,
        valid_until="2030-01-01T00:00:00Z",
        terms=OfferTerms(),
        status=OfferStatus.PROPOSED,
        round=1,
    )


async def test_buyer_counter_is_one_model_call():
    planner = NebiusBuyerPlanner(
        "test-key", "http://127.0.0.1:1/v1/", "test-model"
    )
    fake = _CountingStructuredLLM(
        CounterChoice(
            target_unit_price_cents=18300, requested_changes={}, rationale="x"
        )
    )
    base = _RecordingBaseLLM()
    planner.base_llm = base
    planner.counter_llm = fake

    choice = await planner.choose_counter(_offer(), _mandate(), [18300], 2)

    assert choice.target_unit_price_cents == 18300
    assert base.bound == 0, "bind_tools would add extra LLM turns"
    assert fake.calls == 1
    assert len(fake.messages) == 2  # system + human, no ToolMessage
    assert not hasattr(planner, "tools")


async def test_seller_decision_is_one_model_call(northwind_policy):
    planner = NebiusSellerPlanner(
        "test-key", "http://127.0.0.1:1/v1/", "test-model"
    )
    fake = _CountingStructuredLLM(
        SellerDecision(
            action="counter",
            unit_price_cents=18300,
            warranty_months=12,
            rationale="x",
        )
    )
    base = _RecordingBaseLLM()
    planner.base_llm = base
    planner.llm = fake

    context = SellerDecisionContext(
        policy=northwind_policy,
        catalog_item={"sku": "NC-700", "name": "Nimbus NC-700"},
        current_round=2,
        allowed_prices=[18300],
        allowed_warranty_months=[12, 24],
        counter_offer=CounterOffer(
            negotiation_round=2,
            target_unit_price_cents=18300,
            requested_changes={},
            rationale="x",
        ),
    )
    decision = await planner.decide(context)

    assert decision.action == "counter"
    assert base.bound == 0, "bind_tools would add extra LLM turns"
    assert fake.calls == 1
    assert len(fake.messages) == 2
    assert not hasattr(planner, "tools")
