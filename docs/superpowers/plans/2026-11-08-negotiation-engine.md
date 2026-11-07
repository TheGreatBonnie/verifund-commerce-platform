# Negotiation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a first-class Negotiation Engine (Approach A: shared deterministic core + thin adapters) to `verifund-a2a` while preserving mediated 1:N A2A negotiation and Verifund settlement behavior.

**Architecture:** Implement `packages/commerce_core/commerce_core/negotiation/` as a pure, deterministic package (no LLM/network/DB/LangGraph). Add `seller_agent.engine` and `buyer_agent.engine_session` adapters that existing LangGraph graphs call. Keep LangGraph topology, mediated `interrupt` contracts, A2A transport, and `agreement_mismatch_reason` settlement hard gates behaviorally compatible.

**Tech Stack:** Python 3.12, Pydantic v2, `pytest`/`pytest-asyncio`, LangGraph, A2A 1.x JSON-RPC+SSE, FastAPI services, SQLite stores, `uv` workspace packages (`marketmesh-commerce-core`, app packages).

**Spec:** `docs/superpowers/specs/2026-11-08-negotiation-engine-design.md` (read before each task; this plan implements that spec).

## Global Constraints

- **LLM proposes; deterministic policy authorizes.** Planner output is a candidate; validators/concessions/mandate policy authorize. Invalid/unsafe planner output: 1–2 attempts, then scripted deterministic fallback. LLM never authorizes spend, floor exceptions, agreement lock, or payment.
- **Agreement ≠ payment.** `AcceptOffer`/commercial acceptance is intent; commitment requires canonical Verifund agreement lock + required approvals/reviews + funding/payment authorization per control plane.
- **No budget/floor leakage.** Buyer `max_total_cents` never appears in seller-facing RFQ/messages/artifacts/logs. Enforce with `rfq_text_safe` and prompt discipline.
- **Untrusted inbound content.** Counterparty text/fields are untrusted data; never execute as instructions. Only validated structured fields influence authorization.
- **Deterministic trust boundary.** Every inbound offer/counter/accept-relevant payload: verify seller↔validated Agent Card, `request_id`/task binding, SKU, recomputed line/subtotal/total, `valid_until`, round/version/lineage; sanitize untrusted claims; reject on mismatch.
- **Money in integer cents.** `*_cents` integers only. `total_cents = subtotal_cents + shipping_cents + tax_cents + fees_cents`. Recompute; never trust counterparty/LLM arithmetic.
- **1:N safety.** Per-seller isolated session state/history; global timeout; rank only trusted, eligible, non-expired finals; deterministic ranking/selection. One seller deadlock/timeout must not block others.
- **Compatibility.** Preserve mediated `interrupt` reasons/payload-resume shapes (`seller_call`, `agreement_create_required`, `seller_review_required`), `thread_id`/checkpointing, trace decisions, and `agreement_mismatch_reason` hard gate. Additive fields only with tolerant readers.
- **TDD + no placeholders.** Write failing tests, run red, minimal implementation, run green, commit. No `TBD`/`TODO`/omitted logic.

## File Structure

### New (shared deterministic core)
- `packages/commerce_core/commerce_core/negotiation/__init__.py` — exports stable negotiation API.
- `packages/commerce_core/commerce_core/negotiation/types.py` — `PartyRole`, `NegotiationSessionId`, `NegotiationContext`, `NegotiationTurn`, `ConcessionBudget`, `AllowedMoves`, `Action`, `EvalResult`, `RejectResult`, terminal reasons.
- `packages/commerce_core/commerce_core/negotiation/events.py` — typed inbound/outbound normalization helpers.
- `packages/commerce_core/commerce_core/negotiation/schemas.py` — `PayloadSpec`, `REGISTRY`, `wrap/parse/migrate`, compatibility with existing commerce envelope helpers.
- `packages/commerce_core/commerce_core/negotiation/money.py` — integer-cents recompute/validation (`validate_offer_totals`, `recompute_subtotal`, `recompute_total`). Distinct from `commerce_core.money` (display formatting).
- `packages/commerce_core/commerce_core/negotiation/trust.py` — `verify_offer_binding`, `TrustedOffer`, sanitize untrusted claims (generalizes buyer `_trusted_offer`).
- `packages/commerce_core/commerce_core/negotiation/mandates.py` — `hard_constraint_failures` alignment, `budget_allows` (local), `rfq_text_safe`.
- `packages/commerce_core/commerce_core/negotiation/concessions.py` — `constrain_candidate`, typed `requested_changes` allowlist enforcement.
- `packages/commerce_core/commerce_core/negotiation/deadlock.py` — `detect` → `continue|propose_alternative|escalate_human|terminate`.
- `packages/commerce_core/commerce_core/negotiation/tradeoff.py` — bounded deterministic feasible alternatives.
- `packages/commerce_core/commerce_core/negotiation/artifacts.py` — sanitized `negotiation_history` artifact builder (no budget/secrets/tokens).

### New (app adapters)
- `apps/seller_agent/seller_agent/engine.py` — `SellerNegotiationEngine` wrapping classify/prepare/decide/constrain/finalize/accept.
- `apps/buyer_agent/buyer_agent/engine_session.py` — `BuyerNegotiationSessionEngine` for per-seller trust/eval/action/counter building.

### Modified (wrap, preserve behavior)
- `packages/commerce_core/commerce_core/contracts.py` — additive optional fields (`CounterOffer.in_response_to_offer_id`, `idempotency_key`; `AcceptOffer.idempotency_key`, `accepted_at`; `Offer.parent_offer_id/supersedes_offer_id`), typed `requested_changes` validation; tolerant defaults.
- `apps/seller_agent/seller_agent/graph.py` — delegate to `SellerNegotiationEngine` where safe; keep topology/routes/state keys.
- `apps/seller_agent/seller_agent/planner.py` — align `SellerDecisionContext`/validation with engine `AllowedMoves` (additive).
- `apps/buyer_agent/buyer_agent/graph.py` — extract trust/counter/deadlock helpers to session engine calls; keep interrupts, settlement, traces, state keys.
- `apps/buyer_agent/buyer_agent/planner.py` — preserve `CounterChoice` schema and fallback; enforce allowed targets via engine.

