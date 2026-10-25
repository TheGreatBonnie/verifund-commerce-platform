from __future__ import annotations

import operator
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, TypedDict

from commerce_core.cards import validate_agent_card
from commerce_core.contracts import (
    RFQ,
    AcceptOffer,
    ApprovalReceipt,
    AwardPackage,
    CounterOffer,
    Mandate,
    NegotiationRecord,
    Offer,
    OfferStatus,
    PurchaseOrderRequest,
    RFQConstraints,
    RFQPreferences,
    ShippingAddress,
)
from commerce_core.pricing import counter_targets
from commerce_core.scoring import (
    ScoredOffer,
    hard_constraint_failures,
)
from commerce_core.scoring import (
    rank_offers as rank_eligible_offers,
)
from commerce_core.extension import wrap_payload
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from buyer_agent.a2a_client import A2ATurn
from buyer_agent.planner import (
    BuyerPlanner,
    CounterChoice,
    ScriptedBuyerPlanner,
    mandate_from_text,
)


def merge_negotiations(
    left: list[dict], right: list[dict]
) -> list[dict]:
    merged: dict[str, dict] = {
        item["seller_id"]: item for item in left if "seller_id" in item
    }
    for item in right:
        merged[item["seller_id"]] = item
    return list(merged.values())


class BuyerState(TypedDict, total=False):
    messages: Annotated[list[AnyMessage], operator.add]
    run_id: str
    mandate: dict
    stage: str
    sellers: list[dict]
    rfq_message: str
    offers: Annotated[list[dict], operator.add]
    negotiations: Annotated[list[dict], merge_negotiations]
    award: dict | None
    award_summary: str
    approval: dict | None
    order: dict | None
    error: dict | None
    trace: Annotated[list[dict], operator.add]
    # Mediated mode (Task 0 gate proof)
    pending_sellers: list[str]
    current_seller_id: str
    current_rfq: dict
    seller_call_result: Any


def _services(config: dict) -> Any:
    return config["configurable"]["services"]


def _planner(config: dict, default: BuyerPlanner) -> BuyerPlanner:
    return config["configurable"].get("planner", default)


def _error(message: str, *, code: str = "invalid_request") -> dict:
    return {"code": code, "message": message, "retryable": False, "details": {}}


async def _upsert(services: Any, run_id: str, **fields: Any) -> None:
    trace = getattr(services, "trace", None)
    if trace is None:
        return
    method = getattr(trace, "upsert_run", None)
    if method is not None:
        await method(run_id, **fields)


async def _record_decision(
    services: Any,
    run_id: str,
    *,
    source: str,
    action: str,
    rationale: str,
    fallback_used: bool = False,
    seller_id: str | None = None,
) -> dict:
    payload = {
        "source": source,
        "action": action,
        "rationale": rationale,
        "fallback_used": fallback_used,
    }
    trace = getattr(services, "trace", None)
    if trace is not None:
        recorder = getattr(trace, "record", None)
        if recorder is not None:
            await recorder(
                run_id,
                direction="internal",
                method=source,
                payload=payload,
                seller_id=seller_id,
            )
    return {"type": "planner_decision", **payload, "seller_id": seller_id}


def _safe_text(text: str, mandate: Mandate) -> bool:
    if not text:
        return False
    budget_dollars = f"{mandate.max_total_cents // 100}"
    budget_cents = str(mandate.max_total_cents)
    return "max_total_cents" not in text and budget_dollars not in text and budget_cents not in text


def fallback_rfq_message(mandate: Mandate) -> str:
    return (
        f"Please quote {mandate.quantity} units of {mandate.product_hint} in "
        f"{mandate.preferences.color or 'black'} with delivery within "
        f"{mandate.deadline_days} days, a {mandate.min_warranty_months}-month "
        f"warranty, and {mandate.min_returns_days}-day returns. Please include "
        "your best structured offer and any sustainability certification."
    )


