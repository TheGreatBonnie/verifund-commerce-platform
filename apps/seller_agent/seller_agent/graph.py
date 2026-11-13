from __future__ import annotations

import uuid
from typing import TypedDict

from commerce_core.binding import BINDING_VERSION
from commerce_core.contracts import (
    RFQ,
    AcceptOffer,
    CommerceError,
    CommerceErrorCode,
    CounterOffer,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    PurchaseOrderRequest,
)
from commerce_core.extension import expected_schema, parse_payload
from commerce_core.pricing import Quote, SellerPolicy
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from seller_agent.engine import SellerNegotiationEngine
from seller_agent.planner import (
    ScriptedSellerPlanner,
    SellerDecision,
    SellerDecisionContext,
    SellerPlanner,
)

_SELLER_ENGINE = SellerNegotiationEngine()


class SellerState(TypedDict, total=False):
    task_id: str
    context_id: str
    kind: str
    incoming: dict
    rfq: RFQ | None
    counter: CounterOffer | None
    previous_offer: Offer | None
    current_round: int
    allowed_prices: list[int]
    allowed_warranty_months: list[int]
    requested_warranty_months: int | None
    allow_split: bool
    decision: dict | None
    offer: dict | None
    order: dict | None
    error: dict | None
    task_state: str
    message: str


class CommerceProtocolError(Exception):
    pass


SCHEMA_KINDS = {
    expected_schema(kind): kind
    for kind in ("rfq", "counter_offer", "accept_offer", "purchase_order")
}


def kind_from_envelope(envelope: dict) -> str:
    kind = SCHEMA_KINDS.get(envelope.get("schema", ""))
    if kind is None:
        raise CommerceProtocolError("unsupported commerce schema")
    return kind


def _error(
    code: CommerceErrorCode, message: str, *, retryable: bool = False
) -> dict:
    return {
        "code": code.value,
        "message": message,
        "retryable": retryable,
        "details": {},
    }


def classify(state: SellerState) -> dict:
    envelope = state.get("incoming")
    try:
        if not envelope:
            raise CommerceProtocolError("missing DataPart")
        kind = kind_from_envelope(envelope)
    except CommerceProtocolError as exc:
        return {
            "kind": "invalid",
            "error": _error(CommerceErrorCode.INVALID_REQUEST, str(exc)),
            "task_state": "failed",
            "message": str(exc),
        }
    return {"kind": kind}


def route_kind(state: SellerState) -> str:
    kind = state.get("kind", "invalid")
    if kind == "purchase_order":
        return "order"
    if kind in {"rfq", "counter_offer", "accept_offer"}:
        return kind
    return "invalid"


def _catalog_item(policy: SellerPolicy) -> dict:
    return {
        "sku": policy.sku,
        "name": policy.product_name,
        "list_unit_price_cents": policy.list_unit_price_cents,
        "sustainability_certified": policy.sustainability_certified,
        "rating": policy.rating,
    }




def _filter_counter_changes(
    changes: dict[str, object], allowed_warranties: list[int]
) -> tuple[dict[str, object], list[str]]:
    """Drop changes the seller cannot grant instead of rejecting the counter.

    A seller can grant a warranty month from its policy and it can commit to a
    split shipment. It cannot grant a different delivery SLA or a shipping
    price, and a warranty month it does not offer is ignored. Dropping the
    ungrantable parts lets the seller answer the counter on the terms it can
    actually move.
    """
    grantable = {"warranty_months", "split_shipment"}
    kept: dict[str, object] = {}
    dropped: list[str] = []
    for key, value in changes.items():
        if key not in grantable:
            dropped.append(key)
            continue
        if key == "warranty_months":
            try:
                warranty = int(value)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                dropped.append(key)
                continue
            if warranty not in allowed_warranties:
                dropped.append(key)
                continue
            kept[key] = warranty
            continue
        if key == "split_shipment":
            if isinstance(value, bool):
                kept[key] = value
            elif str(value).lower() in {"true", "1", "yes"}:
                kept[key] = True
            elif str(value).lower() in {"false", "0", "no"}:
                kept[key] = False
            else:
                dropped.append(key)
            continue
    return kept, dropped


def _parse_requested_warranty(
    changes: dict[str, str | int | bool], allowed: list[int]
) -> int | None:
    value = changes.get("warranty_months")
    if value is None:
        return None
    try:
        warranty = int(value)
    except (TypeError, ValueError) as exc:
        raise CommerceProtocolError("warranty_months must be an integer") from exc
    if warranty not in allowed:
        raise CommerceProtocolError("requested warranty is not supported")
    return warranty


