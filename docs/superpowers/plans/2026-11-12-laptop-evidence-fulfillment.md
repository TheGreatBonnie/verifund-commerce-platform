# Laptop Evidence & Fulfillment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing Verifund control plane so a laptop transaction proves a verifiable chain (identity → condition → packaging → carrier delivery → buyer inspection/dispute) and authorizes a separate seller payout only when deterministic blockers are clear.

**Architecture:** Evolve the current modular monolith in place. Keep requirement status derived from the agreement projection and `policy.evaluate`; keep the local content-addressed `EvidenceStore`, SQLite schema evolution (`create_all` + idempotent `ALTER TABLE`), reconciler sweeps, and the existing ledger/payout path. Add only the missing facts as additive tables (provenance challenges, shipments, carrier events, delivery confirmations, inspection records, disputes), a `CarrierAdapter` selected like `PaymentPort`, and an explainable `blockers[]` result.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2 / pydantic-settings, SQLAlchemy 2 (async, SQLite/aiosqlite), existing `EvidenceStore` (SHA-256, local filesystem), existing `Reconciler`, LangGraph (verifund_agent only, unchanged), pytest + httpx ASGITransport + injected clock, TypeScript/Next.js console (`apps/console`).

**Spec:** `docs/superpowers/specs/2026-11-12-laptop-evidence-fulfillment-design.md`

## Global Constraints

- **Source precedence (spec D1, D2):** 2026-11-12 docs supersede `2026-11-04-verifund-seller-evidence-target-design.md` on delivery authority, requirement catalog, review-state ownership, and inspection/dispute persistence. Architecture doc wins on mechanics; canonical doc wins on policy semantics; requirements doc is content reference.
- **No rebuilds (spec §4):** do not create `fulfillment_tasks`, `fulfillment_requirements`, `verification_runs`, `evidence_verifications`, `release_evaluations`, or `settlement_intents` tables. Requirement status stays derived (D7).
- **SQLite only (D11):** additive schema in `Repository.create_schema` / `tenancy` / `agreements` via `create_all` + `await self._ensure_column(...)` / idempotent `ALTER TABLE`. No Alembic, no asyncpg/psycopg, no SQLite-specific changes that prevent later swap except those already present.
- **Money path is authoritative (spec §4):** do not alter ledger builders, `idempotency_keys`, `provider_operations`, webhook dedupe, CAS `Repository.transition`, or `service.release` / `_start_payout` semantics except to consume `blockers[]`.
- **Deterministic money decisions:** OCR/CV/LLM produce findings only. Blockers and payout authorization are deterministic and service-enforced.
- **Carrier is authoritative for shipped flows (D9):** `LABEL_CREATED` ≠ acceptance; `DELIVERED` ≠ correct contents/condition. `POST /transactions/{id}/delivery-confirmed` remains corroboration only.
- **Statuses (D13):** keep `RequirementStatus = {not_submitted, pending_scan, pass, fail, review}`. Expose derived `action_owner ∈ {seller, reviewer, none}`; map `ACTION_REQUIRED` → `fail`+`seller`, `UNDER_REVIEW` → `review`+`reviewer`, terminal rejection → `fail`+terminal `reason_code`.
- **Delivery timeout never refunds (D14).** Block + review only.
- **Provenance (D10):** extraction adapter may vary; comparison is strict string equality against an active, unexpired, single-use challenge consumed by a conditional `UPDATE`.
- **Simulation:** all generated artifacts/events labelled `simulated: true`; sandbox uses adapter injection at the app boundary (like `PaymentPort`), never `if sandbox` in domain logic.
- **Buyer-attested delivery tests will break in P3:** update `tests/integration/test_verifund_lifecycle.py` and affected unit/integration tests in the same commit as the semantics change.
- **`UNIQUE(transaction_id, sha256)` on `evidence`:** fixtures must use distinct bytes per requirement; add a regression test.
- **No seller-agent changes (D12).** Live submission path is console → control plane.
- **Existing requirement ids preserved:** `serial, product_photos, hardware, warranty, shipping, delivery_confirmation, invoice`. New: `provenance, condition_declaration, battery, packaging, insurance_confirmation, carrier_acceptance`.

## File Map

| File | Responsibility |
|---|---|
| `packages/verifund_contracts/verifund_contracts/models.py` | Requirement/stage/source/check enums, `CarrierEventStatus`, `DisputeClaimType`, `ActionOwner`, evidence submission view/finding fields, blocker/projection DTOs |
| `packages/verifund_contracts/verifund_contracts/terms.py` | Laptop category template, `project_requirements` category resolution + defaults, floors unchanged |
| `apps/buyer_agent/buyer_agent/settlement_flow.py` | Laptop authoring catalog aligned to spec ids/checks (source of terms copied into agreements) |
| `apps/verifund_control_plane/verifund_control_plane/policy.py` | `declaration` source, `min_items`/`views_cover`, system-owned requirements, provenance/challenge evaluation hooks, `blockers[]`, `action_owner` derivation |
| `apps/verifund_control_plane/verifund_control_plane/service.py` | Evidence declaration/view handling, challenge issue/consume, shipment registration, inspection/dispute record transitions, blocker-aware release guard |
| `apps/verifund_control_plane/verifund_control_plane/repository.py` | 6 additive tables + 5 additive `evidence_submissions` columns, queries for shipments/events/challenges/inspection/disputes |
| `apps/verifund_control_plane/verifund_control_plane/domain.py` | Transaction states unchanged except any minimal additions required by inspection/dispute records; blocker/event helpers |
| `apps/verifund_control_plane/verifund_control_plane/carrier.py` | Replace/extend with `CarrierAdapter` protocol + `MockCarrierAdapter` + event normalization (keep `FakeCarrier` compatibility only if needed by existing tests, else migrate) |
| `apps/verifund_control_plane/verifund_control_plane/reconciler.py` | `_sweep_shipments`, delivery timeout, inspection expiry/deemed acceptance integration |
| `apps/verifund_control_plane/verifund_control_plane/api/seller.py` | Challenge, shipment endpoints; `view_label` on upload |
| `apps/verifund_control_plane/verifund_control_plane/api/buyer.py` | Inspection read, dispute `claim_type`, buyer evidence if added |
| `apps/verifund_control_plane/verifund_control_plane/api/ops.py` | Manual poll / inspection resolve |
| `apps/verifund_control_plane/verifund_control_plane/app.py` | Inject carrier adapter + challenge extractor + scenario fixtures |
| `apps/console/lib/seller-types.ts` + seller fulfillment components | Stage grouping, blockers, provenance card, shipment timeline, inspection/dispute, view selector |
| `fixtures/laptop/**` | Seven scenario fixtures + remapped manifest |
| `scripts/run_scenario.py` | Deterministic replay/seed for judges |
| `tests/unit/*`, `tests/integration/*`, `tests/e2e/*` | TDD per task; lifecycle updates in P3 commit |

