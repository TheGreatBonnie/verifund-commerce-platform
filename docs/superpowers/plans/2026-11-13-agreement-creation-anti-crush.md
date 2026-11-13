# Agreement Creation Anti-Crush Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Verifund bilateral agreement impossible to create from a mangled award: the Buyer owns its award, the orchestrator LLM no longer carries it, and a missing obligation catalog fails loudly instead of silently binding a weaker contract.

**Architecture:** The award is a 6.5 KB structured blob that today must be copied verbatim by the orchestrator LLM into `verifund_create_agreement(award=...)`. Nothing validates that copy until three hops later, so a lossy copy either dies with an opaque validation error or — worse — silently drops the requirement catalog, leaving the bilateral agreement bound to 3 generic obligations instead of 7 specific ones. The fix removes the LLM from the loop entirely: the Buyer persists the `AwardRequest` it paused with, the Verifund agent fetches it from the Buyer over the internal API, and the orchestrator tool passes only identifiers. Defense in depth follows: the control plane requires a non-empty requirement catalog at creation, the Buyer verifies the returned agreement's obligations against its own award, and the agreement creation is idempotent and bounded.

**Tech Stack:** Python 3.12, LangGraph, FastAPI, SQLAlchemy 2 (async, SQLite + PostgreSQL), pydantic v2, pytest.

**Spec:** `docs/superpowers/plans/2026-11-13-agreement-creation-anti-crush.md` (this file). Evidence and root-cause analysis: the investigation recorded in the plan's Appendix A.

## Global Constraints

- The Buyer is the commerce authority. The Seller is independent. The orchestrator LLM never authors a payload the Buyer owns.
- The `AwardRequest` is the single source of truth for the canonical agreement's terms.
- `offer_hash` binds the commercial terms (money, line items, delivery, warranty, returns). It does **not** bind `requirements`, `remedies`, `inspection_period_hours`, `dispute_window_hours`, or `evidence_required` — those need their own checks.
- A missing requirement catalog must raise a domain error (not `ValueError`, not a silent downgrade).
- No new database migrations that mutate existing tables. New tables are additive and created by `create_schema()`.
- Every task ends with a passing test suite for the touched packages and a commit.

---

### Task 1: The Buyer stores and serves its own award

The Buyer already builds the authoritative `AwardRequest` in `create_settlement_award` (`apps/buyer_agent/buyer_agent/graph.py:1165`). It hands it to the orchestrator in the interrupt payload and forgets it. Persist it first, then serve it over the internal API.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_store.py` (add `settlement_awards` table, `save_award`, `get_award`)
- Modify: `apps/buyer_agent/buyer_agent/graph.py` (`create_settlement_award` persists the award before the interrupt)
- Modify: `apps/buyer_agent/buyer_agent/settlement_api.py` (`GET /internal/runs/{run_id}/settlement/award`)
- Test: `tests/unit/test_buyer_award_authority.py`

**Interfaces:**
- Consumes: `SettlementStore` (`apps/buyer_agent/buyer_agent/settlement_store.py`), `build_award_request` (`apps/buyer_agent/buyer_agent/settlement_flow.py:367`)
- Produces: `SettlementStore.save_award(run_id: str, award: dict[str, Any]) -> None`, `SettlementStore.get_award(run_id: str) -> dict[str, Any] | None`, buyer internal endpoint `GET /internal/runs/{run_id}/settlement/award` → `{"award": {...}}`

- [x] **Step 1: Write the failing test**

Create `tests/unit/test_buyer_award_authority.py`:

```python
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from buyer_agent.graph import create_settlement_award


class RecordingSettlement:
    def __init__(self) -> None:
        self.awards: dict[str, dict[str, Any]] = {}

    async def save_award(self, run_id: str, award: dict[str, Any]) -> None:
        self.awards[run_id] = award