async def prepare(state: SellerState, config: RunnableConfig) -> dict:
    service = config["configurable"]["service"]
    policy: SellerPolicy = service.policy
    kind = state["kind"]
    try:
        if kind == "rfq":
            rfq = parse_payload("rfq", state["incoming"], RFQ)
            policy = policy.for_product(rfq.product_sku, rfq.product_hint)
            return {
                "rfq": rfq,
                "counter": None,
                "previous_offer": None,
                "current_round": 1,
                "allowed_prices": [
                    policy.initial_unit_price_cents,
                    *policy.next_price_options(
                        policy.initial_unit_price_cents
                    ),
                ],
                "allowed_warranty_months": sorted(
                    policy.warranty_addons_cents
                ),
                "requested_warranty_months": None,
                "allow_split": False,
            }
        if kind == "counter_offer":
            counter = parse_payload(
                "counter_offer", state["incoming"], CounterOffer
            )
            previous = await service.store.get_latest_offer(state["task_id"])
            if previous is None:
                raise CommerceProtocolError(
                    "counteroffer has no previous offer"
                )
            policy = policy.for_product(
                previous.line_items[0].sku if previous.line_items else None
            )
            allowed_warranties = sorted(policy.warranty_addons_cents)
            filtered_changes, _dropped = _filter_counter_changes(
                counter.requested_changes, allowed_warranties
            )
            requested_warranty = _parse_requested_warranty(
                filtered_changes, allowed_warranties
            )
            allow_split = bool(filtered_changes.get("split_shipment", False))
            counter = counter.model_copy(update={"requested_changes": filtered_changes})
            previous_base = previous.line_items[0].unit_price_cents
            return {
                "counter": counter,
                "previous_offer": previous,
                "current_round": previous.round + 1,
                "allowed_prices": policy.next_price_options(previous_base),
                "allowed_warranty_months": allowed_warranties,
                "requested_warranty_months": requested_warranty,
                "allow_split": allow_split,
            }
        return {}
    except Exception as exc:  # noqa: BLE001
        return {
            "error": _error(
                CommerceErrorCode.UNSUPPORTED_CONSTRAINT, str(exc)
            ),
            "task_state": "failed",
            "message": str(exc),
        }


def _build_context(
    state: SellerState, policy: SellerPolicy
) -> SellerDecisionContext:
    return SellerDecisionContext(
        policy=policy,
        catalog_item=_catalog_item(policy),
        rfq=state.get("rfq"),
        counter_offer=state.get("counter"),
        current_round=state.get("current_round", 1),
        allowed_prices=state.get("allowed_prices", []),
        allowed_warranty_months=state.get(
            "allowed_warranty_months", sorted(policy.warranty_addons_cents)
        ),
        previous_offer=state.get("previous_offer"),
        requested_warranty_months=state.get("requested_warranty_months"),
        allow_split=state.get("allow_split", False),
    )


def _valid_decision(
    decision: SellerDecision, context: SellerDecisionContext
) -> bool:
    return _SELLER_ENGINE.validate_decision(
        decision,
        allowed_prices=context.allowed_prices,
        allowed_warranty_months=context.allowed_warranty_months,
        floor_unit_price_cents=context.policy.floor_unit_price_cents,
    )


async def decide(state: SellerState, config: RunnableConfig) -> dict:
    if state.get("error"):
        return {}
    service = config["configurable"]["service"]
    planner: SellerPlanner = config["configurable"]["planner"]
    base_policy: SellerPolicy = service.policy
    rfq = state.get("rfq")
    previous = state.get("previous_offer")
    sku = (
        rfq.product_sku
        if rfq is not None
        else previous.line_items[0].sku
        if previous is not None and previous.line_items
        else None
    )
    hint = rfq.product_hint if rfq is not None else ""
    policy: SellerPolicy = base_policy.for_product(sku, hint)
    context = _build_context(state, policy)
    fallback_used = False
    try:
        decision = await planner.decide(context)
        if not isinstance(decision, SellerDecision) or not _valid_decision(
            decision, context
        ):
            raise ValueError("invalid seller decision")
    except Exception:  # noqa: BLE001
        fallback_used = True
        try:
            decision = await ScriptedSellerPlanner().decide(context)
        except Exception as exc:  # noqa: BLE001
            return {
                "error": _error(CommerceErrorCode.INVALID_REQUEST, str(exc)),
                "task_state": "failed",
                "message": str(exc),
            }
    if fallback_used:
        decision = decision.model_copy(
            update={
                "rationale": f"{decision.rationale} [fallback_used]"
            }
        )
    return {"decision": decision.model_dump()}