---

## Phase 1 — Catalog, declaration source, min_items/views coverage

### Task 1: Contract fields and enums

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Modify: `packages/verifund_contracts/verifund_contracts/terms.py`
- Test: `tests/unit/test_laptop_terms_projection.py` (new)

**Interfaces:**
- Consumes: existing `Requirement`, `RequirementCheck`, `RequirementStatus`, `EvidenceItem`, `EvidenceSubmission` shapes.
- Produces: `Requirement.stage`, `Requirement.min_items`, `Requirement.required_views`; `Requirement.source` accepts `declaration`; `ActionOwner`, `CarrierEventStatus`, `DisputeClaimType` enums; `EvidenceSubmission.view_label` and finding fields (`reason_code`, `verification_method`, `rule_version`, `confidence`) with safe defaults so existing rows/objects still validate.

- [ ] **Step 1: Write failing projection/validation tests**

```python
from verifund_contracts.models import ActionOwner, CarrierEventStatus, DisputeClaimType, Requirement
from verifund_contracts.terms import project_requirements


def test_project_requirements_defaults_for_legacy_terms() -> None:
    reqs = project_requirements({"evidence_required": ["serial", "invoice"]})
    serial = next(r for r in reqs if r.requirement_id == "serial")
    assert serial.stage is None
    assert serial.min_items == 1
    assert serial.required_views == []


def test_project_requirements_laptop_category_emits_staged_catalog() -> None:
    terms = {
        "product": {"category": "electronics.laptop.refurbished"},
        "evidence_required": ["serial", "invoice"],
    }
    reqs = project_requirements(terms)
    ids = [r.requirement_id for r in reqs]
    assert "provenance" in ids
    assert "condition_declaration" in ids
    assert "battery" in ids
    assert "packaging" in ids
    assert "carrier_acceptance" in ids
    photos = next(r for r in reqs if r.requirement_id == "product_photos")
    assert photos.stage == "product_condition"
    assert photos.min_items == 7
    assert "serial" in photos.required_views
    decl = next(r for r in reqs if r.requirement_id == "condition_declaration")
    assert decl.source == "declaration"
    assert decl.owner == "seller"
    assert {r.requirement_id: r.owner for r in reqs}["carrier_acceptance"] == "system"


def test_new_enums_exist() -> None:
    assert ActionOwner.SELLER.value == "seller"
    assert CarrierEventStatus.PICKED_UP.value == "PICKED_UP"
    assert DisputeClaimType.WRONG_DEVICE.value == "WRONG_DEVICE"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && uv run pytest tests/unit/test_laptop_terms_projection.py -v`
Expected: FAIL (missing fields/enums or wrong projection)

- [ ] **Step 3: Add contract fields with backward-compatible defaults**

In `packages/verifund_contracts/verifund_contracts/models.py`, extend `Requirement` and add enums/findings:

```python
class Requirement(VerifundModel):
    requirement_id: str
    title: str
    description: str
    owner: str  # seller | system | buyer
    kind: str
    source: str  # file | reference | declaration
    accepted_formats: list[str] = Field(default_factory=list)
    checks: list[RequirementCheck] = Field(default_factory=list)
    required: bool = True
    stage: str | None = None
    min_items: int = 1
    required_views: list[str] = Field(default_factory=list)


class ActionOwner(StrEnum):
    SELLER = "seller"
    REVIEWER = "reviewer"
    NONE = "none"


class CarrierEventStatus(StrEnum):
    LABEL_CREATED = "LABEL_CREATED"
    CARRIER_ACCEPTED = "CARRIER_ACCEPTED"
    PICKED_UP = "PICKED_UP"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    DELIVERED_SIGNED = "DELIVERED_SIGNED"
    DELIVERY_EXCEPTION = "DELIVERY_EXCEPTION"
    DELIVERY_FAILED = "DELIVERY_FAILED"
    RETURN_TO_SENDER = "RETURN_TO_SENDER"
    LOST = "LOST"
    UNKNOWN = "UNKNOWN"


class DisputeClaimType(StrEnum):
    EMPTY_BOX = "EMPTY_BOX"
    WRONG_DEVICE = "WRONG_DEVICE"
    UNDISCLOSED_DAMAGE = "UNDISCLOSED_DAMAGE"
    NOT_POWERING_ON = "NOT_POWERING_ON"
    MISSING_ACCESSORY = "MISSING_ACCESSORY"
    OTHER = "OTHER"
```

Add `view_label: str | None = None` and `reason_code: str | None = None`, `verification_method: str | None = None`, `rule_version: int | None = None`, `confidence: float | None = None` to `EvidenceSubmission` (and mirror on `EvidenceItem` only if the read path needs them) with defaults so existing payloads remain valid.

- [ ] **Step 4: Implement laptop category projection in terms.py**

In `packages/verifund_contracts/verifund_contracts/terms.py`, keep `project_requirements` behavior for legacy/generic agreements and add category resolution:

```python
def _category_of(terms: dict[str, Any]) -> str | None:
    product = terms.get("product") or {}
    category = product.get("category") or terms.get("category")
    return str(category) if category else None


def _laptop_requirement_catalog() -> list[Requirement]:
    return [
        Requirement(requirement_id="serial", title="Serial number", description="Device serial label/photo.", owner="seller", kind="serial", source="file", stage="product_identity", accepted_formats=["image/jpeg","image/png","image/webp"], checks=[RequirementCheck(check_id="serial_readable", description="Serial is readable.", operator="exists", verification_method="deterministic"), RequirementCheck(check_id="serial_matches", description="Serial matches declared value.", operator="eq", expected_value=None, verification_method="deterministic")], required=True),
        Requirement(requirement_id="provenance", title="Provenance challenge", description="Transaction challenge code visible on the device.", owner="seller", kind="other", source="file", stage="product_identity", accepted_formats=["image/jpeg","image/png","image/webp"], checks=[RequirementCheck(check_id="challenge_code", description="Challenge code matches active challenge.", operator="eq", expected_value=None, verification_method="deterministic")], required=True),
        Requirement(requirement_id="product_photos", title="Condition photos", description="Multi-angle baseline photos.", owner="seller", kind="other", source="file", stage="product_condition", accepted_formats=["image/jpeg","image/png","image/webp"], min_items=7, required_views=["front","back","left","right","keyboard","screen","underside","serial"], checks=[RequirementCheck(check_id="views_cover", description="Required views are covered.", operator="exists", verification_method="deterministic")], required=True),
        Requirement(requirement_id="condition_declaration", title="Condition declaration", description="Structured condition and lock/accessory declaration.", owner="seller", kind="other", source="declaration", stage="product_condition", checks=[RequirementCheck(check_id="battery_health_declared", description="Battery health declared.", operator="exists", verification_method="deterministic"), RequirementCheck(check_id="locks_disabled", description="Locks disabled / not enrolled.", operator="eq", expected_value="true", verification_method="deterministic")], required=True),
        Requirement(requirement_id="hardware", title="Hardware diagnostics", description="Diagnostic report matching agreed specs.", owner="seller", kind="other", source="file", stage="product_compliance", accepted_formats=["application/json","application/pdf","text/csv","image/jpeg","image/png","image/webp"], checks=[RequirementCheck(check_id="ram_gte_32gb", description="RAM meets minimum.", operator="gte", expected_value=32, unit="GB", verification_method="deterministic"), RequirementCheck(check_id="storage_gte_1tb", description="Storage meets minimum.", operator="gte", expected_value=1024, unit="GB", verification_method="deterministic")], required=True),
        Requirement(requirement_id="battery", title="Battery report", description="Battery health and cycles.", owner="seller", kind="other", source="file", stage="product_compliance", accepted_formats=["application/json","application/pdf","text/csv","image/jpeg","image/png","image/webp"], checks=[RequirementCheck(check_id="battery_health_pct", description="Battery health meets threshold.", operator="gte", expected_value=80, unit="%", verification_method="deterministic")], required=True),
        Requirement(requirement_id="warranty", title="Warranty", description="Warranty/coverage evidence.", owner="seller", kind="other", source="file", stage="product_compliance", accepted_formats=["application/json","application/pdf","text/csv","image/jpeg","image/png","image/webp"], checks=[RequirementCheck(check_id="warranty_gte_90_days", description="Warranty meets minimum.", operator="gte", expected_value=90, unit="days", verification_method="deterministic")], required=True),
        Requirement(requirement_id="packaging", title="Packaging photos", description="Unit, inside box, sealed box with label.", owner="seller", kind="shipment_manifest", source="file", stage="packaging", accepted_formats=["image/jpeg","image/png","image/webp"], min_items=3, required_views=["unit_with_serial","inside_box","sealed_with_label"], checks=[RequirementCheck(check_id="views_cover", description="Packaging views covered.", operator="exists", verification_method="deterministic")], required=True),
        Requirement(requirement_id="shipping", title="Shipping details", description="Carrier and tracking reference.", owner="seller", kind="shipment_manifest", source="reference", stage="packaging", checks=[RequirementCheck(check_id="carrier_present", description="Carrier present.", operator="exists", verification_method="deterministic"), RequirementCheck(check_id="tracking_present", description="Tracking present.", operator="exists", verification_method="deterministic")], required=True),
        Requirement(requirement_id="insurance_confirmation", title="Shipping insurance", description="Coverage confirmation when required.", owner="seller", kind="other", source="file", stage="packaging", accepted_formats=["application/json","application/pdf","image/jpeg","image/png","image/webp"], required=False, checks=[RequirementCheck(check_id="insured_value_sufficient", description="Insured value covers declared value.", operator="gte", expected_value=None, verification_method="deterministic")]),
        Requirement(requirement_id="carrier_acceptance", title="Carrier acceptance", description="Carrier accepted the package.", owner="system", kind="shipment_manifest", source="reference", stage="delivery", checks=[RequirementCheck(check_id="carrier_accepted", description="Carrier acceptance event exists.", operator="exists", verification_method="deterministic")], required=True),
        Requirement(requirement_id="delivery_confirmation", title="Delivery confirmation", description="Carrier delivery and POD as required.", owner="system", kind="delivery_confirmation", source="reference", stage="delivery", checks=[RequirementCheck(check_id="delivered", description="Delivered event exists.", operator="exists", verification_method="deterministic")], required=True),
        Requirement(requirement_id="invoice", title="Invoice", description="Seller invoice.", owner="seller", kind="invoice", source="file", stage="packaging", accepted_formats=["application/json","application/pdf","text/csv","image/jpeg","image/png","image/webp"], checks=[RequirementCheck(check_id="invoice_present", description="Invoice present.", operator="exists", verification_method="deterministic")], required=True),
    ]


def project_requirements(terms: dict[str, Any]) -> list[Requirement]:
    raw = terms.get("requirements") or []
    if raw:
        reqs = [Requirement.model_validate(item) for item in raw]
        # Backfill defaults for old stored catalogs.
        return [r.model_copy(update={"min_items": r.min_items or 1}) for r in reqs]
    if _category_of(terms) == "electronics.laptop.refurbished":
        # Merge with legacy evidence_required to preserve any extra ids the
        # agreement explicitly named.
        base = {r.requirement_id: r for r in _laptop_requirement_catalog()}
        for kind in terms.get("evidence_required") or []:
            base.setdefault(str(kind), _legacy_requirement(str(kind)))
        return list(base.values())
    return [_legacy_requirement(str(kind)) for kind in terms.get("evidence_required") or []]
```

Adjust exact titles/checks to the values you choose, but keep ids and the `source=declaration`/`owner=system` semantics. If `validate_requirements` rejects `source=declaration` or `owner=system` in unintended ways, update it deliberately and add a test.

- [ ] **Step 5: Run tests and existing terms tests**

Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && uv run pytest tests/unit/test_laptop_terms_projection.py tests/unit -k terms -v`
Expected: PASS for new tests and no regressions in terms-related unit tests

- [ ] **Step 6: Commit**

```bash
cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a
git add packages/verifund_contracts/verifund_contracts/models.py packages/verifund_contracts/verifund_contracts/terms.py tests/unit/test_laptop_terms_projection.py
git commit -m "feat(contracts): add laptop requirement projection fields and category catalog"
```

### Task 2: Policy support for declaration source, min_items, and view coverage

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py` (only if needed to pass `view_label` into evaluation inputs)
- Test: `tests/unit/test_verifund_policy.py` (extend)
- Test: `tests/unit/test_laptop_policy_coverage.py` (new)

**Interfaces:**
- Consumes: `Requirement.min_items`, `Requirement.required_views`, `Requirement.source == "declaration"`, `requirement_declarations`, submission `view_label`.
- Produces: per-requirement results where insufficient items/views or missing declaration coverage yield `fail` (actionable) or `review` (ambiguous), never `pass`.

- [ ] **Step 1: Write failing coverage/declaration tests**