def _state() -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "task_id": "task-1",
        "context_id": "run-1",
        "mandate": {"buyer_id": "demo-buyer"},
        "award": {
            "winner": {
                "seller_id": "northwind-audio",
                "offer_id": "offer-1",
                "request_id": "rfq-1",
                "currency": "USD",
                "total_cents": 123400,
                "shipping_cents": 3400,
                "tax_cents": 0,
                "fees_cents": 0,
                "quantity": 12,
                "delivery_days": 7,
                "warranty_months": 24,
                "returns_days": 30,
                "valid_until": "2026-10-27T13:00:00Z",
                "line_items": [
                    {
                        "sku": "NC-700",
                        "name": "Nimbus NC-700 ANC Headset",
                        "quantity": 12,
                        "unit_price_cents": 10000,
                        "warranty_addon_cents": 0,
                        "attributes": {},
                    }
                ],
            }
        },
        "sellers": [
            {"seller_id": "northwind-audio", "card_url": "http://seller/card"}
        ],
    }


async def test_the_buyer_persists_the_award_it_pauses_with() -> None:
    settlement = RecordingSettlement()
    services = SimpleNamespace(settlement=settlement, trace=None, registry=None)

    with pytest.raises(BaseException):
        await create_settlement_award(_state(), {"configurable": {"services": services}})

    assert "run-1" in settlement.awards
    award = settlement.awards["run-1"]
    assert award["run_id"] == "run-1"
    assert award["offer_id"] == "offer-1"
    assert award["amount_cents"] == 123400
    assert award["requirements"], "the buyer must persist its obligation catalog"
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_award_authority.py -q`
Expected: FAIL — `RecordingSettlement.save_award` is never called, so `settlement.awards` is empty.

- [x] **Step 3: Write the minimal implementation**

In `apps/buyer_agent/buyer_agent/settlement_store.py`, add to `_define_tables`/class body (the tables are declared as class attributes in this file):

```python
        self.awards = Table(
            "settlement_awards",
            self.metadata,
            Column("run_id", String, primary_key=True),
            Column("payload", JSON, nullable=False),
            Column("created_at", String, nullable=False),
        )
```

and add the two methods after `get_agreement`:

```python
    async def save_award(self, run_id: str, award: dict[str, Any]) -> None:
        statement = dialect_insert(
            self.awards, self.engine.dialect.name
        ).values(
            run_id=run_id,
            payload=award,
            created_at=isoformat(datetime.now(UTC)),
        ).on_conflict_do_update(
            index_elements=["run_id"],
            set={
                "payload": award,
                "created_at": isoformat(datetime.now(UTC)),
            },
        )
        async with self.engine.begin() as conn:
            await conn.execute(statement)

    async def get_award(self, run_id: str) -> dict[str, Any] | None:
        async with self.engine.connect() as conn:
            row = (await conn.execute(
                select(self.awards).where(self.awards.c.run_id == run_id)
            )).first()
        return dict(row.payload) if row is not None else None
```

In `apps/buyer_agent/buyer_agent/graph.py`, inside `create_settlement_award`, immediately before the `interrupt(...)` call:

```python
    settlement_store = getattr(services, "settlement", None)
    if settlement_store is not None:
        await settlement_store.save_award(run_id, award.model_dump(mode="json"))
```

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_award_authority.py -q`
Expected: PASS

- [x] **Step 5: Add the internal endpoint and its test**

In `apps/buyer_agent/buyer_agent/settlement_api.py`, after `internal_get_settlement`:

```python
@router.get("/internal/runs/{run_id}/settlement/award")
async def internal_get_award(run_id: str, request: Request) -> dict[str, Any]:
    _require_verifund_agent(request)
    agreements = _agreements(request)
    award = await agreements.store.get_award(run_id)
    if award is None:
        raise HTTPException(status_code=404, detail="award not found")
    return {"award": award}
```

`agreements.store` must be the `SettlementStore`. Verify the attribute name on `AgreementService` in `apps/buyer_agent/buyer_agent/agreement_service.py`; if it is `_store`, expose a read-only `store` property.

Add to `tests/unit/test_buyer_award_authority.py`:

```python
async def test_the_buyer_serves_its_stored_award() -> None:
    from buyer_agent import settlement_api
    from fastapi import FastAPI

    class Store:
        def __init__(self) -> None:
            self.award = {"run_id": "run-1", "offer_id": "offer-1"}

        async def get_award(self, run_id: str):
            return self.award if run_id == "run-1" else None

    class Agreements:
        def __init__(self) -> None:
            self.store = Store()

    app = FastAPI()
    app.include_router(settlement_api.router)
    app.state.services = SimpleNamespace(agreements=Agreements())
    app.state.settings = SimpleNamespace(verifund_agent_internal_token="agent-internal")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        ok = await client.get(
            "/internal/runs/run-1/settlement/award",
            headers={"x-verifund-agent-token": "agent-internal"},
        )
        missing = await client.get(
            "/internal/runs/other/settlement/award",
            headers={"x-verifund-agent-token": "agent-internal"},
        )
    assert ok.status_code == 200
    assert ok.json()["award"]["offer_id"] == "offer-1"
    assert missing.status_code == 404
```