### Tests (new/updated)
- `tests/unit/negotiation/test_money.py`
- `tests/unit/negotiation/test_trust.py`
- `tests/unit/negotiation/test_mandates.py`
- `tests/unit/negotiation/test_concessions.py`
- `tests/unit/negotiation/test_deadlock.py`
- `tests/unit/negotiation/test_schemas.py`
- `tests/unit/negotiation/test_artifacts.py`
- `tests/unit/test_seller_engine.py`
- `tests/unit/test_buyer_engine_session.py`
- `tests/protocol/test_seller_negotiation.py` — keep passing (characterization); extend only with compatible cases.

## Task 1: Phase 0 — Characterization baseline (existing behavior)

**Files:**
- Create: `tests/unit/test_negotiation_characterization.py`
- Read: `packages/commerce_core/commerce_core/contracts.py`, `apps/buyer_agent/buyer_agent/graph.py`, `tests/protocol/test_seller_negotiation.py`

**Interfaces:**
- Consumes: `commerce_core.contracts` (`Offer`, `OfferLineItem`, `OfferTerms`, `OfferStatus`), `buyer_agent.graph._safe_text` behavior (import carefully; if unavailable in test context, assert equivalent invariant via local helper mirroring current logic).
- Produces: baseline tests that must remain green through Phases 1–3.

- [ ] **Step 1: Write failing characterization tests**

```python
from datetime import UTC, datetime, timedelta

from commerce_core.contracts import Offer, OfferLineItem, OfferStatus, OfferTerms


def make_offer(*, total_cents: int = 226800, valid_until: datetime | None = None) -> Offer:
    return Offer(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="seller-a",
        seller_name="Seller A",
        seller_rating=4.5,
        task_id="task-1",
        context_id="run-1",
        line_items=[
            OfferLineItem(
                sku="MM-WIRELESS-HEADPHONES",
                name="Wireless Headphones",
                quantity=12,
                unit_price_cents=18900,
                list_unit_price_cents=19900,
                warranty_addon_cents=0,
            )
        ],
        subtotal_cents=226800,
        shipping_cents=0,
        tax_cents=0,
        fees_cents=0,
        total_cents=total_cents,
        delivery_days=7,
        warranty_months=12,
        returns_days=30,
        valid_until=valid_until or (datetime.now(UTC) + timedelta(days=1)),
        terms=OfferTerms(sustainability_certified=True, stock_confidence=1.0),
        status=OfferStatus.PROPOSED,
        round=1,
    )


def test_offer_totals_validate_current_contract():
    offer = make_offer()
    assert offer.total_cents == 226800
    assert offer.subtotal_cents == 12 * 18900


def test_offer_rejects_mismatched_total():
    try:
        make_offer(total_cents=1)
    except ValueError as exc:
        assert "total_cents" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run tests to verify they pass (baseline) or reveal environment issues**

Run: `uv run pytest tests/unit/test_negotiation_characterization.py -v`  
Expected: PASS (these encode current behavior).

- [ ] **Step 3: Add budget-safety characterization**

Append to `tests/unit/test_negotiation_characterization.py`:

```python
import re


def rfq_text_safe_current(text: str, max_total_cents: int) -> bool:
    if not text:
        return False
    budget_dollars = f"{max_total_cents // 100}"
    budget_cents = str(max_total_cents)
    return "max_total_cents" not in text and budget_dollars not in text and budget_cents not in text


def test_budget_safety_rejects_disclosed_budget():
    assert rfq_text_safe_current("Quote 12 units", 340000) is True
    assert rfq_text_safe_current("Budget is 3400 dollars", 340000) is False
    assert rfq_text_safe_current("max_total_cents 340000", 340000) is False
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_negotiation_characterization.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_negotiation_characterization.py
git commit -m "test(negotiation): add characterization baseline for totals and budget safety"
```

## Task 2: Phase 1 — `commerce_core.negotiation` package skeleton + money

**Files:**
- Create: `packages/commerce_core/commerce_core/negotiation/__init__.py`
- Create: `packages/commerce_core/commerce_core/negotiation/money.py`
- Create: `tests/unit/negotiation/__init__.py`
- Test: `tests/unit/negotiation/test_money.py`

**Interfaces:**
- Consumes: `commerce_core.contracts.Offer`, `OfferLineItem`.
- Produces: `recompute_subtotal(line_items)->int`, `recompute_total(subtotal_cents, shipping_cents, tax_cents=0, fees_cents=0)->int`, `validate_offer_amounts(offer)->tuple[bool,str|None]`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime, timedelta

from commerce_core.contracts import Offer, OfferLineItem, OfferStatus, OfferTerms
from commerce_core.negotiation.money import (
    recompute_subtotal,
    recompute_total,
    validate_offer_amounts,
)


def sample_offer(**updates):
    data = dict(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="seller-a",
        seller_name="Seller A",
        seller_rating=4.5,
        line_items=[
            OfferLineItem(
                sku="SKU",
                name="Item",
                quantity=2,
                unit_price_cents=1000,
                list_unit_price_cents=1200,
                warranty_addon_cents=50,
            )
        ],
        subtotal_cents=2100,
        shipping_cents=100,
        tax_cents=20,
        fees_cents=5,
        total_cents=2225,
        delivery_days=3,
        warranty_months=12,
        returns_days=30,
        valid_until=datetime.now(UTC) + timedelta(days=1),
        terms=OfferTerms(),
        status=OfferStatus.PROPOSED,
        round=1,
    )
    data.update(updates)
    return Offer(**data)


def test_recompute_subtotal_and_total():
    offer = sample_offer()
    assert recompute_subtotal(offer.line_items) == 2100
    assert recompute_total(2100, 100, 20, 5) == 2225


def test_validate_offer_amounts_accepts_consistent_offer():
    ok, reason = validate_offer_amounts(sample_offer())
    assert ok is True
    assert reason is None


def test_validate_offer_amounts_rejects_inconsistent_total():
    offer = sample_offer().model_copy(update={"total_cents": 9999})
    ok, reason = validate_offer_amounts(offer)
    assert ok is False
    assert "total" in (reason or "").lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/negotiation/test_money.py -v`  