async def interpret_brief(state: BuyerState, config: dict) -> dict:
    run_id = config["configurable"]["thread_id"]
    messages = state.get("messages", [])
    human = next(
        (
            message
            for message in reversed(messages)
            if isinstance(message, HumanMessage)
        ),
        None,
    )
    if human is None:
        return {
            "run_id": run_id,
            "stage": "needs_clarification",
            "error": _error("A shopping brief is required."),
            "messages": [
                AIMessage(content="Please describe what you would like to buy.")
            ],
        }
    text = human.content if isinstance(human.content, str) else str(human.content)
    planner = _planner(config, ScriptedBuyerPlanner())
    services = _services(config)
    mandate = None
    fallback_used = False
    for _ in range(2):
        try:
            mandate = await planner.parse_brief(text)
            if not isinstance(mandate, Mandate):
                mandate = Mandate.model_validate(mandate)
            break
        except Exception:  # noqa: BLE001
            mandate = None
    if mandate is None:
        fallback_used = True
        try:
            mandate = mandate_from_text(text)
        except Exception as exc:  # noqa: BLE001
            error = _error(f"Could not parse the brief: {exc}")
            return {
                "run_id": run_id,
                "stage": "needs_clarification",
                "error": error,
                "messages": [
                    AIMessage(
                        content=(
                            "I could not parse the brief. Please include the "
                            "product, quantity, budget, delivery deadline, "
                            "warranty, and returns requirements."
                        )
                    )
                ],
            }
    mandate = mandate.model_copy(update={"run_id": run_id})
    sku_match = re.search(r"\bProduct SKU:\s*([A-Za-z0-9._-]+)", text, re.IGNORECASE)
    if sku_match:
        mandate = mandate.model_copy(update={"product_sku": sku_match.group(1)})
    source = "scripted.fallback" if fallback_used else "scripted.decision"
    rationale = (
        "Used regex fallback for the shopping brief."
        if fallback_used
        else "Parsed the shopping brief."
    )
    trace = [
        await _record_decision(
            services,
            run_id,
            source=source,
            action="parse_brief",
            rationale=rationale,
            fallback_used=fallback_used,
        )
    ]
    await _upsert(services, run_id, stage="brief_ready", mandate=mandate.model_dump(mode="json"))
    return {
        "run_id": run_id,
        "mandate": mandate.model_dump(mode="json"),
        "trace": trace,
        "stage": "brief_ready",
        "award": None,
        "approval": None,
        "order": None,
    }


def has_brief(state: BuyerState) -> str:
    return "continue" if state.get("mandate") else "stop"


async def discover_sellers(state: BuyerState, config: dict) -> dict:
    services = _services(config)
    run_id = state["run_id"]
    mandate = Mandate.model_validate(state["mandate"])
    try:
        endpoints = await services.registry.discover(
            mandate.category, mandate.product_sku
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "stage": "failed",
            "error": _error(f"Seller discovery failed: {exc}"),
            "messages": [
                AIMessage(content="Seller discovery failed. Please try again.")
            ],
        }
    sellers = []
    trace = []
    for endpoint in endpoints:
        errors = validate_agent_card(endpoint.card)
        if errors:
            trace.append(
                {
                    "type": "card_rejected",
                    "seller_id": endpoint.seller_id,
                    "reason": "; ".join(errors),
                }
            )
            continue
        sellers.append(
            {
                "seller_id": endpoint.seller_id,
                "name": endpoint.name,
                "card_url": endpoint.card_url,
                "rating": endpoint.rating,
                "sustainability_certified": endpoint.sustainability_certified,
            }
        )
    if not sellers:
        return {
            "sellers": [],
            "trace": trace,
            "stage": "failed",
            "error": _error("No independently validated sellers were found."),
            "messages": [
                AIMessage(content="No validated sellers are available right now.")
            ],
        }
    await _upsert(services, run_id, stage="sellers_discovered")
    return {"sellers": sellers, "trace": trace, "stage": "sellers_discovered"}


def has_sellers(state: BuyerState) -> str:
    return "continue" if state.get("sellers") else "stop"