```python
from datetime import UTC, datetime

from verifund_control_plane.evidence import EvidenceStore
from verifund_control_plane.policy import evaluate
from verifund_contracts.models import EvidenceItem, Requirement, RequirementCheck, TransactionRecord


def _txn() -> TransactionRecord:
    now = datetime(2026, 11, 12, tzinfo=UTC)
    return TransactionRecord.model_validate({
        "transaction_id": "txn_cov",
        "buyer_id": "buyer",
        "seller_id": "seller",
        "state": "VERIFICATION_PENDING",
        "agreement_hash": "h",
        "agreement_version": 1,
        "seller_payout_ref": "seller@x",
        "amount_minor": 100,
        "currency": "USD",
        "funding": {},
        "verification": {},
        "deadlines": {},
        "purchase_order": {},
        "evidence": [],
        "version": 1,
        "created_at": now,
        "updated_at": now,
    })


def test_product_photos_fail_when_views_missing(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    req = Requirement(requirement_id="product_photos", title="Photos", description="", owner="seller", kind="other", source="file", accepted_formats=["image/jpeg"], min_items=7, required_views=["front","back","left","right","keyboard","screen","underside","serial"], checks=[RequirementCheck(check_id="views_cover", description="", operator="exists", verification_method="deterministic")])
    # Two valid submissions with distinct bytes/views but insufficient coverage.
    item_a = store.put(transaction_id="txn_cov", seller_id="seller", kind="other", media_type="image/jpeg", original_filename="a.jpg", data=b"a", note=None, captured_at=None)
    item_a = item_a.model_copy(update={"requirement_id": "product_photos", "purpose": "requirement", "view_label": "front"})
    item_b = store.put(transaction_id="txn_cov", seller_id="seller", kind="other", media_type="image/jpeg", original_filename="b.jpg", data=b"b", note=None, captured_at=None)
    item_b = item_b.model_copy(update={"requirement_id": "product_photos", "purpose": "requirement", "view_label": "back"})
    result = evaluate(_txn(), [item_a, item_b], store, datetime(2026,11,12,tzinfo=UTC), inspection_window_hours=48, ledger_balances={"platform_cash":100,"held_funds":100}, terms={"requirements":[req.model_dump()]})
    photo = next(r for r in result.requirements if r.requirement_id == "product_photos")
    assert photo.status in {"fail", "review"}


def test_declaration_requirement_uses_requirement_declarations(tmp_path) -> None:
    store = EvidenceStore(tmp_path)
    req = Requirement(requirement_id="condition_declaration", title="Declaration", description="", owner="seller", kind="other", source="declaration", checks=[RequirementCheck(check_id="locks_disabled", description="", operator="eq", expected_value="true", verification_method="deterministic")])
    result = evaluate(_txn(), [], store, datetime(2026,11,12,tzinfo=UTC), inspection_window_hours=48, ledger_balances={"platform_cash":100,"held_funds":100}, terms={"requirements":[req.model_dump()]}, declarations=[{"declaration_id":"d1","requirement_id":"condition_declaration","attempt":1,"declared_at":"2026-11-12T00:00:00+00:00","submission_ids":[],"values":{"locks_disabled":"true"}}])
    decl = next(r for r in result.requirements if r.requirement_id == "condition_declaration")
    assert decl.status == "pass"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && uv run pytest tests/unit/test_laptop_policy_coverage.py -v`
Expected: FAIL (coverage not enforced, declaration path incomplete)

- [ ] **Step 3: Implement aggregation helpers in policy.py**

Add helpers (names illustrative; keep module style consistent):

```python
def _coverage_status(requirement: Requirement, items: list[EvidenceItem]) -> tuple[bool, list[ReviewReason]]:
    if getattr(requirement, "min_items", 1) > 1 and len(items) < requirement.min_items:
        return False, [ReviewReason.MISSING_EVIDENCE]
    views = getattr(requirement, "required_views", None) or []
    if views:
        present = {getattr(item, "view_label", None) for item in items}
        missing = [v for v in views if v not in present]
        if missing:
            return False, [ReviewReason.MISSING_EVIDENCE]
    return True, []


def _declaration_values(declarations: list[dict[str, Any]] | None, requirement_id: str) -> dict[str, Any] | None:
    if not declarations:
        return None
    candidates = [d for d in declarations if d.get("requirement_id") == requirement_id]
    if not candidates:
        return None
    latest = sorted(candidates, key=lambda d: (d.get("attempt", 0), d.get("declared_at", "")))[-1]
    return latest.get("values") or latest
```

In `evaluate(...)`, before per-check artifact evaluation:
- If `requirement.source == "declaration"`, evaluate checks against `_declaration_values(...)` (treat missing declaration as not submitted/fail per current semantics, never pass).
- If `requirement.min_items > 1` or `requirement.required_views`, apply `_coverage_status` over matched, non-rejected items. Fail coverage when clearly insufficient; use `review` only when evidence is present but ambiguous.

Do not count `PENDING_SCAN` or integrity-rejected files toward coverage. Preserve existing remediation supersession behavior (`matched.sort(key=lambda item: item.created_at, reverse=True)`).

- [ ] **Step 4: Run policy and integration-adjacent tests**

Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && uv run pytest tests/unit/test_laptop_policy_coverage.py tests/unit/test_verifund_policy.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a
git add apps/verifund_control_plane/verifund_control_plane/policy.py apps/verifund_control_plane/verifund_control_plane/service.py tests/unit/test_laptop_policy_coverage.py tests/unit/test_verifund_policy.py
git commit -m "feat(policy): enforce declaration source, min_items, and view coverage"
```

### Task 3: API and storage plumbing for view_label and declaration values

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_seller_evidence_upload.py` or `tests/integration/test_seller_evidence_*.py` (extend existing)

**Interfaces:**
- Consumes: multipart `view_label` on upload; declaration payload carrying `values` for declaration checks.
- Produces: `EvidenceSubmission.view_label` persisted/returned; declaration records include structured `values` usable by `policy.evaluate`.

- [ ] **Step 1: Write failing API/persistence tests**

```python
# Pseudocode shape for an integration test using the existing ASGI app fixture pattern:
# POST /seller/transactions/{id}/evidence with requirement_id=product_photos, view_label=front, file=...
# assert 201 and response["view_label"] == "front" (or exposed in evidence item projection)
# POST /seller/transactions/{id}/requirements/condition_declaration/declare with values={...}
# GET projection shows condition_declaration pass when values satisfy checks
```

Use the repo's existing seller auth helpers and `httpx.AsyncClient` fixture style.

- [ ] **Step 2: Run to verify failure**

Run the specific new/extended test file only.
Expected: FAIL (`view_label` ignored or declaration values not evaluated)

- [ ] **Step 3: Thread view_label through upload and persist declaration values**