Expected: FAIL (module `commerce_core.negotiation.money` missing).

- [ ] **Step 3: Write minimal implementation**

`packages/commerce_core/commerce_core/negotiation/__init__.py`:
```python
"""Deterministic negotiation primitives (no LLM/network/DB/LangGraph)."""

from commerce_core.negotiation.money import (
    recompute_subtotal,
    recompute_total,
    validate_offer_amounts,
)

__all__ = ["recompute_subtotal", "recompute_total", "validate_offer_amounts"]
```

`packages/commerce_core/commerce_core/negotiation/money.py`:
```python
from __future__ import annotations

from collections.abc import Sequence

from commerce_core.contracts import Offer, OfferLineItem


def recompute_subtotal(line_items: Sequence[OfferLineItem]) -> int:
    return sum(
        (item.unit_price_cents + item.warranty_addon_cents) * item.quantity
        for item in line_items
    )


def recompute_total(
    subtotal_cents: int,
    shipping_cents: int,
    tax_cents: int = 0,
    fees_cents: int = 0,
) -> int:
    return subtotal_cents + shipping_cents + tax_cents + fees_cents


def validate_offer_amounts(offer: Offer) -> tuple[bool, str | None]:
    subtotal = recompute_subtotal(offer.line_items)
    if subtotal != offer.subtotal_cents:
        return False, "subtotal_cents does not match line items"
    total = recompute_total(
        offer.subtotal_cents, offer.shipping_cents, offer.tax_cents, offer.fees_cents
    )
    if total != offer.total_cents:
        return False, "total_cents does not match subtotal, shipping, tax, fees"
    return True, None
```

`tests/unit/negotiation/__init__.py`: empty file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/negotiation/test_money.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/negotiation/__init__.py packages/commerce_core/commerce_core/negotiation/money.py tests/unit/negotiation/__init__.py tests/unit/negotiation/test_money.py
git commit -m "feat(commerce-core): add negotiation money recomputation helpers"
```

## Task 3: Phase 1 — mandates (budget safety + hard constraints)

**Files:**
- Create: `packages/commerce_core/commerce_core/negotiation/mandates.py`
- Test: `tests/unit/negotiation/test_mandates.py`
- Modify: `packages/commerce_core/commerce_core/negotiation/__init__.py` (export)

**Interfaces:**
- Consumes: `commerce_core.contracts.Mandate`, `Offer`.
- Produces: `rfq_text_safe(text, max_total_cents)->bool`, `budget_allows(total_cents, max_total_cents)->bool`, `hard_constraint_failures(mandate, offer)->list[str]`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime, timedelta

from commerce_core.contracts import (
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    Preferences,
)
from commerce_core.negotiation.mandates import (
    budget_allows,
    hard_constraint_failures,
    rfq_text_safe,
)


def mandate(max_total_cents: int = 340000) -> Mandate:
    return Mandate(
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Headphones",
        product_sku="SKU",
        quantity=12,
        max_total_cents=max_total_cents,
        deadline_days=14,
        min_warranty_months=12,
        min_returns_days=30,
        preferences=Preferences(sustainability=False, color="black"),
    )


def offer(*, total_cents: int = 2400, sku: str = "SKU", warranty: int = 12, returns: int = 30):
    return Offer(
        offer_id="o1",
        request_id="r1",
        seller_id="s1",
        seller_name="S1",
        seller_rating=4.0,
        line_items=[OfferLineItem(sku=sku, name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)],
        subtotal_cents=2400,
        shipping_cents=0,
        total_cents=total_cents,
        delivery_days=7,
        warranty_months=warranty,
        returns_days=returns,
        valid_until=datetime.now(UTC) + timedelta(days=1),
        terms=OfferTerms(),
        status=OfferStatus.PROPOSED,
        round=1,
    )


def test_rfq_text_safe_blocks_budget_disclosure():
    assert rfq_text_safe("Please quote 12 units", 340000) is True
    assert rfq_text_safe("budget 3400", 340000) is False
    assert rfq_text_safe("max_total_cents=340000", 340000) is False
    assert rfq_text_safe("", 340000) is False


def test_budget_allows_and_hard_constraints():
    m = mandate()
    assert budget_allows(340000, m.max_total_cents) is True
    assert budget_allows(340001, m.max_total_cents) is False
    assert hard_constraint_failures(m, offer()) == []
    assert hard_constraint_failures(m, offer(total_cents=340001)) == ["over_budget"]
    assert "sku_mismatch" in hard_constraint_failures(m, offer(sku="OTHER"))
    assert "warranty_too_short" in hard_constraint_failures(m, offer(warranty=6))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/negotiation/test_mandates.py -v`  
Expected: FAIL (module missing).

- [ ] **Step 3: Write minimal implementation**

`packages/commerce_core/commerce_core/negotiation/mandates.py`:
```python
from __future__ import annotations

from commerce_core.contracts import Mandate, Offer


def rfq_text_safe(text: str, max_total_cents: int) -> bool:
    if not text:
        return False
    budget_dollars = f"{max_total_cents // 100}"
    budget_cents = str(max_total_cents)
    return (
        "max_total_cents" not in text
        and budget_dollars not in text
        and budget_cents not in text
    )


def budget_allows(total_cents: int, max_total_cents: int) -> bool:
    return total_cents <= max_total_cents


def hard_constraint_failures(mandate: Mandate, offer: Offer) -> list[str]:
    failures: list[str] = []
    if not budget_allows(offer.total_cents, mandate.max_total_cents):
        failures.append("over_budget")
    if mandate.product_sku and any(item.sku != mandate.product_sku for item in offer.line_items):
        failures.append("sku_mismatch")
    if offer.warranty_months < mandate.min_warranty_months:
        failures.append("warranty_too_short")
    if offer.returns_days < mandate.min_returns_days:
        failures.append("returns_too_short")
    if offer.delivery_days > mandate.deadline_days:
        failures.append("delivery_too_slow")
    qty = sum(item.quantity for item in offer.line_items)
    if qty != mandate.quantity:
        failures.append("quantity_mismatch")
    return failures
```