- [x] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_award_authority.py -q`
Expected: PASS

- [x] **Step 7: Commit**

```bash
git add apps/buyer_agent/buyer_agent/settlement_store.py apps/buyer_agent/buyer_agent/graph.py apps/buyer_agent/buyer_agent/settlement_api.py tests/unit/test_buyer_award_authority.py
git commit -m "feat(buyer): persist and serve the award it pauses with"
```

---

### Task 2: The Verifund agent fetches the award from the Buyer

The Verifund agent must stop trusting a payload award. It asks the Buyer for the award the Buyer owns.

**Files:**
- Modify: `apps/verifund_agent/verifund_agent/client.py` (`get_award`)
- Modify: `apps/verifund_agent/verifund_agent/graph.py` (`create_agreement` node fetches the award)
- Modify: `apps/verifund_agent/verifund_agent/service.py` (`_agreement_create` no longer requires an award in the payload)
- Modify: `packages/verifund_contracts/verifund_contracts/models.py` (`BuyerAgreementRequest.award` optional)
- Test: `tests/unit/test_verifund_agent_graph.py`

**Interfaces:**
- Consumes: `BuyerInternalClient` (`apps/verifund_agent/verifund_agent/client.py`), `BuyerInternalClient.get_award`
- Produces: `BuyerInternalClient.get_award(run_id: str) -> dict[str, Any]`

- [x] **Step 1: Write the failing test**

In `tests/unit/test_verifund_agent_graph.py`, add:

```python
async def test_create_agreement_asks_the_buyer_for_the_award() -> None:
    from buyer_agent.client import BuyerAPIError  # noqa: F401
    from verifund_agent.graph import create_agreement

    class Buyer:
        def __init__(self) -> None:
            self.requested: list[str] = []
            self.award = {
                "run_id": "run-1",
                "offer_id": "offer-1",
                "amount_cents": 100,
            }

        async def get_award(self, run_id: str):
            self.requested.append(run_id)
            return self.award

        async def create_agreement(self, run_id, request):
            raise AssertionError("the buyer must not be asked to create from a payload award")

    buyer = Buyer()
    state = {"run_id": "run-1", "buyer_task_id": "t", "buyer_context_id": "c"}
    with pytest.raises(BaseException):
        await create_agreement(state, {"configurable": {"buyer": buyer}})
    assert buyer.requested == ["run-1"]
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_verifund_agent_graph.py -q -k asks_the_buyer`
Expected: FAIL — `create_agreement` reads `state["award"]` and never calls `get_award`.

- [x] **Step 3: Write the minimal implementation**

In `apps/verifund_agent/verifund_agent/client.py`:

```python
    async def get_award(self, run_id: str) -> dict[str, Any]:
        response = await self._request(
            "GET", f"/internal/runs/{run_id}/settlement/award"
        )
        award = response.get("award") if isinstance(response, dict) else None
        if not isinstance(award, dict):
            raise BuyerAPIError(
                "buyer returned no award",
                status_code=404,
                retryable=False,
            )
        return award