In `api/seller.py` upload handler add `view_label: str | None = Form(None)` and pass to `service.add_evidence`. In `service.add_evidence`, validate `view_label` is allowed when `requirement.required_views` is non-empty, copy onto the evidence item/submission, and persist via the repository update/insert path you already use for attempt metadata.

For declarations, extend the declaration endpoint/service to accept a `values` object and store it in `requirement_declarations` (JSON column or added column, additive migration in `Repository.create_schema`). Ensure `get_declarations` / policy input returns `values`.

- [ ] **Step 4: Run targeted tests**

Run: `cd /Applications/Projects/hackathon/paypal-verifund-platform/verifund-a2a && uv run pytest <affected seller evidence tests> -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/seller.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/repository.py <tests>
git commit -m "feat(evidence): persist view labels and declaration values"
```

### Task 4: Align buyer-agent authored laptop catalog and fixture manifest

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_flow.py`
- Modify: `verifund-test-laptop-evidence/manifest.json`
- Test: `tests/unit/test_buyer_agent_*` or `tests/integration/test_laptop_catalog_alignment.py` (new)

**Interfaces:**
- Consumes: spec §6 requirement ids.
- Produces: authored terms catalog compatible with the control-plane projection; fixture manifest mapping files to real requirement ids; no byte-identical reuse across requirements.

- [ ] **Step 1: Write failing alignment tests**

```python
from verifund_contracts.terms import project_requirements


def test_buyer_authored_laptop_terms_project_to_spec_ids() -> None:
    # Build the minimal terms dict the buyer agent authors for a laptop.
    from apps.buyer_agent.buyer_agent.settlement_flow import laptop_requirements  # or the actual function/name
    terms = {"product": {"category": "electronics.laptop.refurbished"}, "requirements": [r.model_dump() for r in laptop_requirements()]}
    ids = {r.requirement_id for r in project_requirements(terms)}
    assert {"serial","provenance","product_photos","condition_declaration","hardware","battery","warranty","packaging","shipping","insurance_confirmation","carrier_acceptance","delivery_confirmation","invoice"} <= ids
```

Adapt the import to the real helper name in `settlement_flow.py`.

- [ ] **Step 2: Run to verify failure**

Run the new test file.
Expected: FAIL (missing new ids/stages/sources)

- [ ] **Step 3: Update authored catalog and manifest**

Add `provenance`, `condition_declaration`, `battery`, `packaging`, `insurance_confirmation`, `carrier_acceptance` with correct `owner/source/stage/min_items/required_views/checks`. Preserve existing ids and existing checks where still valid. Remap `verifund-test-laptop-evidence/manifest.json` from `product_identity/serial_number/hardware_specifications/shipping_delivery/buyer_acceptance` to the real ids and document `view_label` per photo. Ensure each requirement maps to a distinct file (copy/rename fixtures if necessary).

- [ ] **Step 4: Run tests and add sha-collision regression**

Add a unit test asserting that two different files for two requirements produce different sha256 values in the fixture set.

Run: `uv run pytest <new + buyer settlement tests> -v`

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/settlement_flow.py verifund-test-laptop-evidence/manifest.json <tests/fixtures>
git commit -m "feat(catalog): align laptop authored requirements and fixture manifest"
```

**Phase 1 exit criterion:** `uv run pytest tests/unit/test_laptop_terms_projection.py tests/unit/test_laptop_policy_coverage.py -v` passes; an `electronics.laptop.refurbished` agreement projects the 13 requirements; a RAM-below-minimum `hardware` artifact fails with a requirement-level finding and no payout eligibility signal is produced.

(End of chunk 1 — Phases 2–6 follow in subsequent chunks.)
## Phase 2 — Provenance challenge

### Task 5: Provenance challenge persistence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py` (add `provenance_ttl_minutes` if absent)
- Test: `tests/unit/test_provenance_repository.py` (new)

**Interfaces:**
- Produces: `provenance_challenges` table and repository methods `issue_provenance_challenge`, `get_active_provenance_challenge`, `consume_provenance_challenge` (conditional single-use), `expire_provenance_challenges`.

- [ ] **Step 1: Write failing repository tests**

```python
import asyncio
from datetime import UTC, datetime, timedelta

from verifund_control_plane.db import create_engine
from verifund_control_plane.repository import Repository


async def _repo(tmp_path):
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path/'db.sqlite'}")
    repo = Repository(engine)
    await repo.create_schema()
    return repo


def test_issue_and_consume_challenge_once(tmp_path) -> None:
    async def run():
        repo = await _repo(tmp_path)
        now = datetime(2026, 11, 12, tzinfo=UTC)
        challenge = await repo.issue_provenance_challenge(
            organization_id="org", transaction_id="txn", code="VF2048-839251",
            issued_at=now, expires_at=now + timedelta(minutes=60),
        )
        assert challenge["status"] == "active"
        consumed = await repo.consume_provenance_challenge(
            organization_id="org", transaction_id="txn", code="VF2048-839251", now=now,
        )
        assert consumed is True
        consumed_again = await repo.consume_provenance_challenge(
            organization_id="org", transaction_id="txn", code="VF2048-839251", now=now,
        )
        assert consumed_again is False
    asyncio.run(run())
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_provenance_repository.py -v`
Expected: FAIL (missing table/methods)

- [ ] **Step 3: Add table and methods in repository.py**

Add the table in `Repository.__init__`:

```python
self.provenance_challenges = Table(
    "provenance_challenges",
    self.metadata,
    Column("id", String, primary_key=True),
    Column("organization_id", String, nullable=False, index=True),
    Column("transaction_id", String, nullable=False, index=True),
    Column("code", String, nullable=False),
    Column("issued_at", String, nullable=False),
    Column("expires_at", String, nullable=False),
    Column("used_at", String, nullable=True),
    Column("status", String, nullable=False),
    UniqueConstraint("organization_id", "transaction_id", "code", name="uq_provenance_org_txn_code"),
)
```

Implement methods using `insert`, `select`, and a conditional `update`:

```python
async def consume_provenance_challenge(self, *, organization_id: str, transaction_id: str, code: str, now: datetime) -> bool:
    async with self.transaction() as conn:
        result = await conn.execute(
            self.provenance_challenges.update()
            .where(self.provenance_challenges.c.organization_id == organization_id)
            .where(self.provenance_challenges.c.transaction_id == transaction_id)
            .where(self.provenance_challenges.c.code == code)
            .where(self.provenance_challenges.c.status == "active")
            .where(self.provenance_challenges.c.expires_at >= now.isoformat())
            .values(status="used", used_at=now.isoformat())
        )
        return result.rowcount == 1
```