Update `packages/commerce_core/commerce_core/negotiation/__init__.py` to export `rfq_text_safe`, `budget_allows`, `hard_constraint_failures`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/negotiation/test_mandates.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/negotiation/mandates.py packages/commerce_core/commerce_core/negotiation/__init__.py tests/unit/negotiation/test_mandates.py
git commit -m "feat(commerce-core): add negotiation mandate and budget-safety checks"
```

## Task 4: Phase 1 — trust boundary (generalized `_trusted_offer`)

**Files:**
- Create: `packages/commerce_core/commerce_core/negotiation/trust.py`
- Test: `tests/unit/negotiation/test_trust.py`
- Modify: `packages/commerce_core/commerce_core/negotiation/__init__.py`

**Interfaces:**
- Consumes: `commerce_core.contracts.Offer`, validated seller metadata `seller_id`, `request_id`, optional `sku`, `now_utc`, `seller_rating`, `sustainability_certified`.
- Produces: `TrustReject(code, reason)`, `verify_offer_binding(...)->tuple[Offer|None, TrustReject|None]` returning a sanitized trusted copy or rejection.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime, timedelta

from commerce_core.contracts import Offer, OfferLineItem, OfferStatus, OfferTerms
from commerce_core.negotiation.trust import verify_offer_binding


def raw_offer(**updates):
    data = dict(
        offer_id="o1",
        request_id="req-1",
        seller_id="seller-a",
        seller_name="Seller A",
        seller_rating=1.0,
        line_items=[OfferLineItem(sku="SKU", name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)],
        subtotal_cents=2400,
        shipping_cents=0,
        total_cents=2400,
        delivery_days=7,
        warranty_months=12,
        returns_days=30,
        valid_until=datetime.now(UTC) + timedelta(days=1),
        terms=OfferTerms(sustainability_certified=False, stock_confidence=0.5),
        status=OfferStatus.PROPOSED,
        round=1,
    )
    data.update(updates)
    return Offer(**data)


def test_verify_offer_binding_sanitizes_untrusted_claims():
    trusted, reject = verify_offer_binding(
        raw_offer(),
        expected_seller_id="seller-a",
        expected_request_id="req-1",
        expected_sku="SKU",
        validated_rating=4.8,
        validated_sustainability=True,
        now_utc=datetime.now(UTC),
    )
    assert reject is None
    assert trusted is not None
    assert trusted.seller_rating == 4.8
    assert trusted.terms.sustainability_certified is True


def test_verify_offer_binding_rejects_mismatch_and_expiry():
    _, reject = verify_offer_binding(
        raw_offer(seller_id="evil"),
        expected_seller_id="seller-a",
        expected_request_id="req-1",
        expected_sku="SKU",
        validated_rating=4.8,
        validated_sustainability=True,
        now_utc=datetime.now(UTC),
    )
    assert reject is not None
    assert reject.code == "binding_mismatch"

    _, reject = verify_offer_binding(
        raw_offer(valid_until=datetime.now(UTC) - timedelta(seconds=1)),
        expected_seller_id="seller-a",
        expected_request_id="req-1",
        expected_sku="SKU",
        validated_rating=4.8,
        validated_sustainability=True,
        now_utc=datetime.now(UTC),
    )
    assert reject is not None
    assert reject.code == "offer_expired"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/negotiation/test_trust.py -v`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`packages/commerce_core/commerce_core/negotiation/trust.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from commerce_core.contracts import Offer
from commerce_core.negotiation.money import validate_offer_amounts


@dataclass(frozen=True)
class TrustReject:
    code: str
    reason: str
    retryable: bool = False


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def verify_offer_binding(
    offer: Offer,
    *,
    expected_seller_id: str,
    expected_request_id: str,
    expected_sku: str | None,
    validated_rating: float,
    validated_sustainability: bool,
    now_utc: datetime | None = None,
) -> tuple[Offer | None, TrustReject | None]:
    now = _as_utc(now_utc or datetime.now(UTC))
    if offer.seller_id != expected_seller_id:
        return None, TrustReject("binding_mismatch", "offer seller_id does not match validated card")
    if offer.request_id != expected_request_id:
        return None, TrustReject("binding_mismatch", "offer request_id does not match request")
    if expected_sku and any(item.sku != expected_sku for item in offer.line_items):
        return None, TrustReject("binding_mismatch", "offer SKU does not match requested product")
    ok, reason = validate_offer_amounts(offer)
    if not ok:
        return None, TrustReject("binding_mismatch", reason or "offer totals are invalid")
    if _as_utc(offer.valid_until) <= now:
        return None, TrustReject("offer_expired", "offer is expired")
    trusted = offer.model_copy(
        update={
            "seller_rating": validated_rating,
            "terms": offer.terms.model_copy(
                update={"sustainability_certified": validated_sustainability}
            ),
        }
    )
    return trusted, None
```

Export `TrustReject`, `verify_offer_binding` from `__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/negotiation/test_trust.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/negotiation/trust.py packages/commerce_core/commerce_core/negotiation/__init__.py tests/unit/negotiation/test_trust.py
git commit -m "feat(commerce-core): add negotiation trust boundary for offers"
```

## Task 5: Phase 1 — concessions (typed changes + allowed moves)

**Files:**
- Create: `packages/commerce_core/commerce_core/negotiation/concessions.py`
- Test: `tests/unit/negotiation/test_concessions.py`
- Modify: `packages/commerce_core/commerce_core/contracts.py` (tighten `CounterOffer.requested_changes` validation, additive lineage fields)
- Modify: `packages/commerce_core/commerce_core/negotiation/__init__.py`

**Interfaces:**
- Consumes: candidate action/target/changes, `allowed_price_targets`, `allowed_warranty_months`, `floor_unit_price_cents`, `max_rounds/current_round`.
- Produces: `AllowedDecision` or `TrustReject`-like `RejectResult(code,reason)`, `validate_requested_changes(changes, allowed_warranty_months, allow_split)->tuple[dict|None,str|None]`.

- [ ] **Step 1: Write the failing test**