def route_decision(state: SellerState) -> str:
    if state.get("error"):
        return "reject"
    decision = state.get("decision") or {}
    action = decision.get("action", "reject")
    if action in {"propose", "counter"}:
        return "finalize"
    if action == "accept":
        return "accept"
    return "reject"


def _offer_from_quote(
    *,
    policy: SellerPolicy,
    state: SellerState,
    quote: Quote,
    decision: SellerDecision,
) -> Offer:
    rfq = state.get("rfq")
    previous = state.get("previous_offer")
    request_id = (
        rfq.request_id
        if rfq is not None
        else previous.request_id
        if previous is not None
        else "unknown"
    )
    quantity = (
        rfq.quantity
        if rfq is not None
        else previous.line_items[0].quantity
        if previous is not None
        else 0
    )
    status = _SELLER_ENGINE.status_for_offer(
        round=state.get("current_round", 1),
        max_rounds=policy.max_rounds,
        unit_price_cents=decision.unit_price_cents,
        floor_unit_price_cents=policy.floor_unit_price_cents,
        next_prices=policy.next_price_options(decision.unit_price_cents),
    )
    line_item = OfferLineItem(
        sku=policy.sku,
        name=policy.product_name,
        quantity=quantity,
        unit_price_cents=quote.base_unit_price_cents,
        list_unit_price_cents=policy.list_unit_price_cents,
        warranty_addon_cents=quote.warranty_addon_cents,
        attributes={
            "image_url": policy.product_image_url or policy.image_url,
            "color_name": policy.color,
            "description": policy.product_description or policy.product_name,
            "condition": "new",
            "category": policy.categories[0] if policy.categories else "",
            "tag": policy.product_tag,
            "specs": policy.product_description or policy.product_name,
        },
    )
    return Offer(
        offer_id=str(uuid.uuid4()),
        request_id=request_id,
        seller_id=policy.seller_id,
        seller_name=policy.name,
        seller_rating=policy.rating,
        task_id=state["task_id"],
        context_id=state["context_id"],
        line_items=[line_item],
        subtotal_cents=quote.subtotal_cents,
        shipping_cents=0,
        total_cents=quote.total_cents,
        delivery_days=quote.delivery_days,
        warranty_months=quote.warranty_months,
        returns_days=policy.returns_days,
        valid_until=quote.valid_until,
        terms=OfferTerms(
            sustainability_certified=policy.sustainability_certified,
            stock_confidence=quote.stock_confidence,
            split_shipment=quote.split_shipment,
        ),
        binding_version=BINDING_VERSION,
        status=status,
        round=state.get("current_round", 1),
        rationale=decision.rationale,
    )


async def finalize_offer(state: SellerState, config: RunnableConfig) -> dict:
    if state.get("error"):
        return {}
    service = config["configurable"]["service"]
    base_policy: SellerPolicy = service.policy
    decision = SellerDecision.model_validate(state["decision"])
    previous = state.get("previous_offer")
    rfq = state.get("rfq")
    sku = (
        rfq.product_sku
        if rfq is not None
        else previous.line_items[0].sku
        if previous is not None and previous.line_items
        else None
    )
    policy: SellerPolicy = base_policy.for_product(
        sku, rfq.product_hint if rfq is not None else ""
    )
    quantity = (
        rfq.quantity
        if rfq is not None
        else previous.line_items[0].quantity
        if previous is not None
        else 0
    )
    try:
        live_stock = await service.store.get_stock(policy.sku)
        quote = policy.quote(
            quantity=quantity,
            unit_price_cents=decision.unit_price_cents,
            warranty_months=decision.warranty_months,
            allow_split=state.get("allow_split", False),
            stock_on_hand=live_stock.on_hand,
            incoming_stock=live_stock.incoming,
            incoming_days=live_stock.incoming_days,
        )
        offer = _offer_from_quote(
            policy=policy, state=state, quote=quote, decision=decision
        )
        await service.store.save_offer(
            offer, task_id=state["task_id"], context_id=state["context_id"]
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": _error(CommerceErrorCode.INVALID_REQUEST, str(exc)),
            "task_state": "failed",
            "message": str(exc),
        }
    return {
        "offer": offer.model_dump(mode="json"),
        "task_state": "input_required",
        "message": "Structured offer available.",
    }