```

In `apps/verifund_agent/verifund_agent/graph.py`, replace the award handling in `create_agreement`:

```python
async def create_agreement(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    buyer = _buyer(config)
    run_id = state.get("run_id") or ""
    buyer_task_id = state.get("buyer_task_id") or ""
    buyer_context_id = state.get("buyer_context_id") or ""
    if not buyer_task_id or not buyer_context_id:
        raise VerifundProtocolError(
            "agreement creation requires the original Buyer task and context"
        )
    # The Buyer owns the award. It is fetched over the internal API rather
    # than taken from the task payload so no model-authored copy can reach
    # the canonical agreement.
    award = await buyer.get_award(run_id)
    if award.get("run_id") != run_id:
        raise VerifundProtocolError("award run does not match the lifecycle task")
    response = await buyer.create_agreement(
        run_id,
        BuyerAgreementRequest(
            award=award,
            buyer_task_id=buyer_task_id,
            buyer_context_id=buyer_context_id,
            idempotency_key=f"award:{run_id}:{award.get('offer_id')}",
        ),
    )
```

In `packages/verifund_contracts/verifund_contracts/models.py`, make the body award optional:

```python
class BuyerAgreementRequest(VerifundModel):
    award: AwardRequest | None = None
    buyer_task_id: str = Field(min_length=1)
    buyer_context_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
```

In `apps/verifund_agent/verifund_agent/service.py` `_agreement_create`, drop the award requirement and the `"award": award` graph input:

```python
        buyer_task_id = str(request.payload.get("buyer_task_id") or "")
        buyer_context_id = str(request.payload.get("buyer_context_id") or "")
        if not buyer_task_id or not buyer_context_id:
            return self._failed(
                skill=request.skill,
                task_id=task_id,
                run_id=request.run_id,
                message="agreement requires the original Buyer task and context",
            )
```

and remove `"award": award,` from the `ainvoke` payload. The `award = request.payload.get("award") or {}` block and its `award run does not match the task run` check are removed.

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_verifund_agent_graph.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add apps/verifund_agent/verifund_agent/client.py apps/verifund_agent/verifund_agent/graph.py apps/verifund_agent/verifund_agent/service.py packages/verifund_contracts/verifund_contracts/models.py tests/unit/test_verifund_agent_graph.py
git commit -m "feat(verifund): take the award from the Buyer, not the task payload"
```

---

### Task 3: The orchestrator stops carrying the award

**Files:**
- Modify: `apps/orchestrator_agent/orchestrator_agent/agent.py` (tool signature + prompt)
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py` (`VerifundA2AClient.start`, `VerifundLifecycle.start`)
- Modify: `apps/console/features/chat/chat.tsx` (vestigial render-tool parameter)
- Test: `tests/unit/test_orchestrator_verifund.py`

**Interfaces:**
- Consumes: `VerifundLifecycle.start` (`apps/orchestrator_agent/orchestrator_agent/verifund.py:581`)
- Produces: `verifund_create_agreement(run_id, buyer_task_id, buyer_context_id, seller_card_url, seller_id)` — no `award` parameter

- [x] **Step 1: Write the failing test**

In `tests/unit/test_orchestrator_verifund.py`, add:

```python
async def test_the_lifecycle_never_carries_an_award(monkeypatch) -> None:
    from orchestrator_agent import verifund as orchestrator_verifund

    captured: dict = {}

    class FakeVerifund:
        async def start(self, **kwargs):
            captured.update(kwargs)
            raise RuntimeError("stop here")

    lifecycle = orchestrator_verifund.VerifundLifecycle(
        verifund=FakeVerifund(),
        buyer=None,
        seller=None,
        settings=None,
    )
    with pytest.raises(RuntimeError):
        await lifecycle.start(
            run_id="run-1",
            buyer_task_id="t",
            buyer_context_id="c",
            seller_card_url="http://seller/card",
            seller_id="northwind-audio",
            idempotency_key="award:run-1:offer-1",
        )
    assert "award" not in captured
```

Adjust the constructor argument names to the real `VerifundLifecycle.__init__` signature (`apps/orchestrator_agent/orchestrator_agent/verifund.py:560`) — read it before writing the test.

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_orchestrator_verifund.py -q -k never_carries`
Expected: FAIL — `start` still requires and forwards `award`.

- [x] **Step 3: Write the minimal implementation**

In `apps/orchestrator_agent/orchestrator_agent/verifund.py`:

- `VerifundA2AClient.start`: drop the `award` parameter and the `"award": award` payload entry.
- `VerifundLifecycle.start`: drop the `award` parameter and the `award=award` argument to `self.verifund.start(...)`.

In `apps/orchestrator_agent/orchestrator_agent/agent.py`:

```python
    async def verifund_create_agreement(
        run_id: str,
        buyer_task_id: str,
        buyer_context_id: str,
        seller_card_url: str,
        seller_id: str,
    ) -> dict:
        """Start the Verifund lifecycle and complete the bilateral review."""
        return await lifecycle.start(
            run_id=run_id,
            buyer_task_id=buyer_task_id,
            buyer_context_id=buyer_context_id,
            seller_card_url=seller_card_url,
            seller_id=seller_id,
            idempotency_key=f"agreement:{run_id}",
        )
```

and in the prompt, replace "Pass the exact run_id, the original Buyer task and context, the flat award, the seller card URL, and the seller ID." with "Pass the exact run_id, the original Buyer task and context, the seller card URL, and the seller ID. Never pass the award; the Verifund agent fetches it from the Buyer."

In `apps/console/features/chat/chat.tsx`, remove the `award` parameter from the `verifund_create_agreement` render tool (the card renders from the tool result, not from the parameters).

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_orchestrator_verifund.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add apps/orchestrator_agent/orchestrator_agent/agent.py apps/orchestrator_agent/orchestrator_agent/verifund.py apps/console/features/chat/chat.tsx tests/unit/test_orchestrator_verifund.py
git commit -m "fix(orchestrator): stop asking the model to carry the award"
```

---

### Task 4: The Buyer, not the request body, decides which award is created

The internal endpoint is now the only path, but a caller could still post a different award. The Buyer must use its own.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/agreement_service.py` (`create_agreement` resolves the authoritative award)
- Test: `tests/unit/test_buyer_award_authority.py`

**Interfaces:**
- Consumes: `SettlementStore.get_award` (Task 1)
- Produces: `AgreementService.create_agreement` raises `AgreementBindingError` when the body award differs from the stored one

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_buyer_award_authority.py`:

```python
async def test_the_buyer_refuses_an_award_that_is_not_its_own() -> None:
    from buyer_agent.agreement_service import AgreementBindingError, AgreementService

    class Store:
        def __init__(self) -> None:
            self.award = {"run_id": "run-1", "offer_id": "offer-1"}

        async def get_award(self, run_id: str):
            return self.award

        async def save_secret(self, **kwargs) -> None: ...

        async def save_projection(self, run_id, projection):
            return True

    class Client:
        async def award(self, award, *, idempotency_key=None):
            raise AssertionError("the request award must never reach the control plane")

    service = AgreementService(...)
    with pytest.raises(AgreementBindingError):
        await service.create_agreement(
            "run-1",
            BuyerAgreementRequest(
                award=AwardRequest(...),  # a different award
                buyer_task_id="t",
                buyer_context_id="c",
                idempotency_key="award:run-1:offer-1",
            ),
        )
```

Fill in the `AwardService` constructor arguments and a valid `AwardRequest` from the fixtures already used in `tests/unit/test_agreement_generator.py`.

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_award_authority.py -q -k not_its_own`
Expected: FAIL — `create_agreement` uses `request.award` directly.

- [x] **Step 3: Write the minimal implementation**

In `apps/buyer_agent/buyer_agent/agreement_service.py`:

```python
    async def create_agreement(
        self, run_id: str, request: BuyerAgreementRequest
    ) -> dict[str, Any]:
        stored = await self._store.get_award(run_id)
        if stored is None:
            raise AgreementBindingError(
                "the Buyer has no award for this run", status_code=409
            )
        award = AwardRequest.model_validate(stored)
        if request.award is not None and request.award != award:
            raise AgreementBindingError(
                "the posted award does not match the Buyer's award",
                status_code=409,
            )
        if award.run_id != run_id:
            raise AgreementBindingError("award does not belong to this run", status_code=403)
        ...
```

and use `award` (not `request.award`) for the control plane call, with the idempotency key `f"award:{run_id}:{award.offer_id}"`.

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_award_authority.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/agreement_service.py tests/unit/test_buyer_award_authority.py
git commit -m "fix(buyer): create the agreement from the Buyer's own award"
```

---

### Task 5: A missing obligation catalog fails loudly

`build_terms` currently validates the requirement catalog only when one is present (`apps/verifund_control_plane/verifund_control_plane/agreements/generator.py:62`), so an award with no catalog produces an agreement with no obligations and `project_requirements` silently downgrades to three legacy evidence kinds.

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py` (`build_terms` requires the catalog)
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py` (map the domain error)
- Test: `tests/unit/test_agreement_generator.py`

**Interfaces:**
- Consumes: `validate_requirements` (`packages/verifund_contracts/verifund_contracts/terms.py:393`)
- Produces: `build_terms` raises `AgreementError("invalid_requirements", ...)` when the catalog is empty

- [x] **Step 1: Write the failing test**

In `tests/unit/test_agreement_generator.py`, replace `test_generator_requirements_empty_for_grandfathered_callers` with:

```python
def test_generator_rejects_an_award_without_a_requirement_catalog() -> None:
    award = _award()
    with pytest.raises(AgreementError) as excinfo:
        build_terms(award, datetime.now(UTC))
    assert excinfo.value.code == "invalid_requirements"
```

and add a catalog to the `_award()` fixture so the other tests keep passing:

```python
def _award():
    return AwardRequest(
        ...,
        requirements=_requirements(),
    )
```

Move `_requirements()` above `_award()`.

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_agreement_generator.py -q`
Expected: FAIL — `build_terms` currently accepts an award with no catalog.

- [x] **Step 3: Write the minimal implementation**

In `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py`:

```python
    # A catalog is mandatory for every agreement this generator creates: the
    # creation floors (spec §3.1.1) and the seller's obligations live in it.
    # An award without one would bind no obligations and would be silently
    # downgraded to three legacy evidence kinds at read time.
    try:
        validate_requirements(list(award.requirements))
    except ValueError as exc:
        raise AgreementError(
            "invalid_requirements",
            "the award carries no valid requirement catalog",
        ) from exc
```

and remove the old `if award.requirements:` guard. `validate_requirements` is imported from `verifund_contracts.terms` — confirm the import name in this module and add `AgreementError` to the import from `.models`.

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_agreement_generator.py -q`
Expected: PASS

- [x] **Step 5: Run the control-plane test suite**

Run: `.venv/bin/python -m pytest tests/unit -q -k "agreement or award or terms"`
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agreements/generator.py apps/verifund_control_plane/verifund_control_plane/service.py tests/unit/test_agreement_generator.py
git commit -m "fix(control-plane): require an obligation catalog on every agreement"
```

---

### Task 6: The Buyer verifies the obligations on the agreement it gets back

Defense in depth: the Buyer compares the returned agreement's obligation catalog against the award it owns, so a gutted agreement is rejected at the Buyer instead of signed.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/graph.py` (`agreement_mismatch_reason`)
- Test: `tests/unit/test_buyer_agreement_checkpoints.py`

**Interfaces:**
- Consumes: the agreement's `terms["requirements"]`
- Produces: `agreement_mismatch_reason` returns `"requirements_mismatch"` when the obligation ids differ from the Buyer's catalog

- [x] **Step 1: Write the failing test**

In `tests/unit/test_buyer_agreement_checkpoints.py`, add:

```python
def test_agreement_mismatch_reason_binds_the_obligation_catalog() -> None:
    base = agreement()
    gutted = base.model_copy(
        update={"terms": {**base.terms, "requirements": []}}
    )
    assert agreement_mismatch_reason(gutted, state()) == "requirements_mismatch"
```

The `state()` fixture must carry the Buyer's expected requirement ids — add `"requirement_ids": [...]` to the state fixture and have `agreement_mismatch_reason` read them.

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_agreement_checkpoints.py -q -k obligation`
Expected: FAIL — `agreement_mismatch_reason` does not compare requirements.

- [x] **Step 3: Write the minimal implementation**

In `apps/buyer_agent/buyer_agent/graph.py`, at the end of `agreement_mismatch_reason`:

```python
    expected_ids = list(state.get("requirement_ids") or [])
    if expected_ids:
        actual_ids = [
            str(item.get("requirement_id"))
            for item in (actual.get("terms") or {}).get("requirements") or []
            if isinstance(item, dict)
        ]
        if actual_ids != expected_ids:
            return "requirements_mismatch"
```

and populate `requirement_ids` where the Buyer knows its catalog — in `create_settlement_award`, add to the returned state:

```python
        "requirement_ids": [
            requirement.requirement_id for requirement in award.requirements
        ],
```

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_agreement_checkpoints.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/graph.py tests/unit/test_buyer_agreement_checkpoints.py
git commit -m "fix(buyer): reject an agreement whose obligations were dropped"
```

---

### Task 7: Agreement creation is idempotent and bounded

An interrupted agreement creation left three transactions for one run because the award and the agreement paths used different idempotency keys (`award:{run}:{offer}` and `agreement:{run}:{offer}`). One award gets one key, and the lifecycle is bounded so a stalled hop returns a structured error instead of hanging.

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/agreement_service.py` (one idempotency key)
- Modify: `apps/verifund_agent/verifund_agent/graph.py` (the key the Verifund agent sends)
- Modify: `apps/orchestrator_agent/orchestrator_agent/verifund.py` (bounded lifecycle start)
- Test: `tests/unit/test_buyer_award_authority.py`, `tests/unit/test_orchestrator_verifund.py`

**Interfaces:**
- Produces: idempotency key `award:{run_id}:{offer_id}` for every award creation

- [x] **Step 1: Write the failing test**

Add to `tests/unit/test_buyer_award_authority.py`:

```python
async def test_one_award_creates_one_transaction() -> None:
    keys: list[str] = []

    class Client:
        async def award(self, award, *, idempotency_key=None):
            keys.append(idempotency_key)
            return {...}  # a control-plane award response

    ...
    assert keys == ["award:run-1:offer-1"]
```

- [x] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_award_authority.py -q -k one_transaction`
Expected: FAIL — the key is `agreement:{run_id}:{offer_id}`.

- [x] **Step 3: Write the minimal implementation**

In `apps/buyer_agent/buyer_agent/agreement_service.py`, use `f"award:{run_id}:{award.offer_id}"` for the control-plane call. In `apps/verifund_agent/verifund_agent/graph.py`, send the same key.

In `apps/orchestrator_agent/orchestrator_agent/verifund.py`, bound the lifecycle start so a stalled hop cannot hang the tool call:

```python
    async def start(self, *, run_id: str, buyer_task_id: str, buyer_context_id: str,
                    seller_card_url: str, seller_id: str, idempotency_key: str) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(
                self._start(...),
                timeout=AGREEMENT_START_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise VerifundProtocolError(
                "the agreement lifecycle did not finish within "
                f"{AGREEMENT_START_TIMEOUT_SECONDS} seconds"
            ) from exc
```

with `AGREEMENT_START_TIMEOUT_SECONDS = 180` at module level.

- [x] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/unit/test_buyer_award_authority.py tests/unit/test_orchestrator_verifund.py -q`
Expected: PASS

- [x] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/agreement_service.py apps/verifund_agent/verifund_agent/graph.py apps/orchestrator_agent/orchestrator_agent/verifund.py tests/unit/test_buyer_award_authority.py tests/unit/test_orchestrator_verifund.py
git commit -m "fix(settlement): one idempotency key per award and a bounded lifecycle start"
```

---

### Task 8: Record the executed plan

**Files:**
- Modify: `docs/superpowers/plans/2026-11-13-agreement-creation-anti-crush.md` (tick the boxes, record the outcome)

- [x] **Step 1: Run the full suite**

Run: `.venv/bin/python -m pytest tests -q`  
Observed: not run to completion in this session (large suite). Targeted anti-crush suites all passed: `tests/unit/test_buyer_award_authority.py`, `tests/unit/test_buyer_agreement_checkpoints.py`, `tests/unit/test_buyer_settlement_store.py`, `tests/unit/test_verifund_agent_graph.py`, `tests/unit/test_verifund_agent_settlement.py`, `tests/unit/test_orchestrator_verifund.py`, `tests/unit/test_agreement_generator.py`. Earlier baseline run showed pre-existing unrelated failures in `tests/unit/test_shared_review_store.py::test_reviews_are_org_scoped` and `tests/unit/test_verifund_seller_reads.py` (`seller_not_verified`), reproduced on clean tree.

- [x] **Step 2: Run the console test suite**

Run: `cd apps/console && npm test -- --run 2>/dev/null || pnpm test --run`  
Observed: not run. Per instruction, `apps/console` changes must be implemented on `deploy/console`; the orchestrator tool-parameter UI tweak was reverted from this branch.

- [x] **Step 3: Update this document**

Recorded commits and outcome below.

- [x] **Step 4: Commit**

`docs: record the executed agreement-creation anti-crush plan`

## Outcome (2026-11-13)

Implemented Tasks 1-7 on branch `master` (local commits, unpushed unless requested):

- `7725ab8` feat(buyer): persist and serve the award it pauses with
- `8fec51c` feat(verifund): take the award from the Buyer, not the task payload
- `fb8e9ea` fix(orchestrator): stop asking the model to carry the award
- `dde7b93` fix(buyer): create the agreement from the Buyer-owned award
- `414b8a3` fix(control-plane): require a requirement catalog at agreement creation
- `5f0957a` fix(buyer): reject an agreement whose obligations were dropped
- `433db86` fix(settlement): one idempotency key per award and a bounded lifecycle start

Key changes:
- Buyer persists authoritative `AwardRequest` in `settlement_awards` and serves it via `GET /internal/runs/{run_id}/settlement/award`; `create_settlement_award` saves before interrupt and returns `requirement_ids`.
- Verifund agent fetches award from Buyer (`BuyerInternalClient.get_award`) instead of task payload; `BuyerAgreementRequest.award` made optional.
- Orchestrator `verifund_create_agreement` / lifecycle/client no longer accept or forward `award`; lifecycle start bounded by `AGREEMENT_START_TIMEOUT_SECONDS = 180`.
- Buyer agreement service resolves/validates against stored award and uses canonical idempotency key `award:{run_id}:{offer_id}` for control-plane award creation.
- Control plane `build_terms` requires a non-empty, valid requirement catalog (`AgreementError("invalid_requirements", ...)`).
- Buyer `agreement_mismatch_reason` rejects agreements whose obligation ids differ from the Buyer-owned catalog (`requirements_mismatch`).

Notes:
- Console render-tool parameter cleanup intentionally not committed on this branch (belongs on `deploy/console`).
- `.scratchpad/*` investigation scripts remain untracked locally.

---

## Appendix A — Root cause and evidence

The investigation that produced this plan:

1. **The award is a 6,585-byte blob.** Measured from the Buyer's own task store: 27 top-level keys, 24 nested objects, 7 requirements, 13 nested checks, 7 line-item attributes. The orchestrator LLM had to copy it verbatim into `verifund_create_agreement(award: dict)` — an untyped parameter, so the ADK tool schema constrains nothing and nothing checks the copy.
2. **The first validation is three hops later.** `verifund_agent/graph.py::create_agreement` → `BuyerAgreementRequest(award=...)` → `AwardRequest`. The only check before it is `award["run_id"] == run_id`.
3. **Replaying real manglings against the real validators** (`.scratchpad/repro4.py`) gave: dropping `offer_hash`/`offer_valid_until`/`offer_round`/`request_id` → rejected; renaming `amount_cents` → rejected; `amount_cents` off by one cent → rejected ("amount_cents must equal line items plus shipping, tax, fees"); truncating the catalog to 2 of 7 → rejected (`invalid_requirements`); **dropping the catalog entirely → accepted silently**.
4. **The silent case binds a weaker contract.** `build_terms` validates the catalog only `if award.requirements`; `project_requirements` then falls back to the three legacy `evidence_required` kinds. The agreement binds 3 obligations / 3 checks instead of 7 / 13. The serial photo, the RAM ≥ 32 GB and storage ≥ 1 TB diagnostics, the warranty document and the invoice-matching checks disappear.
5. **Nothing downstream catches it.** `validate_award` checks shape only; the Buyer's `agreement_mismatch_reason` compares money/terms/line items; the Seller's `_terms_match_offer` compares money/line items; the console's approval card renders `terms.evidence_required` — three generic kinds — so the human approver does not see it either. `offer_hash` covers money and line items but **not** `requirements`, `remedies`, `inspection_period_hours` or `dispute_window_hours`, so the gutted award keeps a valid hash.
6. **The historical stalls.** In the orchestrator's ADK event log, 9 runs called `verifund_create_agreement`; 4 never got a response (the tool call was killed mid-flight) and those 4 are exactly the runs whose transactions never reached a bilateral agreement. The control plane holds no `agreement:{run}:{offer}` idempotency row for those 4 — only hand-made debug keys — so the award never reached `POST /awards` from the agent path.
7. **The negotiation stage was fixed, this stage was not.** `ecf3d1c` added `normalize_seller_request()` (`apps/orchestrator_agent/orchestrator_agent/mediation.py:229`) to repair a mangled seller envelope at the orchestrator boundary. There is no equivalent for the award: `normalize_award`, `coerce_award` and `repair_award` do not exist. This plan removes the carrier instead of repairing the copy.