```python
from commerce_core.negotiation.concessions import (
    constrain_buyer_counter,
    validate_requested_changes,
)


def test_validate_requested_changes_typed_allowlist():
    ok, err = validate_requested_changes({"warranty_months": 24}, [12, 24], True)
    assert err is None
    assert ok == {"warranty_months": 24}

    ok, err = validate_requested_changes({"unknown": 1}, [12, 24], True)
    assert ok is None
    assert err is not None

    ok, err = validate_requested_changes({"warranty_months": 36}, [12, 24], True)
    assert ok is None
    assert "warranty" in (err or "").lower()


def test_constrain_buyer_counter_requires_allowed_target():
    decision, reject = constrain_buyer_counter(
        target_unit_price_cents=18500,
        allowed_targets=[18300],
        requested_changes={},
        allowed_warranty_months=[12, 24],
        allow_split=True,
    )
    assert decision is None
    assert reject is not None

    decision, reject = constrain_buyer_counter(
        target_unit_price_cents=18300,
        allowed_targets=[18300],
        requested_changes={"split_shipment": True},
        allowed_warranty_months=[12, 24],
        allow_split=True,
    )
    assert reject is None
    assert decision is not None
    assert decision.target_unit_price_cents == 18300
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/negotiation/test_concessions.py -v`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`packages/commerce_core/commerce_core/negotiation/concessions.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ALLOWED_REQUESTED_CHANGE_KEYS = {
    "warranty_months",
    "split_shipment",
    "shipping_cents",
    "delivery_days",
}


@dataclass(frozen=True)
class RejectResult:
    code: str
    reason: str
    retryable: bool = False


@dataclass(frozen=True)
class AllowedBuyerCounter:
    target_unit_price_cents: int
    requested_changes: dict[str, int | bool]
    rationale: str = ""


def validate_requested_changes(
    changes: dict[str, Any],
    allowed_warranty_months: list[int],
    allow_split: bool,
) -> tuple[dict[str, int | bool] | None, str | None]:
    unknown = set(changes) - ALLOWED_REQUESTED_CHANGE_KEYS
    if unknown:
        return None, f"unsupported requested changes: {sorted(unknown)}"
    normalized: dict[str, int | bool] = {}
    if "warranty_months" in changes:
        value = changes["warranty_months"]
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "warranty_months must be an integer"
        if value not in allowed_warranty_months:
            return None, "requested warranty is not supported"
        normalized["warranty_months"] = value
    if "split_shipment" in changes:
        value = changes["split_shipment"]
        if not isinstance(value, bool):
            return None, "split_shipment must be a boolean"
        if value and not allow_split:
            return None, "split shipment is not supported"
        normalized["split_shipment"] = value
    if "shipping_cents" in changes:
        value = changes["shipping_cents"]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None, "shipping_cents must be a non-negative integer"
        normalized["shipping_cents"] = value
    if "delivery_days" in changes:
        value = changes["delivery_days"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None, "delivery_days must be a positive integer"
        normalized["delivery_days"] = value
    return normalized, None


def constrain_buyer_counter(
    *,
    target_unit_price_cents: int,
    allowed_targets: list[int],
    requested_changes: dict[str, Any],
    allowed_warranty_months: list[int],
    allow_split: bool,
    rationale: str = "",
) -> tuple[AllowedBuyerCounter | None, RejectResult | None]:
    if target_unit_price_cents not in allowed_targets:
        return None, RejectResult(
            "unsupported_constraint", "counter target is outside allowed list"
        )
    normalized, err = validate_requested_changes(
        requested_changes, allowed_warranty_months, allow_split
    )
    if err is not None or normalized is None:
        return None, RejectResult("unsupported_constraint", err or "invalid requested changes")
    return AllowedBuyerCounter(target_unit_price_cents, normalized, rationale), None
```

Update `packages/commerce_core/commerce_core/contracts.py` `CounterOffer` (additive, compatible):
```python
class CounterOffer(CommerceModel):
    schema_version: str = "1.0"
    negotiation_round: int = Field(ge=1)
    target_unit_price_cents: int | None = Field(default=None, gt=0)
    requested_changes: dict[str, str | int | bool] = Field(default_factory=dict)
    rationale: str = ""
    in_response_to_offer_id: str | None = None
    idempotency_key: str | None = None
```
(Keep value typing permissive for wire compatibility; engine/concessions enforce typed allowlist.)

Export new symbols from `negotiation/__init__.py`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/negotiation/test_concessions.py tests/unit/test_negotiation_characterization.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/negotiation/concessions.py packages/commerce_core/commerce_core/negotiation/__init__.py packages/commerce_core/commerce_core/contracts.py tests/unit/negotiation/test_concessions.py
git commit -m "feat(commerce-core): add concession constraints and typed counter changes"
```

## Task 6: Phase 1 — deadlock detection

**Files:**
- Create: `packages/commerce_core/commerce_core/negotiation/deadlock.py`
- Test: `tests/unit/negotiation/test_deadlock.py`
- Modify: `packages/commerce_core/commerce_core/negotiation/__init__.py`

**Interfaces:**
- Produces: `DeadlockDecision(outcome, reason)` where outcome in `continue|propose_alternative|escalate_human|terminate`; `detect_deadlock(round, max_rounds, has_feasible_move, has_non_price_alternative, expired=False)->DeadlockDecision`.

- [ ] **Step 1: Write the failing test**

```python
from commerce_core.negotiation.deadlock import detect_deadlock


def test_deadlock_continue_and_terminate():
    assert detect_deadlock(round=1, max_rounds=3, has_feasible_move=True, has_non_price_alternative=True).outcome == "continue"
    assert detect_deadlock(round=3, max_rounds=3, has_feasible_move=False, has_non_price_alternative=False).outcome == "terminate"
    assert detect_deadlock(round=2, max_rounds=3, has_feasible_move=False, has_non_price_alternative=True).outcome == "propose_alternative"
    assert detect_deadlock(round=1, max_rounds=3, has_feasible_move=True, has_non_price_alternative=False, expired=True).outcome == "terminate"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/negotiation/test_deadlock.py -v`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/negotiation/test_deadlock.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/negotiation/deadlock.py packages/commerce_core/commerce_core/negotiation/__init__.py tests/unit/negotiation/test_deadlock.py
git commit -m "feat(commerce-core): add deterministic deadlock detection"
```