async def accept_offer(state: SellerState, config: RunnableConfig) -> dict:
    if state.get("error"):
        return {}
    service = config["configurable"]["service"]
    try:
        accepted = parse_payload(
            "accept_offer", state["incoming"], AcceptOffer
        )
        previous = await service.store.get_offer(accepted.offer_id)
        if previous is None:
            raise CommerceProtocolError("offer to accept was not found")
        if previous.seller_id != service.policy.seller_id:
            raise CommerceProtocolError("offer belongs to another seller")
        if accepted.accepted_total_cents != previous.total_cents:
            raise CommerceProtocolError("accepted total does not match offer")
        if service.settlement_enabled:
            await service.validate_acceptance(
                accepted,
                token=config["configurable"].get("settlement_token"),
            )
        updated = previous.model_copy(
            update={"status": OfferStatus.ACCEPTED}
        )
        await service.store.save_offer(
            updated,
            task_id=state["task_id"],
            context_id=state["context_id"],
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "error": _error(CommerceErrorCode.CONFLICT, str(exc)),
            "task_state": "failed",
            "message": str(exc),
        }
    return {
        "offer": updated.model_dump(mode="json"),
        "task_state": "completed",
        "message": "Offer accepted.",
    }


async def reject_offer(state: SellerState, config: RunnableConfig) -> dict:
    error = state.get("error") or _error(
        CommerceErrorCode.BELOW_FLOOR, "Offer rejected."
    )
    return {
        "error": error,
        "task_state": state.get("task_state", "completed"),
        "message": error.get("message", "Offer rejected."),
    }


async def order(state: SellerState, config: RunnableConfig) -> dict:
    service = config["configurable"]["service"]
    try:
        po = parse_payload(
            "purchase_order", state["incoming"], PurchaseOrderRequest
        )
        validator = None
        if service.settlement_enabled:
            async def validator(request):
                await service.validate_purchase_order(
                    request,
                    token=config["configurable"].get("settlement_token"),
                )

        created = await service.order_service.create_order(
            po, settlement_validator=validator
        )
        # No auto-enqueued evidence: the seller cannot self-certify delivery
        # and reference evidence is submitted against the catalog.
    except Exception as exc:  # noqa: BLE001
        code = getattr(exc, "code", CommerceErrorCode.INVALID_REQUEST)
        retryable = getattr(exc, "retryable", False)
        return {
            "error": {
                "code": code.value,
                "message": str(exc),
                "retryable": retryable,
                "details": {},
            },
            "task_state": "completed",
            "message": str(exc),
        }
    return {
        "order": created.model_dump(mode="json"),
        "task_state": "completed",
        "message": "Order confirmed.",
    }


def build_graph(checkpointer=None):
    # ty cannot match TypedDicts against langgraph's StateLike protocol bound.
    builder = StateGraph(SellerState)  # ty: ignore[invalid-argument-type]
    builder.add_node("classify", classify)
    builder.add_node("prepare", prepare)
    builder.add_node("decide", decide)
    builder.add_node("finalize_offer", finalize_offer)
    builder.add_node("accept_offer", accept_offer)
    builder.add_node("reject_offer", reject_offer)
    builder.add_node("order", order)
    builder.set_entry_point("classify")
    builder.add_conditional_edges(
        "classify",
        route_kind,
        {
            "order": "order",
            "rfq": "prepare",
            "counter_offer": "prepare",
            "accept_offer": "accept_offer",
            "invalid": END,
        },
    )
    builder.add_edge("prepare", "decide")
    builder.add_conditional_edges(
        "decide",
        route_decision,
        {
            "propose": "finalize_offer",
            "counter": "finalize_offer",
            "finalize": "finalize_offer",
            "accept": "accept_offer",
            "reject": "reject_offer",
        },
    )
    builder.add_edge("finalize_offer", END)
    builder.add_edge("accept_offer", END)
    builder.add_edge("reject_offer", END)
    builder.add_edge("order", END)
    return builder.compile(checkpointer=checkpointer or MemorySaver())


def error_artifact(error: dict):
    from commerce_core.a2a_parts import make_artifact
    from commerce_core.extension import wrap_payload

    payload = CommerceError(
        code=CommerceErrorCode(error.get("code", "invalid_request")),
        message=error.get("message", "commerce error"),
        retryable=bool(error.get("retryable", False)),
        details=error.get("details") or {},
    )
    return make_artifact("commerce-error", wrap_payload("commerce_error", payload))