`issue_provenance_challenge` must supersede any active challenge for the same `(organization_id, transaction_id)` in the same transaction before inserting the new one.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_provenance_repository.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/settings.py tests/unit/test_provenance_repository.py
git commit -m "feat(provenance): persist single-use challenges"
```

### Task 6: Provenance issue/verify service and API

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/challenge_extractor.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/integration/test_provenance_challenge.py` (new)

**Interfaces:**
- Produces: `POST /seller/transactions/{id}/provenance-challenge`, `GET /seller/transactions/{id}/provenance-challenge`; service methods `issue_provenance_challenge` and `verify_provenance_submission`; extractor protocol `extract_code(image_bytes, expected_hint) -> {code, confidence, simulated}`.

- [ ] **Step 1: Write failing integration tests**

```python
# Use existing ASGI test app fixture style. Assert:
# - issue returns {code, issued_at, expires_at} with tx short id embedded
# - reissue supersedes previous active challenge
# - submitting provenance with matching extracted code consumes challenge and can pass
# - mismatch/expired routes to review/fail with reason code
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_provenance_challenge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement extractor protocol and adapters**

```python
# apps/verifund_control_plane/verifund_control_plane/challenge_extractor.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ChallengeExtraction:
    code: str | None
    confidence: float
    simulated: bool = False
    provider: str = "unknown"


class ChallengeExtractor(Protocol):
    async def extract_code(self, image_bytes: bytes, *, expected_hint: str | None = None) -> ChallengeExtraction: ...


class FixtureChallengeExtractor:
    async def extract_code(self, image_bytes: bytes, *, expected_hint: str | None = None) -> ChallengeExtraction:
        # Sandbox fixtures bypass vision but still exercise the deterministic comparison path.
        return ChallengeExtraction(code=expected_hint, confidence=1.0, simulated=True, provider="fixture")
```

Wire `app.state.challenge_extractor` in `app.py` (fixture in sandbox mode; LLM adapter when configured, otherwise fixture in tests).

- [ ] **Step 4: Implement service/API/policy logic**

Service: generate code `f"VF{transaction_id[-4:]}-{secrets.token_hex(3).upper()}"` (or a stable project-appropriate format), issue with TTL, return active challenge. In `add_evidence` or verification path for `requirement_id == "provenance"`, call extractor, compare to active challenge, apply deterministic rules from spec §9, and persist finding fields (`reason_code`, `verification_method`, `rule_version`, `confidence`) on the submission.

Policy: treat a consumed matching challenge as the satisfied `challenge_code` check; `CHALLENGE_MISMATCH`/expired/missing produce the reason codes and statuses from spec.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/integration/test_provenance_challenge.py tests/unit/test_provenance_repository.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/challenge_extractor.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/policy.py apps/verifund_control_plane/verifund_control_plane/api/seller.py apps/verifund_control_plane/verifund_control_plane/app.py tests/integration/test_provenance_challenge.py
git commit -m "feat(provenance): issue and verify single-use challenge codes"
```

## Phase 3 — Carrier-authoritative shipment and delivery

### Task 7: Carrier protocol, mock adapter, and shipment tables

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/carrier.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py`
- Test: `tests/unit/test_carrier_adapter.py` (new)
- Test: `tests/unit/test_shipment_repository.py` (new)

**Interfaces:**
- Produces: `CarrierAdapter` protocol (`register_tracking`, `get_tracking_events`, `get_proof_of_delivery`), normalized event shape, `MockCarrierAdapter`, and tables `shipments`, `carrier_events`, `delivery_confirmations` with idempotent inserts.

- [ ] **Step 1: Write failing adapter/repository tests**

```python
import asyncio
from datetime import UTC, datetime

from verifund_control_plane.carrier import CarrierEventStatus, MockCarrierAdapter


def test_mock_carrier_happy_path_events() -> None:
    async def run():
        carrier = MockCarrierAdapter()
        await carrier.register_tracking({"tracking_number": "SANDBOX-happy_path", "scenario": "happy_path"})
        events = await carrier.get_tracking_events("SANDBOX-happy_path")
        statuses = [e["normalized_status"] for e in events]
        assert "PICKED_UP" in statuses
        assert statuses[-1] in {"DELIVERED", "DELIVERED_SIGNED"}
    asyncio.run(run())
```

Repository test: insert same `(carrier_key, provider_event_id)` twice and assert one row.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_carrier_adapter.py tests/unit/test_shipment_repository.py -v`
Expected: FAIL

- [ ] **Step 3: Implement protocol and mock adapter**

Replace the unreferenced `FakeCarrier` in `carrier.py` with the spec-aligned API (or keep a thin compatibility shim if existing reconciler code imports it). `MockCarrierAdapter` must support scenario keys `happy_path, specs_mismatch, packing_photo_missing, weight_anomaly, never_delivers, dispute_seller_wins, dispute_buyer_wins` and return deterministic, ordered events with `provider_event_id`, `normalized_status`, `event_at`, optional `weight_g`, and POD data.

```python
@dataclass(frozen=True)
class NormalizedCarrierEvent:
    provider_event_id: str
    normalized_status: str
    event_at: datetime
    weight_g: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
```

Inject in `app.py`: `app.state.carrier = MockCarrierAdapter(...) if settings.mode in {"fake", "sandbox"} else ...`.

- [ ] **Step 4: Add shipment tables and idempotent writes**

Add `shipments`, `carrier_events`, `delivery_confirmations` tables to `Repository`. Use `sqlite_insert(...).on_conflict_do_nothing(...)` for carrier events on `(carrier_key, provider_event_id)` and for delivery confirmation uniqueness as appropriate.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/unit/test_carrier_adapter.py tests/unit/test_shipment_repository.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/carrier.py apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/app.py tests/unit/test_carrier_adapter.py tests/unit/test_shipment_repository.py
git commit -m "feat(carrier): add shipment tables and mock carrier adapter"
```

### Task 8: Shipment registration and carrier sweeps

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Test: `tests/integration/test_carrier_delivery.py` (new)

**Interfaces:**
- Produces: `POST /seller/transactions/{id}/shipment`, `GET /seller/transactions/{id}/shipment`, `Reconciler._sweep_shipments`, and system satisfaction of `carrier_acceptance` / `delivery_confirmation`.

- [ ] **Step 1: Write failing integration tests**

```python
# Assert: registering tracking creates shipment, reconciler poll ingests PICKED_UP and marks carrier_acceptance satisfied,
# later DELIVERED_SIGNED creates delivery_confirmation and satisfies delivery_confirmation,
# weight_anomaly scenario produces blocker/weight flag, never_delivers produces DELIVERY_TIMEOUT after advancing clock.
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_carrier_delivery.py -v`
Expected: FAIL

- [ ] **Step 3: Implement registration, polling, timeout, and system requirements**

Service: validate seller scope/state/agreement, create shipment from `shipping` requirement/reference, call `carrier.register_tracking`. Reconciler: poll non-terminal shipments, persist events, on acceptance satisfy `carrier_acceptance` in the requirement result/projection inputs, on delivery create `delivery_confirmations` and start inspection, on deadline expiry set blocker/review without refund (D14). Expose shipment read via seller API.

Update `policy.evaluate` so system-owned delivery requirements read from shipment/delivery state (passed into evaluate via terms/context/record or loaded by a small helper), not from seller file uploads.

- [ ] **Step 4: Update lifecycle tests in the same commit**

Modify `tests/integration/test_verifund_lifecycle.py` and any other tests asserting buyer `delivery-confirmed` as authoritative so they now register a shipment, advance reconciler/clock, and reach delivery through carrier events. Keep buyer confirmation as corroboration only.

Run: `uv run pytest tests/integration/test_carrier_delivery.py tests/integration/test_verifund_lifecycle.py -v`

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/seller.py apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/policy.py tests/integration/test_carrier_delivery.py tests/integration/test_verifund_lifecycle.py
git commit -m "feat(delivery): make carrier events authoritative for shipment and delivery"
```