## Task 7: Phase 1 — schema registry + sanitized history artifact

**Files:**
- Create: `packages/commerce_core/commerce_core/negotiation/schemas.py`
- Create: `packages/commerce_core/commerce_core/negotiation/artifacts.py`
- Test: `tests/unit/negotiation/test_schemas.py`
- Test: `tests/unit/negotiation/test_artifacts.py`
- Modify: `packages/commerce_core/commerce_core/negotiation/__init__.py`

**Interfaces:**
- Produces: `PAYLOAD_NAMES` registry/list, `is_known_payload(name)->bool`; `build_negotiation_history_artifact(turns, *, max_total_cents=None)->dict` that never includes budget/secrets/tokens.

- [ ] **Step 1: Write the failing tests**

`tests/unit/negotiation/test_schemas.py`:
```python
from commerce_core.negotiation.schemas import PAYLOAD_NAMES, is_known_payload


def test_known_payloads():
    for name in ["rfq", "offer", "counter_offer", "accept_offer", "purchase_order", "order", "commerce_error"]:
        assert is_known_payload(name)
    assert "rfq" in PAYLOAD_NAMES
    assert not is_known_payload("not_a_payload")
```

`tests/unit/negotiation/test_artifacts.py`:
```python
from commerce_core.negotiation.artifacts import build_negotiation_history_artifact


def test_negotiation_history_artifact_redacts_budget():
    payload = build_negotiation_history_artifact(
        [{"round": 1, "kind": "offer", "offer_id": "o1", "total_cents": 100, "source": "scripted"}],
        max_total_cents=9999,
    )
    text = str(payload)
    assert "9999" not in text
    assert "max_total_cents" not in text
    assert payload["turns"][0]["offer_id"] == "o1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/negotiation/test_schemas.py tests/unit/negotiation/test_artifacts.py -v`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`schemas.py`:
```python
from __future__ import annotations

PAYLOAD_NAMES = (
    "rfq",
    "offer",
    "counter_offer",
    "accept_offer",
    "purchase_order",
    "order",
    "commerce_error",
    "negotiation_history",
)


def is_known_payload(name: str) -> bool:
    return name in PAYLOAD_NAMES
```

`artifacts.py`:
```python
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
```

Export `PAYLOAD_NAMES`, `is_known_payload`, `build_negotiation_history_artifact`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/negotiation/test_schemas.py tests/unit/negotiation/test_artifacts.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/negotiation/schemas.py packages/commerce_core/commerce_core/negotiation/artifacts.py packages/commerce_core/commerce_core/negotiation/__init__.py tests/unit/negotiation/test_schemas.py tests/unit/negotiation/test_artifacts.py
git commit -m "feat(commerce-core): add negotiation payload registry and sanitized history artifact"
```

## Task 8: Phase 2 — seller engine adapter (wrap, preserve topology)

**Files:**
- Create: `apps/seller_agent/seller_agent/engine.py`
- Create: `tests/unit/test_seller_engine.py`
- Modify: `apps/seller_agent/seller_agent/graph.py` (delegate prepare/decide/finalize validation paths to engine helpers; keep node names/routes)

**Interfaces:**
- Consumes: `SellerPolicy` (`commerce_core.pricing`), `SellerPlanner`/`ScriptedSellerPlanner`, `commerce_core.contracts`, `commerce_core.negotiation.{concessions,deadlock,money}`.
- Produces: `SellerNegotiationEngine.validate_decision(decision, *, allowed_prices, allowed_warranty_months, floor_unit_price_cents)->bool`, `status_for_offer(round, max_rounds, unit_price_cents, floor_unit_price_cents, next_prices)->OfferStatus`, and graph uses these (no behavior regression for existing protocol tests).

- [ ] **Step 1: Write the failing test**

```python
from commerce_core.contracts import OfferStatus
from seller_agent.engine import SellerNegotiationEngine
from seller_agent.planner import SellerDecision


def test_seller_engine_validate_and_status():
    engine = SellerNegotiationEngine()
    ok = engine.validate_decision(
        SellerDecision(action="counter", unit_price_cents=18500, warranty_months=12, rationale="x"),
        allowed_prices=[18500],
        allowed_warranty_months=[12, 24],
        floor_unit_price_cents=18000,
    )
    assert ok is True
    bad = engine.validate_decision(
        SellerDecision(action="counter", unit_price_cents=18400, warranty_months=12, rationale="x"),
        allowed_prices=[18500],
        allowed_warranty_months=[12, 24],
        floor_unit_price_cents=18000,
    )
    assert bad is False
    assert engine.status_for_offer(
        round=3, max_rounds=3, unit_price_cents=18500, floor_unit_price_cents=18000, next_prices=[18400]
    ) == OfferStatus.FINAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_engine.py -v`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`apps/seller_agent/seller_agent/engine.py`:
```python
from __future__ import annotations

from commerce_core.contracts import OfferStatus
from seller_agent.planner import SellerDecision


class SellerNegotiationEngine:
    def validate_decision(
        self,
        decision: SellerDecision,
        *,
        allowed_prices: list[int],
        allowed_warranty_months: list[int],
        floor_unit_price_cents: int,
    ) -> bool:
        if decision.action not in {"propose", "counter", "accept", "reject"}:
            return False
        if decision.warranty_months not in allowed_warranty_months:
            return False
        if decision.unit_price_cents < floor_unit_price_cents:
            return False
        if decision.action in {"propose", "counter"}:
            return decision.unit_price_cents in allowed_prices
        return True

    def status_for_offer(
        self,
        *,
        round: int,
        max_rounds: int,
        unit_price_cents: int,
        floor_unit_price_cents: int,
        next_prices: list[int],
    ) -> OfferStatus:
        if round >= max_rounds:
            return OfferStatus.FINAL
        if unit_price_cents == floor_unit_price_cents:
            return OfferStatus.FINAL
        if next_prices == [unit_price_cents]:
            return OfferStatus.FINAL
        return OfferStatus.PROPOSED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_seller_engine.py -v`  
Expected: PASS.

- [ ] **Step 5: Wire into `seller_agent/graph.py` (minimal, no behavior change)**

In `graph.py`, replace local `_valid_decision` body to delegate:
```python
from seller_agent.engine import SellerNegotiationEngine