async def plan_sourcing(state: BuyerState, config: dict) -> dict:
    services = _services(config)
    run_id = state["run_id"]
    mandate = Mandate.model_validate(state["mandate"])
    planner = _planner(config, ScriptedBuyerPlanner())
    fallback_used = False
    message = ""
    for _ in range(2):
        try:
            compose = getattr(planner, "compose_rfq", None)
            if compose is None:
                raise RuntimeError("planner has no compose_rfq")
            message = await compose(mandate)
            if not isinstance(message, str) or not _safe_text(message, mandate):
                raise ValueError("unsafe RFQ prose")
            break
        except Exception:  # noqa: BLE001
            message = ""
    if not message:
        fallback_used = True
        message = fallback_rfq_message(mandate)
    trace = [
        await _record_decision(
            services,
            run_id,
            source="scripted.decision",
            action="compose_rfq",
            rationale="Composed a budget-safe RFQ message." if not fallback_used else "Used deterministic RFQ text.",
            fallback_used=fallback_used,
        )
    ]
    await _upsert(services, run_id, stage="sourcing_planned")
    return {"rfq_message": message, "trace": trace, "stage": "sourcing_planned"}


def _recompute_total(offer: Offer) -> int:
    return sum(
        (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
        for item in offer.line_items
    )


def _trusted_offer(offer: Offer, mandate: Mandate, endpoint: Any, request_id: str) -> tuple[Offer | None, str | None]:
    if offer.seller_id != endpoint.seller_id:
        return None, "offer seller_id does not match the validated card"
    if offer.request_id != request_id:
        return None, "offer request_id does not match the A2A task"
    if mandate.product_sku and any(
        item.sku != mandate.product_sku for item in offer.line_items
    ):
        return None, "offer SKU does not match the requested product"
    if _recompute_total(offer) != offer.subtotal_cents:
        return None, "offer total could not be recomputed"
    if offer.total_cents != offer.subtotal_cents + offer.shipping_cents:
        return None, "offer total does not match line items"
    trusted = offer.model_copy(
        update={
            "seller_rating": endpoint.rating,
            "terms": offer.terms.model_copy(
                update={
                    "sustainability_certified": endpoint.sustainability_certified
                }
            ),
        }
    )
    return trusted, None


async def _choose_counter(
    services: Any,
    run_id: str,
    planner: BuyerPlanner,
    offer: Offer,
    mandate: Mandate,
    allowed: list[int],
    round_number: int,
    seller_id: str,
) -> tuple[CounterChoice, bool, list[dict]]:
    trace = []
    for attempt in range(2):
        try:
            choice = await planner.choose_counter(
                offer, mandate, allowed, round_number
            )
            if not isinstance(choice, CounterChoice):
                choice = CounterChoice.model_validate(choice)
            if choice.target_unit_price_cents not in allowed:
                raise ValueError("counter target is outside allowed list")
            trace.append(
                await _record_decision(
                    services,
                    run_id,
                    source="scripted.decision",
                    action="counter",
                    rationale=choice.rationale,
                    fallback_used=False,
                    seller_id=seller_id,
                )
            )
            return choice, False, trace
        except Exception:  # noqa: BLE001, S112
            continue
    fallback = await ScriptedBuyerPlanner().choose_counter(
        offer, mandate, allowed, round_number
    )
    trace.append(
        await _record_decision(
            services,
            run_id,
            source="scripted.decision",
            action="counter",
            rationale="Planner failed or proposed an invalid target; used the deterministic allowed target.",
            fallback_used=True,
            seller_id=seller_id,
        )
    )
    trace.append(
        {
            "type": "guardrail_rejected",
            "seller_id": seller_id,
            "target_unit_price_cents": allowed[0],
        }
    )
    return fallback, True, trace

def _turn_from_resume(resumed: Any) -> dict:
    if not isinstance(resumed, dict):
        return {"offers": [], "orders": [], "order": None, "task_id": "", "context_id": "", "error": None, "text": ""}
    if "error" in resumed and "offers" not in resumed and "order" not in resumed and "orders" not in resumed:
        return {"offers": [], "orders": [], "order": None, "task_id": resumed.get("task_id", ""), "context_id": resumed.get("context_id", ""), "error": resumed.get("error"), "text": ""}
    offers = resumed.get("offers", [])
    if isinstance(offers, dict):
        offers = [offers]
    return {
        "offers": offers if isinstance(offers, list) else [],
        "orders": resumed.get("orders", []),
        "order": resumed.get("order"),
        "task_id": resumed.get("task_id", ""),
        "context_id": resumed.get("context_id", ""),
        "error": resumed.get("error"),
        "text": resumed.get("text", ""),
        "state": resumed.get("state"),
    }


async def _mediated_prepare(state: BuyerState, config: dict) -> dict:
    return {
        "stage": "negotiating",
        "pending_sellers": [s["seller_id"] for s in state.get("sellers", [])],
    }


async def _mediated_process_seller(state: BuyerState, config: dict) -> dict:
    services = _services(config)
    planner = _planner(config, ScriptedBuyerPlanner())
    run_id = state["run_id"]
    mandate = Mandate.model_validate(state["mandate"])
    seller_id = state.get("current_seller_id", "")
    if not seller_id:
        return {"current_seller_id": ""}
    endpoint = services.registry.endpoint(seller_id)
    rfq_request_id = f"rfq-{run_id}-{seller_id}-mediated"
    rfq = RFQ(
        request_id=rfq_request_id,
        run_id=run_id,
        category=mandate.category,
        product_hint=mandate.product_hint,
        product_sku=mandate.product_sku,
        quantity=mandate.quantity,
        required_by=datetime.now(UTC) + timedelta(days=mandate.deadline_days),
        constraints=RFQConstraints(
            min_warranty_months=mandate.min_warranty_months,
            min_returns_days=mandate.min_returns_days,
            color=mandate.preferences.color,
        ),
        preferences=RFQPreferences(sustainability=mandate.preferences.sustainability),
        message=state.get("rfq_message") or fallback_rfq_message(mandate),
    )
    if not _safe_text(rfq.model_dump_json(), mandate):
        record = NegotiationRecord(
            seller_id=seller_id,
            seller_name=endpoint.name,
            task_id="",
            status="error",
            error="outbound RFQ contained the buyer budget",
        )
        return {
            "current_seller_id": "",
            "trace": (state.get("trace") or [])
            + [{"type": "guardrail_rejected", "seller_id": seller_id, "reason": "budget_in_rfq"}],
            "negotiations": [record.model_dump(mode="json")],
        }

    rounds: list[Offer] = []
    trace: list[dict] = [{"type": "rfq_sent", "seller_id": seller_id}]
    error_message: str | None = None
    task_id = ""
    seller_context_id = run_id

    # RFQ pause
    resumed = interrupt(
        {
            "reason": "seller_call",
            "kind": "rfq",
            "seller_id": seller_id,
            "card_url": endpoint.card_url,
            "request": wrap_payload("rfq", rfq),
            "run_id": run_id,
            "context_id": run_id,
            "seller_task_id": None,
            "seller_context_id": seller_context_id,
            "message": f"Seller call required for {seller_id}.",
        }
    )
    turn = _turn_from_resume(resumed)
    task_id = turn["task_id"] or rfq_request_id
    seller_context_id = turn["context_id"] or seller_context_id
    if turn["error"]:
        error_message = turn["error"]
        trace.append({"type": "seller_error", "seller_id": seller_id, "reason": error_message})
    else:
        for offer in turn["offers"]:
            try:
                offer_obj = offer if isinstance(offer, Offer) else Offer.model_validate(offer)
            except Exception as exc:  # noqa: BLE001
                error_message = f"invalid offer: {exc}"
                trace.append({"type": "protocol_error", "seller_id": seller_id, "reason": error_message})
                continue
            trusted, err = _trusted_offer(offer_obj, mandate, endpoint, rfq_request_id)
            if err or trusted is None:
                error_message = err or "invalid offer"
                trace.append({"type": "protocol_error", "seller_id": seller_id, "reason": error_message})
                continue
            rounds.append(trusted)
        if not rounds and not error_message:
            error_message = "seller returned no structured offer"
        if turn["text"]:
            trace.append({"type": "seller_text", "seller_id": seller_id})

    # Counter rounds
    round_number = 1
    while rounds and round_number < 3:
        last = rounds[-1]
        if last.status in (OfferStatus.FINAL, OfferStatus.REJECTED):
            break
        targets = counter_targets(
            last.line_items[0].unit_price_cents,
            mandate.max_total_cents,
            mandate.quantity,
        )
        index = round_number - 1
        if index >= len(targets):
            break
        allowed = [targets[index]]
        choice, _, counter_trace = await _choose_counter(
            services, run_id, planner, last, mandate, allowed, round_number + 1, seller_id
        )
        trace.extend(counter_trace)
        counter = CounterOffer(
            negotiation_round=round_number + 1,
            target_unit_price_cents=choice.target_unit_price_cents,
            requested_changes=choice.requested_changes,
            rationale=choice.rationale,
        )
        resumed = interrupt(
            {
                "reason": "seller_call",
                "kind": "counter",
                "seller_id": seller_id,
                "card_url": endpoint.card_url,
                "request": wrap_payload("counter_offer", counter),
                "run_id": run_id,
                "context_id": run_id,
                "seller_task_id": task_id or None,
                "seller_context_id": seller_context_id,
                "message": f"Counteroffer required for {seller_id}.",
            }
        )
        turn = _turn_from_resume(resumed)
        task_id = turn["task_id"] or task_id
        seller_context_id = turn["context_id"] or seller_context_id
        if turn["error"]:
            error_message = turn["error"]
            trace.append({"type": "seller_error", "seller_id": seller_id, "reason": error_message})
            break
        new_offers = []
        for offer in turn["offers"]:
            if isinstance(offer, dict):
                try:
                    offer_obj = Offer.model_validate(offer)
                except Exception:
                    continue
            else:
                offer_obj = offer
            trusted, err = _trusted_offer(offer_obj, mandate, endpoint, rfq_request_id)
            if err or trusted is None:
                error_message = err or "invalid offer"
                trace.append({"type": "protocol_error", "seller_id": seller_id, "reason": error_message})
                continue
            new_offers.append(trusted)
        if new_offers:
            rounds.extend(new_offers)
        else:
            if not error_message:
                error_message = "seller returned no structured offer"
            break
        round_number += 1

    final = rounds[-1] if rounds else None
    status = final.status.value if final is not None else "error"
    if error_message and final is None:
        status = "error"
    record = NegotiationRecord(
        seller_id=seller_id,
        seller_name=endpoint.name,
        task_id=task_id,
        status=status,
        rounds=rounds,
        final_offer=final,
        error=error_message,
    )
    result: dict[str, Any] = {
        "offers": [final.model_dump(mode="json")] if final is not None else [],
        "negotiations": [record.model_dump(mode="json")],
        "trace": trace,
        "current_seller_id": "",
    }
    return result


async def _mediated_select(state: BuyerState, config: dict) -> dict:
    pending = list(state.get("pending_sellers", []))
    if not pending:
        return {"current_seller_id": "", "stage": "ranking_ready"}
    seller_id = pending[0]
    remaining = pending[1:]
    return {
        "current_seller_id": seller_id,
        "pending_sellers": remaining,
        "stage": "seller_call_pending",
    }


def _mediated_route_after_select(state: BuyerState) -> str:
    if state.get("current_seller_id"):
        return "process_seller"
    if state.get("pending_sellers"):
        return "select_next_seller"
    return "rank_offers"


def _mediated_route_after_process(state: BuyerState) -> str:
    if state.get("pending_sellers"):
        return "select_next_seller"
    return "rank_offers"


async def _mediated_place_order(state: BuyerState, config: dict) -> dict:
    services = _services(config)
    run_id = state["run_id"]
    approval = state.get("approval") or {}
    if not approval.get("approved") or not str(approval.get("approved_by", "")).strip():
        return await cancel_losers(state, config)
    award = state.get("award") or {}
    winner = Offer.model_validate(award["winner"])
    endpoint = services.registry.endpoint(winner.seller_id)
    receipt = ApprovalReceipt(
        approval_id=str(uuid.uuid4()),
        approved_by=str(approval["approved_by"]),
        approved_at=datetime.now(UTC),
        note=approval.get("note") or None,
    )
    po = PurchaseOrderRequest(
        request_id=f"po-{run_id}-{winner.offer_id}",
        run_id=run_id,
        offer_id=winner.offer_id,
        seller_id=winner.seller_id,
        quantity=sum(item.quantity for item in winner.line_items),
        shipping_address=_shipping_address(),
        approval=receipt,
        idempotency_key=f"{run_id}:{winner.offer_id}",
        expected_total_cents=winner.total_cents,
    )
    # Accept by persisted offer ID in a fresh seller task. The negotiation task
    # may already be terminal after a counter-offer or timeout.
    accept = AcceptOffer(
        offer_id=winner.offer_id,
        round=winner.round,
        accepted_total_cents=winner.total_cents,
        accepted_by_buyer_task=run_id,
    )
    resumed = interrupt(
        {
            "reason": "seller_call",
            "kind": "accept",
            "seller_id": winner.seller_id,
            "card_url": endpoint.card_url,
            "request": wrap_payload("accept_offer", accept),
            "run_id": run_id,
            "context_id": run_id,
            "seller_task_id": None,
            "seller_context_id": run_id,
            "message": f"Acceptance required for {winner.seller_id}.",
        }
    )
    turn = _turn_from_resume(resumed)
    if turn.get("error"):
        await _upsert(services, run_id, stage="order_failed", error=turn["error"])
        return {"stage": "order_failed", "order": None, "error": _error(turn["error"]), "messages": [AIMessage(content=f"I could not place the order: {turn['error']}")]}

    # order pause
    resumed = interrupt(
        {
            "reason": "seller_call",
            "kind": "order",
            "seller_id": winner.seller_id,
            "card_url": endpoint.card_url,
            "request": wrap_payload("purchase_order", po),
            "run_id": run_id,
            "context_id": run_id,
            "seller_task_id": None,
            "seller_context_id": run_id,
            "message": f"Order required for {winner.seller_id}.",
        }
    )
    turn = _turn_from_resume(resumed)
    order = turn.get("order")
    if order is None:
        for o in turn.get("orders", []) + turn.get("offers", []):
            if isinstance(o, dict) and o.get("order_id"):
                order = o
                break
    if order is None:
        err = turn.get("error") or "Order failed."
        await _upsert(services, run_id, stage="order_failed", error=err)
        return {"stage": "order_failed", "order": None, "error": _error(err), "messages": [AIMessage(content=f"I could not place the order: {err}")]}

    updates = []
    for other in state.get("negotiations", []):
        if other.get("seller_id") == winner.seller_id:
            updates.append({**other, "status": "accepted", "final_offer": winner.model_dump(mode="json")})
            continue
        updates.append({**other, "status": "cancelled", "error": None})
    await _upsert(services, run_id, stage="ordered", order=order if isinstance(order, dict) else order)
    return {
        "order": order if isinstance(order, dict) else (order.model_dump(mode="json") if hasattr(order, "model_dump") else order),
        "negotiations": updates,
        "stage": "ordered",
        "trace": [{"type": "order_confirmed", "seller_id": winner.seller_id, "order_id": (order.get("order_id") if isinstance(order, dict) else getattr(order, "order_id", None))}],
    }


def mandate_qty(state):
    return Mandate.model_validate(state["mandate"]).quantity


async def rank_offers(state: BuyerState, config: dict) -> dict:
    services = _services(config)
    run_id = state["run_id"]
    mandate = Mandate.model_validate(state["mandate"])
    planner = _planner(config, ScriptedBuyerPlanner())
    by_seller: dict[str, Offer] = {}
    for raw in state.get("offers", []):
        offer = Offer.model_validate(raw)
        by_seller[offer.seller_id] = offer
    offers = list(by_seller.values())
    ranked = rank_eligible_offers(mandate, offers)
    if not ranked:
        failures = {
            offer.seller_id: hard_constraint_failures(mandate, offer)
            for offer in offers
        }
        error = _error("No offer satisfies the buyer mandate.")
        error["details"] = {"failures": failures}
        await _upsert(services, run_id, stage="no_award")
        return {
            "stage": "no_award",
            "error": error,
            "award": None,
            "messages": [
                AIMessage(
                    content="No seller offer satisfies the mandate, so I did not award an order."
                )
            ],
        }
    winner: ScoredOffer = ranked[0]
    initial_totals = []
    for negotiation in state.get("negotiations", []):
        rounds = negotiation.get("rounds", [])
        if rounds:
            initial_totals.append(Offer.model_validate(rounds[0]).total_cents)
    savings = sum(initial_totals) - winner.offer.total_cents
    award = AwardPackage(
        winner=winner.offer,
        score=winner.score,
        alternatives=[item.offer for item in ranked[1:]],
        scores={item.offer.seller_id: item.score for item in ranked},
        savings_cents=savings,
        mandate_checks=[
            f"{item.offer.seller_id}: eligible" for item in ranked
        ],
    )
    fallback_used = False
    explanation = ""
    for _ in range(2):
        try:
            explanation = await planner.explain_award(award)
            if not isinstance(explanation, str) or not explanation.strip():
                raise ValueError("empty award explanation")
            break
        except Exception:  # noqa: BLE001
            explanation = ""
    if not explanation:
        fallback_used = True
        best = winner.offer.total_cents
        explanation = (
            f"{winner.offer.seller_name} wins the award at ${best / 100:,.2f} "
            f"with a score of {winner.score:.1f}. The offer satisfies every "
            f"mandate constraint and saves ${savings / 100:,.2f} versus the "
            f"initial quotes."
        )
    trace = [
        await _record_decision(
            services,
            run_id,
            source="scripted.decision",
            action="explain_award",
            rationale=explanation,
            fallback_used=fallback_used,
        )
    ]
    await _upsert(
        services,
        run_id,
        stage="awaiting_approval",
        award=award.model_dump(mode="json"),
    )
    return {
        "award": award.model_dump(mode="json"),
        "award_summary": explanation,
        "trace": trace,
        "stage": "awaiting_approval",
        "messages": [AIMessage(content=explanation)],
    }


def has_award(state: BuyerState) -> str:
    return "continue" if state.get("award") else "stop"


async def await_approval(state: BuyerState, config: dict) -> dict:
    award = state.get("award") or {}
    winner = (award.get("winner") or {})
    payload = {
        "message": (
            f"Approve the award to {winner.get('seller_name', 'the selected seller')} "
            f"for ${winner.get('total_cents', 0) / 100:,.2f}?"
        ),
        "reason": "order_approval",
        "responseSchema": {
            "type": "object",
            "required": ["approved", "approved_by", "note"],
            "properties": {
                "approved": {"type": "boolean"},
                "approved_by": {"type": "string"},
                "note": {"type": "string"},
            },
        },
        "award": award,
    }
    from buyer_agent.policies import normalize_approval

    decision = normalize_approval(interrupt(payload))
    return {
        "approval": decision,
        "stage": "approved" if decision["approved"] else "rejected",
    }


def approval_route(state: BuyerState) -> str:
    return "approved" if (state.get("approval") or {}).get("approved") else "rejected"


def _shipping_address() -> ShippingAddress:
    return ShippingAddress(
        name="Demo Buyer",
        line1="1 Market Street",
        city="San Francisco",
        region="CA",
        postal_code="94105",
        country="US",
    )


def _negotiation_for(state: BuyerState, seller_id: str) -> dict | None:
    for negation in state.get("negotiations", []):
        if negation.get("seller_id") == seller_id:
            return negation
    return None


async def cancel_losers(state: BuyerState, config: dict) -> dict:
    services = _services(config)
    run_id = state["run_id"]
    updates = []
    for negotiation in state.get("negotiations", []):
        updates.append(
            {
                **negotiation,
                "status": "cancelled",
                "error": None,
            }
        )
    await _upsert(services, run_id, stage="rejected")
    return {
        "negotiations": updates,
        "stage": "rejected",
        "order": None,
        "trace": [{"type": "award_rejected"}],
    }


async def finalize(state: BuyerState, config: dict) -> dict:
    stage = state.get("stage", "finished")
    if stage == "ordered":
        order = state.get("order") or {}
        summary = (
            f"Order {order.get('order_id', '')} is confirmed with "
            f"{order.get('seller_id', 'the winner')}. "
            f"Tracking: {order.get('tracking_number', 'pending')}."
        )
    elif stage == "rejected":
        summary = (
            "The award was rejected by the human reviewer, so no order was "
            "placed and all seller negotiations were closed."
        )
    elif stage == "order_failed":
        summary = "The order could not be completed."
    else:
        summary = "The sourcing run finished."
    return {"messages": [AIMessage(content=summary)], "stage": stage}

def build_buyer_graph(services=None, checkpointer=None, *, planner=None):
    default_planner = planner or ScriptedBuyerPlanner()
    # ty cannot match TypedDicts against langgraph's StateLike protocol bound.
    builder = StateGraph(BuyerState)  # ty: ignore[invalid-argument-type]

    async def _interpret(state, config):
        return await interpret_brief(state, config)

    async def _discover(state, config):
        return await discover_sellers(state, config)

    async def _plan(state, config):
        return await plan_sourcing(state, config)

    async def _prepare(state, config):
        return await _mediated_prepare(state, config)

    async def _select(state, config):
        return await _mediated_select(state, config)

    async def _process(state, config):
        return await _mediated_process_seller(state, config)

    async def _rank(state, config):
        return await rank_offers(state, config)

    async def _approval(state, config):
        return await await_approval(state, config)

    async def _order(state, config):
        return await _mediated_place_order(state, config)

    async def _cancel(state, config):
        return await cancel_losers(state, config)

    async def _finalize(state, config):
        return await finalize(state, config)

    def with_planner(fn):
        async def wrapped(state, config):
            config = dict(config)
            configurable = dict(config.get("configurable", {}))
            configurable.setdefault("planner", default_planner)
            if services is not None:
                configurable.setdefault("services", services)
            config["configurable"] = configurable
            return await fn(state, config)

        return wrapped

    for name, fn in [
        ("interpret_brief", _interpret),
        ("discover_sellers", _discover),
        ("plan_sourcing", _plan),
        ("prepare_mediated", _prepare),
        ("select_next_seller", _select),
        ("process_seller", _process),
        ("rank_offers", _rank),
        ("await_approval", _approval),
        ("place_order", _order),
        ("cancel_losers", _cancel),
        ("finalize", _finalize),
    ]:
        builder.add_node(name, with_planner(fn))

    builder.add_edge(START, "interpret_brief")
    builder.add_conditional_edges(
        "interpret_brief", has_brief, {"continue": "discover_sellers", "stop": END}
    )
    builder.add_conditional_edges(
        "discover_sellers", has_sellers, {"continue": "plan_sourcing", "stop": END}
    )
    builder.add_edge("plan_sourcing", "prepare_mediated")
    builder.add_edge("prepare_mediated", "select_next_seller")
    builder.add_conditional_edges(
        "select_next_seller",
        _mediated_route_after_select,
        {
            "process_seller": "process_seller",
            "select_next_seller": "select_next_seller",
            "rank_offers": "rank_offers",
        },
    )
    # Apply is folded into process_seller; route after process:
    builder.add_conditional_edges(
        "process_seller",
        _mediated_route_after_process,
        {"select_next_seller": "select_next_seller", "rank_offers": "rank_offers"},
    )
    builder.add_conditional_edges(
        "rank_offers", has_award, {"continue": "await_approval", "stop": END}
    )
    builder.add_conditional_edges(
        "await_approval",
        approval_route,
        {"approved": "place_order", "rejected": "cancel_losers"},
    )
    builder.add_edge("place_order", "finalize")
    builder.add_edge("cancel_losers", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())