**Phase 3 exit criterion:** `happy_path` carrier flow reaches verified delivery and starts inspection; `never_delivers` blocks on `DELIVERY_TIMEOUT` with no refund; duplicate/out-of-order events are idempotent.


## Phase 4 — Inspection and disputes

### Task 9: Inspection records and deadline handling

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py` (projection exposure)
- Test: `tests/integration/test_inspection_lifecycle.py` (new)

**Interfaces:**
- Produces: `inspection_records` table; inspection created on carrier delivery with deadline = `delivered_at + inspection_window_hours` (default 48, sandbox-compressed, clock-injected); `GET /transactions/{id}/inspection`; accept/dispute transitions; deemed expiry path in reconciler.

- [ ] **Step 1: Write failing tests**

```python
# After delivery, inspection record exists with pending status and correct deadline.
# Buyer accept resolves inspection; advancing clock past deadline with clean requirements expires/resolves per policy;
# advancing clock with an open claim does not auto-release.
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_inspection_lifecycle.py -v`
Expected: FAIL

- [ ] **Step 3: Implement inspection persistence and transitions**

Add `inspection_records` table and repository CRUD. In delivery handling, create inspection atomically with delivery confirmation (or idempotently). Expose status/deadline/resolution in seller/buyer projections. Reconciler sweep: on expiry, if all mandatory requirements pass and no dispute/exception, apply the deemed-acceptance policy path already used by the project but sourced from the inspection record; otherwise emit blocker/review.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_inspection_lifecycle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/api/buyer.py apps/verifund_control_plane/verifund_control_plane/api/seller.py tests/integration/test_inspection_lifecycle.py
git commit -m "feat(inspection): persist inspection records and deadline resolution"
```

### Task 10: Dispute records, claim taxonomy, and buyer evidence path

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Test: `tests/integration/test_dispute_records.py` (new)

**Interfaces:**
- Produces: `disputes` table with `claim_type`, status, resolution, reviewer; buyer dispute endpoint accepts `claim_type`; ops dispute decision persists rationale/resolution; optional buyer evidence upload endpoint for `owner=buyer` requirements.

- [ ] **Step 1: Write failing tests**

```python
# Opening dispute with claim_type=WRONG_DEVICE creates dispute row and blocks payout.
# Ops resolution records reviewer and resolution; seller-win path clears dispute block when other conditions hold.
# Buyer-win path keeps payout blocked and records resolution.
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_dispute_records.py -v`
Expected: FAIL

- [ ] **Step 3: Implement dispute persistence and wiring**

Add `disputes` table and repository methods. Extend `open_dispute` to require/persist `claim_type` (default `OTHER` only for backward compatibility if necessary, but prefer explicit). Extend ops resolution to write the dispute record and transaction event with rationale. Keep `DISPUTE_OPEN` transaction state as the blocking state. If buyer evidence upload is added, mirror seller upload auth/validation but scope to buyer-owned requirements and never expose them in seller workspace.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/integration/test_dispute_records.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/buyer.py apps/verifund_control_plane/verifund_control_plane/api/ops.py packages/verifund_contracts/verifund_contracts/models.py tests/integration/test_dispute_records.py
git commit -m "feat(disputes): persist claim types and resolutions"
```

## Phase 5 — Blockers and workspace

### Task 11: Deterministic blockers and action_owner

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Modify: `apps/console/lib/seller-types.ts`
- Test: `tests/unit/test_release_blockers.py` (new)

**Interfaces:**
- Produces: `blockers[]` with stable codes and messages; derived `action_owner` per requirement; `release.evaluated` transaction event; seller/buyer projections include blockers and action owners.

- [ ] **Step 1: Write failing blocker tests**

```python
def test_blockers_include_requirement_and_delivery_reasons() -> None:
    # Given incomplete hardware and no delivery confirmation, blockers contain
    # REQUIREMENT_INCOMPLETE:hardware and DELIVERY_NOT_VERIFIED (or CARRIER_ACCEPTANCE_MISSING as appropriate).
    ...


def test_action_owner_maps_fail_to_seller_and_review_to_reviewer() -> None:
    # fail + fixable -> seller; review -> reviewer; pass -> none
    ...
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_release_blockers.py -v`
Expected: FAIL

- [ ] **Step 3: Implement blockers**

Add a small `Blocker` model (`code`, `message`, `requirement_id`, `severity`). Compute blockers in policy/service from authoritative state only: requirement results, shipment/delivery records, inspection record, dispute record, payment reconciliation, payout intent state. Refuse `service.release` when blockers exist; keep existing idempotency and ledger guards. Record `release.evaluated` event with blocker list (redacted as needed).

Derive `action_owner` in projection assembly (D13): `pass -> none`, `pending_scan -> none`, `review -> reviewer`, `fail -> seller` unless reason code is terminal/material then `reviewer`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_release_blockers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/policy.py apps/verifund_control_plane/verifund_control_plane/service.py packages/verifund_contracts/verifund_contracts/models.py apps/console/lib/seller-types.ts tests/unit/test_release_blockers.py
git commit -m "feat(release): expose deterministic payout blockers and action owners"
```

### Task 12: Seller workspace staging, blocker panel, provenance and shipment cards