_SELLER_ENGINE = SellerNegotiationEngine()

def _valid_decision(decision: SellerDecision, context: SellerDecisionContext) -> bool:
    return _SELLER_ENGINE.validate_decision(
        decision,
        allowed_prices=context.allowed_prices,
        allowed_warranty_months=context.allowed_warranty_months,
        floor_unit_price_cents=context.policy.floor_unit_price_cents,
    )
```
And in `_offer_from_quote`, replace status calculation with:
```python
    status = _SELLER_ENGINE.status_for_offer(
        round=state.get("current_round", 1),
        max_rounds=policy.max_rounds,
        unit_price_cents=decision.unit_price_cents,
        floor_unit_price_cents=policy.floor_unit_price_cents,
        next_prices=policy.next_price_options(decision.unit_price_cents),
    )
```

- [ ] **Step 6: Run characterization/protocol-relevant tests**

Run: `uv run pytest tests/unit/test_seller_engine.py tests/protocol/test_seller_negotiation.py tests/unit/test_negotiation_characterization.py -v`  
Expected: PASS (protocol test requires existing fixtures; if fixtures unavailable in this environment, at minimum unit tests PASS — do not weaken assertions).

- [ ] **Step 7: Commit**

```bash
git add apps/seller_agent/seller_agent/engine.py apps/seller_agent/seller_agent/graph.py tests/unit/test_seller_engine.py
git commit -m "refactor(seller): delegate decision validation and offer status to seller engine"
```

## Task 9: Phase 3 — buyer session engine (trust + budget-safe RFQ)

**Files:**
- Create: `apps/buyer_agent/buyer_agent/engine_session.py`
- Create: `tests/unit/test_buyer_engine_session.py`
- Modify: `apps/buyer_agent/buyer_agent/graph.py` (delegate `_safe_text` and `_trusted_offer` to engine/session helpers; preserve function signatures/behavior)

**Interfaces:**
- Consumes: `commerce_core.contracts.Mandate`, `Offer`, `commerce_core.negotiation.{mandates,trust}`.
- Produces: `BuyerNegotiationSessionEngine.rfq_text_safe(text, mandate)->bool`, `trusted_offer(offer, *, mandate, expected_seller_id, expected_request_id, validated_rating, validated_sustainability, now_utc)->(Offer|None, str|None)`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime, timedelta

from commerce_core.contracts import Mandate, Offer, OfferLineItem, OfferStatus, OfferTerms, Preferences
from buyer_agent.engine_session import BuyerNegotiationSessionEngine


def mandate():
    return Mandate(
        run_id="run-1", category="consumer-electronics", product_hint="H", product_sku="SKU",
        quantity=12, max_total_cents=340000, deadline_days=14, min_warranty_months=12, min_returns_days=30,
        preferences=Preferences(),
    )


def offer():
    return Offer(
        offer_id="o1", request_id="req-1", seller_id="s1", seller_name="S1", seller_rating=1.0,
        line_items=[OfferLineItem(sku="SKU", name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)],
        subtotal_cents=2400, shipping_cents=0, total_cents=2400, delivery_days=7, warranty_months=12, returns_days=30,
        valid_until=datetime.now(UTC) + timedelta(days=1), terms=OfferTerms(sustainability_certified=False),
        status=OfferStatus.PROPOSED, round=1,
    )


def test_buyer_session_budget_safety_and_trust():
    engine = BuyerNegotiationSessionEngine()
    m = mandate()
    assert engine.rfq_text_safe("Quote 12 units", m) is True
    assert engine.rfq_text_safe("total is 3400", m) is False
    trusted, err = engine.trusted_offer(
        offer(), mandate=m, expected_seller_id="s1", expected_request_id="req-1",
        validated_rating=4.9, validated_sustainability=True, now_utc=datetime.now(UTC),
    )
    assert err is None
    assert trusted is not None
    assert trusted.seller_rating == 4.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_buyer_engine_session.py -v`  
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`apps/buyer_agent/buyer_agent/engine_session.py`:
```python
from __future__ import annotations

from datetime import datetime

from commerce_core.contracts import Mandate, Offer
from commerce_core.negotiation.mandates import rfq_text_safe
from commerce_core.negotiation.trust import verify_offer_binding


class BuyerNegotiationSessionEngine:
    def rfq_text_safe(self, text: str, mandate: Mandate) -> bool:
        return rfq_text_safe(text, mandate.max_total_cents)

    def trusted_offer(
        self,
        offer: Offer,
        *,
        mandate: Mandate,
        expected_seller_id: str,
        expected_request_id: str,
        validated_rating: float,
        validated_sustainability: bool,
        now_utc: datetime | None = None,
    ) -> tuple[Offer | None, str | None]:
        trusted, reject = verify_offer_binding(
            offer,
            expected_seller_id=expected_seller_id,
            expected_request_id=expected_request_id,
            expected_sku=mandate.product_sku,
            validated_rating=validated_rating,
            validated_sustainability=validated_sustainability,
            now_utc=now_utc,
        )
        if reject is None:
            return trusted, None
        return None, reject.reason
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_buyer_engine_session.py -v`  
Expected: PASS.

- [ ] **Step 5: Wire into `buyer_agent/graph.py` (preserve signatures/behavior)**

Add near top-level helpers:
```python
from buyer_agent.engine_session import BuyerNegotiationSessionEngine

_BUYER_SESSION_ENGINE = BuyerNegotiationSessionEngine()
```
Replace `_safe_text`:
```python
def _safe_text(text: str, mandate: Mandate) -> bool:
    return _BUYER_SESSION_ENGINE.rfq_text_safe(text, mandate)
```
Replace `_trusted_offer` to delegate while preserving its return contract and mandate/endpoint usage:
```python
def _trusted_offer(offer: Offer, mandate: Mandate, endpoint: Any, request_id: str) -> tuple[Offer | None, str | None]:
    return _BUYER_SESSION_ENGINE.trusted_offer(
        offer,
        mandate=mandate,
        expected_seller_id=endpoint.seller_id,
        expected_request_id=request_id,
        validated_rating=endpoint.rating,
        validated_sustainability=endpoint.sustainability_certified,
        now_utc=datetime.now(UTC),
    )
```
(If `datetime.now(UTC)` import/usage differs locally, match file style.)

- [ ] **Step 6: Run focused tests**

Run: `uv run pytest tests/unit/test_buyer_engine_session.py tests/unit/test_negotiation_characterization.py tests/unit/negotiation -v`  
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/buyer_agent/buyer_agent/engine_session.py apps/buyer_agent/buyer_agent/graph.py tests/unit/test_buyer_engine_session.py
git commit -m "refactor(buyer): delegate RFQ safety and offer trust to session engine"
```

## Task 10: Phase 4 — contract hardening & docs touch-up

**Files:**
- Modify: `packages/commerce_core/commerce_core/contracts.py` (additive `AcceptOffer` idempotency/accepted_at, `Offer` lineage fields)
- Create: `tests/unit/negotiation/test_contract_compat.py`
- Modify: `docs/superpowers/specs/2026-11-08-negotiation-engine-design.md` only if implementation reveals a necessary, explicitly-approved correction (default: no spec changes).

**Interfaces:**
- Produces: backward-compatible contract parsing/serialization; lineage fields optional.

- [ ] **Step 1: Write the failing test**

```python
from datetime import UTC, datetime, timedelta

from commerce_core.contracts import AcceptOffer, CounterOffer, Offer, OfferLineItem, OfferStatus, OfferTerms


def test_additive_contract_fields_are_optional():
    counter = CounterOffer(negotiation_round=2, target_unit_price_cents=100, requested_changes={})
    assert counter.in_response_to_offer_id is None
    accept = AcceptOffer(offer_id="o1", round=1, accepted_total_cents=100)
    assert accept.idempotency_key is None
    offer = Offer(
        offer_id="o1", request_id="r1", seller_id="s1", seller_name="S1", seller_rating=4.0,
        line_items=[OfferLineItem(sku="SKU", name="I", quantity=1, unit_price_cents=100, list_unit_price_cents=120)],
        subtotal_cents=100, shipping_cents=0, total_cents=100, delivery_days=1, warranty_months=0, returns_days=0,
        valid_until=datetime.now(UTC) + timedelta(days=1), terms=OfferTerms(), status=OfferStatus.PROPOSED, round=1,
    )
    assert getattr(offer, "parent_offer_id", None) is None
```

- [ ] **Step 2: Run test to verify it fails/passes based on current state**

Run: `uv run pytest tests/unit/negotiation/test_contract_compat.py -v`  
Expected: if lineage fields already added in Task 5 partially, adjust only to make additive behavior explicit; final state PASS.

- [ ] **Step 3: Implement additive fields (if missing)**

`AcceptOffer`:
```python
    idempotency_key: str | None = None
    accepted_at: datetime | None = None
```
`Offer`:
```python
    parent_offer_id: str | None = None
    supersedes_offer_id: str | None = None
```

- [ ] **Step 4: Run full negotiation-related tests**

Run: `uv run pytest tests/unit/negotiation tests/unit/test_seller_engine.py tests/unit/test_buyer_engine_session.py tests/unit/test_negotiation_characterization.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/commerce_core/commerce_core/contracts.py tests/unit/negotiation/test_contract_compat.py
git commit -m "feat(contracts): add additive negotiation lineage and idempotency fields"
```

## Task 11: Final verification & handoff

**Files:**
- Modify: `docs/superpowers/plans/2026-11-08-negotiation-engine.md` checkboxes only if executing manually (optional).

**Interfaces:**
- Produces: green targeted suite for changed areas; known unrelated failures documented, not hidden.

- [ ] **Step 1: Run targeted verification**

Run: `uv run pytest tests/unit/negotiation tests/unit/test_seller_engine.py tests/unit/test_buyer_engine_session.py tests/unit/test_negotiation_characterization.py tests/protocol/test_seller_negotiation.py -v`  
Expected: PASS for unit/characterization; protocol PASS when required fixtures/services are available.

- [ ] **Step 2: Run lint on touched Python packages (best effort)**

Run: `uv run ruff check packages/commerce_core/commerce_core/negotiation apps/seller_agent/seller_agent/engine.py apps/buyer_agent/buyer_agent/engine_session.py tests/unit/negotiation tests/unit/test_seller_engine.py tests/unit/test_buyer_engine_session.py tests/unit/test_negotiation_characterization.py`  
Expected: PASS or only pre-existing unrelated issues (fix issues introduced by this work).

- [ ] **Step 3: Commit any lint-only fixes**

```bash
git add -A
git commit -m "chore(negotiation): fix lint issues in negotiation engine changes"
```
(Only if there are changes; otherwise skip.)

- [ ] **Step 4: Report**

Report: commits, test commands run, pass/fail counts, and any environment-blocked tests (e.g., protocol fixtures/services).

## Self-Review Notes (plan author)

- **Spec coverage:** invariants (LLM/policy, agreement≠payment, no budget leak, trust boundary, cents, 1:N, compatibility) reflected in Global Constraints and tasks 1,3,4,5,8,9. Deterministic core (money/trust/mandates/concessions/deadlock/schemas/artifacts) covered by tasks 2–7. Seller wrap task 8; buyer trust/budget wrap task 9; additive contracts task 10; verification task 11. Full buyer deadlock/tradeoff/1:N coordinator extraction and A2A registry/artifact emission are **Phase 4/5 follow-ups** — implement incrementally after Task 11 without breaking compatibility (kept out of early tasks to avoid high-risk mediated-graph rewrites).
- **Placeholders:** none; all code/commands concrete.
- **Type consistency:** uses existing `commerce_core.contracts` models, `SellerDecision`, `Mandate/Offer` signatures; new helpers return explicit tuples/dataclasses.
- **Compatibility risk:** Tasks 8–9 are narrow delegations preserving function signatures and interrupt/settlement graph structure.