**Files:**
- Modify: `apps/console/app/seller/fulfillment/[id]/page.tsx`
- Modify: `apps/console/app/seller/fulfillment/[id]/evidence/page.tsx`
- Modify: `apps/console/components/seller/requirement-list.tsx`
- Modify: `apps/console/components/seller/upload-evidence-form.tsx`
- Modify: `apps/console/components/seller/dispute-panel.tsx`
- Create: `apps/console/components/seller/blocker-panel.tsx`
- Create: `apps/console/components/seller/provenance-card.tsx`
- Create: `apps/console/components/seller/shipment-timeline.tsx`
- Modify: `apps/console/lib/seller-types.ts`
- Test: `apps/console/**` component tests where they exist; otherwise add focused tests

**Interfaces:**
- Produces: stage-grouped checklist, blocker explanations, provenance code/expiry/regenerate UI, shipment event timeline + weight/POD/signature read-only card, dispute claim type/rung/next step, view-label selector for multi-item requirements.

- [ ] **Step 1: Add failing UI/type tests or contract fixtures**

Assert the seller projection types include `blockers`, `shipment`, `inspection`, per-requirement `action_owner` and `stage`, and that components render blocker messages and stage headings.

- [ ] **Step 2: Run to verify failure**

Run the console test target for the touched area (e.g. `pnpm --filter marketmesh-console test` or the repo's configured command).
Expected: FAIL

- [ ] **Step 3: Implement UI**

Group requirements by stage in deterministic order. Render `blocker-panel` prominently when blockers exist. Render `provenance-card` for the `provenance` requirement using the challenge endpoints. Render `shipment-timeline` from `GET /seller/transactions/{id}/shipment`. Add `view_label` select when `required_views.length > 0`. Keep `mm-*` styling and existing components.

- [ ] **Step 4: Run tests and lint for console**

Run the relevant console tests and typecheck/lint if configured for touched files.
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/console/app/seller/fulfillment apps/console/components/seller apps/console/lib/seller-types.ts
git commit -m "feat(console): show staged evidence, blockers, provenance, and shipment state"
```

## Phase 6 — Scenarios, fixtures, and replay

### Task 13: Fixture set and manifest remap

**Files:**
- Modify: `verifund-test-laptop-evidence/manifest.json`
- Create: `fixtures/laptop/happy_path/**` (and 6 other scenario dirs) or symlink/copy from `verifund-test-laptop-evidence/` with distinct bytes per requirement
- Test: `tests/unit/test_laptop_fixtures.py` (new)

**Interfaces:**
- Produces: deterministic fixtures for all seven scenarios with real requirement ids, unique bytes per requirement, and `simulated: true` metadata.

- [ ] **Step 1: Write failing fixture integrity tests**

```python
import hashlib
import json
from pathlib import Path


def test_fixtures_map_to_real_requirement_ids_and_unique_hashes() -> None:
    manifest = json.loads(Path("verifund-test-laptop-evidence/manifest.json").read_text())
    # assert no legacy ids remain, each mapped requirement file exists,
    # and sha256 values are unique across requirement-bound files.
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/test_laptop_fixtures.py -v`
Expected: FAIL

- [ ] **Step 3: Create/remap fixtures**

Reuse existing images/PDFs/JSON where possible; duplicate and minimally alter bytes when the same file would be reused for two requirements to satisfy the hash-uniqueness constraint. Add scenario-specific files for mismatch, missing packing, weight anomaly evidence context, and dispute cases.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_laptop_fixtures.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add fixtures/laptop verifund-test-laptop-evidence/manifest.json tests/unit/test_laptop_fixtures.py
git commit -m "test(fixtures): add deterministic laptop scenario fixtures"
```

### Task 14: Scenario replay harness and end-to-end assertions

**Files:**
- Create: `scripts/run_scenario.py`
- Create: `tests/integration/test_laptop_scenarios.py` (or `tests/e2e/`)
- Modify: `apps/verifund_control_plane/verifund_control_plane/app.py` / settings only if scenario mode wiring is needed
- Test: the new scenario tests

**Interfaces:**
- Produces: `python scripts/run_scenario.py --scenario <key>` that seeds, replays, and prints final state/blockers/ledger/provider refs; automated tests for all seven scenarios.

- [ ] **Step 1: Write failing scenario tests**

```python
@pytest.mark.parametrize("scenario,expected", [
    ("happy_path", {"payout": "completed"}),
    ("specs_mismatch", {"blocker": "REQUIREMENT_INCOMPLETE:hardware"}),
    ("packing_photo_missing", {"blocker_prefix": "REQUIREMENT_"}),
    ("weight_anomaly", {"blocker": "WEIGHT_ANOMALY"}),
    ("never_delivers", {"blocker": "DELIVERY_TIMEOUT"}),
    ("dispute_seller_wins", {"payout": "completed"}),
    ("dispute_buyer_wins", {"payout": "none"}),
])
def test_laptop_scenario(scenario, expected):
    ...
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_laptop_scenarios.py -v`
Expected: FAIL

- [ ] **Step 3: Implement harness**

Use the injected clock, `MockCarrierAdapter`, `FixtureChallengeExtractor`, fake payment port, and fixture loader. Seed a tenant/agreement/transaction per scenario, submit evidence in the documented order, advance reconciler and clock, assert final transaction state, blockers, ledger entries, and payout/provider references. Label all artifacts `simulated`.

- [ ] **Step 4: Run all seven scenarios**

Run: `uv run pytest tests/integration/test_laptop_scenarios.py -v`
Expected: PASS (7/7)

- [ ] **Step 5: Commit**

```bash
git add scripts/run_scenario.py tests/integration/test_laptop_scenarios.py fixtures/laptop
git commit -m "feat(simulation): add deterministic laptop scenario replay"
```

## Execution and Verification

- [ ] **Full backend verification:** `uv run pytest tests/unit tests/integration -q` (or the project's standard subsets if full suite is too slow locally) with no regressions introduced by P3 lifecycle changes.
- [ ] **Console verification:** run the console's configured typecheck/test commands for touched seller surfaces.
- [ ] **Scenario smoke:** `python scripts/run_scenario.py --scenario happy_path` and `--scenario never_delivers` from a clean database.
- [ ] **Doc alignment:** if implementation reveals a necessary deviation, update `docs/superpowers/specs/2026-11-12-laptop-evidence-fulfillment-design.md` in the same PR/commit series with the rationale.

## Notes for executors

- Read the spec and this plan together. When code and an older doc disagree, follow D1–D14.
- Prefer extending existing helpers (`policy.evaluate`, `project_requirements`, `service.add_evidence`, reconciler sweeps) over parallel implementations.
- Treat any blocker that depends on client input as a bug; blockers come from repository/service state.
- When a step is ambiguous in this codebase, locate the nearest existing pattern (evidence upload, declaration, reconciler sweep, payment adapter wiring) and mirror it rather than inventing a new style.
