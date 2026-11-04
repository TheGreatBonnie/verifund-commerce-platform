# Verifund Seller Evidence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the requirement-driven, buyer-anchored seller evidence flow defined by the target design spec, replacing the hardcoded two-requirement, seller-self-certified flow.

**Architecture:** Contract-first. `Requirement` and `RequirementCheck` become part of agreement terms and are the only source of the seller checklist. Verification returns per-requirement results that roll up into transaction state. Delivery is buyer-attested and carrier-corroborated. Buyer actions use a buyer bearer token. Disputes are evidence-gated and hold funds until a human decides; refunds are a first-class path. Seller list screens get scoped read endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async/aiosqlite, Pydantic v2, pytest/pytest-asyncio, TypeScript/Next.js console, pnpm.

**Spec:** `docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md`

## Global Constraints

- Python `>=3.12`; line length 100; ruff target `py312`.
- Database changes go through `Repository.create_schema()` and fresh-DB tests; there is no Alembic migration in this repo.
- `Requirement.requirement_id` and `RequirementCheck.check_id` are stable across agreement versions; never rename without a migration note.
- AI-derived values contribute `REVIEW` only; deterministic `FAIL` is reserved for directly comparable fields.
- System-owned requirements (`delivery_confirmation`) are never `REMEDIATION_REQUIRED`.
- `ACCEPT` is final and waives later disputes.
- `captured_at` is already collected by intake; it must be surfaced, not re-collected.
- The prototype in `../verifund-seller-fulfillment` is outside this repo and untracked; mirror its ids/formats here, never import from it.

---

## File Structure

- `packages/verifund_contracts/verifund_contracts/models.py` — `Requirement`, `RequirementCheck`, `RequirementResult`, `RequirementCheckResult`, `RequirementStatus`, updates to `EvidenceItem`, `EvidenceSummary`, `VerificationProjection`, `AwardRequest`, `SellerProjection`, `RemedyTerms`.
- `packages/verifund_contracts/verifund_contracts/terms.py` — creation floors for requirements and checks.
- `apps/verifund_control_plane/verifund_control_plane/domain.py` — states, transitions, allowed actions, removal of `REQUIRED_EVIDENCE`.
- `apps/verifund_control_plane/verifund_control_plane/policy.py` — agreement-driven evaluation and rollup.
- `apps/verifund_control_plane/verifund_control_plane/service.py` — verification, buyer actions, projections, seller-scoped reads.
- `apps/verifund_control_plane/verifund_control_plane/repository.py` — schema and persistence for submissions, declarations, buyer tokens, payout reads.
- `apps/verifund_control_plane/verifund_control_plane/evidence.py` — intake allowlist and `captured_at`/`scan_status` on `EvidenceItem`.
- `apps/verifund_control_plane/verifund_control_plane/tokens.py` — buyer token issuance/verification.
- `apps/verifund_control_plane/verifund_control_plane/api/buyer.py` — new buyer routes.
- `apps/verifund_control_plane/verifund_control_plane/api/seller.py` — seller routes and scoped reads.
- `apps/verifund_control_plane/verifund_control_plane/api/ops.py` — narrowed release, dispute decision, resolve-system-failure.
- `apps/buyer_agent/buyer_agent/settlement_flow.py` — buyer-authored requirement catalog.
- `apps/seller_agent/seller_agent/settlement.py` — mandate validation, remove self-certified delivery.
- `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py` — copy requirements into terms.
- `apps/console` — workspace and status vocabulary updates.
- `tests/unit/` — new and updated tests.

---

## Milestone A — catalog and verification

### Task 1: Contract types for requirements and results

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Test: `tests/unit/test_verifund_contracts.py`

**Interfaces:**
- Produces: `Requirement`, `RequirementCheck`, `RequirementStatus`, `RequirementResult`, `RequirementCheckResult`, updated `EvidenceItem`, `EvidenceSummary`, `VerificationProjection`, `AwardRequest`, `SellerProjection`.

- [ ] **Step 1: Write the failing test**

```python
from verifund_contracts import Requirement, RequirementCheck, RequirementResult, RequirementStatus

def test_requirement_rollup_requires_checks():
    req = Requirement(
        requirement_id="hardware",
        title="Hardware diagnostic report",
        description="...",
        owner="seller",
        kind="other",
        source="file",
        accepted_formats=["application/pdf"],
        checks=[RequirementCheck(check_id="ram", description="RAM", expected_value=32, operator="gte", unit="GB", verification_method="deterministic", ai_derived=False)],
        required=True,
    )
    result = RequirementResult(
        requirement_id="hardware",
        kind="other",
        owner="seller",
        source="file",
        status=RequirementStatus.PASS,
        checks=[],
        submissions=[],
        declared_at=None,
        declared_by=None,
        attempt=None,
        reasons=[],
        checked_at=None,
        remediation=None,
    )
    assert req.requirement_id == result.requirement_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -q`
Expected: FAIL with missing names.

- [ ] **Step 3: Write minimal implementation**

Add to `models.py`:

```python
class RequirementStatus(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    PENDING_SCAN = "pending_scan"
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"

class RequirementCheck(VerifundModel):
    check_id: str
    description: str
    expected_value: str | int | float | None = None
    operator: str  # eq | gte | lte | contains | exists
    unit: str | None = None
    verification_method: str
    ai_derived: bool = False

class Requirement(VerifundModel):
    requirement_id: str
    title: str
    description: str
    owner: str  # seller | system | buyer
    kind: str
    source: str  # file | reference
    accepted_formats: list[str] = Field(default_factory=list)
    checks: list[RequirementCheck] = Field(default_factory=list)
    required: bool = True

class RequirementCheckResult(VerifundModel):
    check_id: str
    status: str  # pass | fail | review | not_evaluated
    reasons: list[str] = Field(default_factory=list)
    observed_value: str | int | float | None = None

class RequirementResult(VerifundModel):
    requirement_id: str
    kind: str
    owner: str
    source: str
    status: RequirementStatus
    checks: list[RequirementCheckResult] = Field(default_factory=list)
    submissions: list["EvidenceItem"] = Field(default_factory=list)
    declared_at: datetime | None = None
    declared_by: str | None = None
    attempt: int | None = None
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime | None = None
    remediation: dict[str, Any] | None = None
```

Update `EvidenceItem`:

```python
class EvidenceItem(VerifundModel):
    evidence_id: str
    requirement_id: str | None = None
    kind: str
    sha256: str
    media_type: str
    size_bytes: int
    original_filename: str
    note: str | None = None
    origin: str | None = None  # seller | buyer | carrier | system
    attributed_to: str | None = None
    captured_at: datetime | None = None
    scan_status: str | None = None  # pending | clean | rejected
    agreement_version: int | None = None
    created_at: datetime
```

Replace `EvidenceSummary.required/received/complete` with `requirements: list[RequirementResult]`. Add `requirements` to `VerificationProjection`. Add `requirements: list[Requirement]` to `AwardRequest` with `evidence_required` retained as deprecated mirror. Add `not_as_described` to `RemedyTerms` and `REPAIR_OR_REPLACEMENT` to `RemedyPolicy`. Add `payout` to `SellerProjection` if missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/verifund_contracts/verifund_contracts/models.py tests/unit/test_verifund_contracts.py
git commit -m "feat(contracts): add requirement catalog and result types"
```

### Task 2: Creation floors for requirements and checks

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/terms.py`
- Test: `tests/unit/test_agreement_generator.py` or contract tests

**Interfaces:**
- Consumes: `Requirement`, `RequirementCheck`.
- Produces: validation function `validate_requirements(requirements)`.

- [ ] **Step 1: Write failing test**

```python
def test_requirement_floor_rejects_empty_checks():
    with pytest.raises(ValueError):
        validate_requirements([Requirement(..., checks=[])])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement floors**

Implement `validate_requirements` enforcing:
- non-empty list;
- unique `requirement_id`;
- unique `check_id` within a requirement;
- non-empty `checks`;
- `accepted_formats` non-empty when `source == "file"`;
- `owner` present;
- `expected_value` present when `operator != "exists"` and not AI-derived;
- exactly one system-owned `delivery_confirmation` requirement.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_contracts.py tests/unit/test_agreement_generator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/verifund_contracts/verifund_contracts/terms.py
git commit -m "feat(terms): enforce requirement catalog floors"
```

### Task 3: Buyer agent authors the requirement catalog

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_flow.py`
- Test: `tests/unit/test_buyer_settlement_flow.py`

**Interfaces:**
- Produces: `AwardRequest.requirements` including `product_photos`, `serial`, `hardware`, `warranty`, `shipping`, `delivery_confirmation`, `invoice`.

- [ ] **Step 1: Write failing test**

```python
def test_buyer_authors_seven_requirements():
    request = build_award_request(...)
    ids = [r.requirement_id for r in request.requirements]
    assert ids == ["product_photos", "serial", "hardware", "warranty", "shipping", "delivery_confirmation", "invoice"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_buyer_settlement_flow.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Replace `evidence_required` authoring with `requirements=[...]` per §3.9.2. Keep `evidence_required` as deprecated mirror derived from requirement ids for grandfathered callers.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_buyer_settlement_flow.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/settlement_flow.py
git commit -m "feat(buyer-agent): author requirement catalog"
```

### Task 4: Seller agent mandate validation

**Files:**
- Modify: `apps/seller_agent/seller_agent/settlement.py`
- Test: `tests/unit/test_seller_mandate.py`

**Interfaces:**
- Consumes: `Requirement`.
- Produces: validation error on unsatisfiable requirement.

- [ ] **Step 1: Write failing test**

```python
def test_seller_rejects_unobservable_eq_requirement():
    with pytest.raises(ValueError):
        validate_mandate(requirements_with_unobservable_eq)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_mandate.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Validate every requirement and check against the seller mandate before acceptance. Remove self-certified delivery handling (`settlement.py:25-60`).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_seller_mandate.py tests/unit/test_seller_settlement.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/settlement.py
git commit -m "feat(seller-agent): validate requirement mandate"
```

### Task 5: Agreement generator copies requirements

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py`
- Test: `tests/unit/test_agreement_generator.py`

**Interfaces:**
- Produces: `terms.requirements[]` from `AwardRequest.requirements[]`.

- [ ] **Step 1: Write failing test**

```python
def test_generator_copies_requirements():
    terms = generate_terms(award_request_with_requirements)
    assert [r.requirement_id for r in terms.requirements] == [...]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agreement_generator.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Replace `evidence_required` copy at `generator.py:83` with requirements copy. Keep deprecated mirror.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_agreement_generator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agreements/generator.py
git commit -m "feat(agreements): copy requirements into terms"
```

### Task 6: Grandfathered agreement projection

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_repository_aux.py` or new `tests/unit/test_verifund_grandfathering.py`

**Interfaces:**
- Produces: `project_requirements(agreement)` returning catalog for legacy agreements.

- [ ] **Step 1: Write failing test**

```python
def test_grandfathered_agreement_projects_evidence_required():
    catalog = project_requirements(legacy_agreement)
    assert [r.requirement_id for r in catalog] == legacy_agreement.terms.evidence_required
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_grandfathering.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Project `evidence_required` into `Requirement` entries at read time for `policy_version == 1`. Store `policy_version` on agreement.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_grandfathering.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(service): grandfather legacy agreements into catalog"
```

### Task 7: Remove hardcoded required evidence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/domain.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Test: `tests/unit/test_verifund_agent_service.py` or policy tests

**Interfaces:**
- Consumes: stored agreement terms.

- [ ] **Step 1: Write failing test**

```python
def test_evaluate_uses_agreement_requirements():
    result = evaluate(agreement_with_custom_requirements, evidence)
    assert [r.requirement_id for r in result.requirements] == [r.requirement_id for r in agreement_with_custom_requirements.terms.requirements]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Delete `REQUIRED_EVIDENCE` usage. `evaluate()` takes `AgreementVersion` terms and returns `list[RequirementResult]` plus rollup.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/domain.py apps/verifund_control_plane/verifund_control_plane/policy.py
git commit -m "feat(policy): evaluate against agreement catalog"
```

### Task 8: Per-requirement verification and rollup

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `evaluate() -> (list[RequirementResult], rollup_state)`.

- [ ] **Step 1: Write failing test**

```python
def test_review_wins_over_fail():
    results = evaluate(agreement, evidence_with_review_and_fail)
    assert rollup(results) == "REVIEW_REQUIRED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Implement per-check deterministic comparators. AI-derived checks contribute `REVIEW`. System-owned misses contribute `REVIEW`, not `REMEDIATION_REQUIRED`. Rollup:
- any `REVIEW` → `REVIEW_REQUIRED`;
- else any `FAIL` → `REMEDIATION_REQUIRED`;
- else all `PASS` → `RELEASE_PERMITTED` (subject to acceptance clock);
- seller-owned `NOT_SUBMITTED` before deadline stays pending;
- seller-owned miss at/after deadline → `REMEDIATION_REQUIRED` with `EVIDENCE_DEADLINE_MISSED`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/policy.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(verification): per-requirement rollup"
```

### Task 9: Submission attempts and declarations persistence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_verifund_repository_aux.py`

**Interfaces:**
- Produces: `add_evidence_submission`, `list_submissions`, `add_declaration`, `list_declarations`.

- [ ] **Step 1: Write failing test**

```python
async def test_declaration_records_attempt(repo):
    async with repo.transaction() as conn:
        await repo.add_declaration(conn, "vf_1", "hardware", 1, actor="seller", submission_ids=["sub_1"])
    rows = await repo.list_declarations("vf_1", "hardware")
    assert rows[0]["attempt"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `evidence_submissions` and `requirement_declarations` tables to `create_schema`. Evidence table gains `requirement_id`, `origin`, `attributed_to`, `artifact_type`, `reference`, `agreement_version`, `scan_status`. Keep `UniqueConstraint(transaction_id, sha256)` for blob dedupe.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(repo): submission attempts and declarations"
```

### Task 10: Seller-scoped read endpoints

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Test: `tests/unit/test_verifund_agent_service.py` or new `tests/unit/test_verifund_seller_reads.py`

**Interfaces:**
- Produces: `GET /seller/transactions`, `GET /seller/evidence`, `GET /seller/payouts`.

- [ ] **Step 1: Write failing test**

```python
async def test_seller_list_scoped_by_token():
    response = await client.get("/seller/transactions", headers={"Authorization": f"Bearer {seller_token}"})
    assert all(item["seller_id"] is None for item in response.json()["items"])  # no buyer identity leak
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Implement keyset paging, `counts_by_state`, batched evidence counts, `payout` on `SellerProjection`, `requirement_id` filter on evidence, `captured_at` and `scan_status` on entries. Reject `seller_id` query param.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/seller.py
git commit -m "feat(seller-api): scoped read coverage"
```

### Task 10a: Seller events and agreement reads

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Test: `tests/unit/test_verifund_seller_reads.py`

**Interfaces:**
- Produces: `GET /seller/transactions/{id}/events`, `GET /seller/agreements/{id}`.

- [ ] **Step 1: Write failing test**

```python
async def test_seller_can_read_events_and_agreement():
    events = await client.get("/seller/transactions/vf_1/events", headers=auth)
    agreement = await client.get("/seller/agreements/agr_1", headers=auth)
    assert events.status_code == 200
    assert agreement.json()["terms"]["requirements"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Expose seller-visible events for a transaction and an agreement read including terms/requirements. Enforce seller ownership and token scope.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/seller.py
git commit -m "feat(seller-api): events and agreement reads"
```

---

## Milestone B — buyer anchor and acceptance

### Task 11: Buyer bearer token

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tokens.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_agreement_tokens.py`

**Interfaces:**
- Produces: `issue_buyer_token(buyer_id, transaction_id, scopes=("txn:buy",))`, `verify_buyer_token`.

- [ ] **Step 1: Write failing test**

```python
def test_buyer_token_scope_denied():
    token = issue_buyer_token("buyer_1", "vf_1")
    with pytest.raises(VerifundError):
        verify_buyer_token(token, required_scope="txn:read")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Reuse `SellerTokenService` machinery with `actor_type="buyer"` and `buyer_tokens` table. Bind to `buyer_id` and `transaction_id`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tokens.py apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(auth): buyer bearer token"
```

### Task 12: Buyer API routes

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/main.py` (or router registration)
- Test: `tests/unit/test_verifund_agent_service.py` or new buyer tests

**Interfaces:**
- Produces: `POST /buyer/transactions/{id}/delivery-confirmed`, `/accept`, `/dispute`.

- [ ] **Step 1: Write failing test**

```python
async def test_buyer_delivery_requires_token():
    response = await client.post("/buyer/transactions/vf_1/delivery-confirmed", json={"confirmed_at": "..."})
    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_buyer_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Register buyer router. Enforce buyer bearer token and ownership. Add request models.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_buyer_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/buyer.py
git commit -m "feat(buyer-api): buyer routes"
```

### Task 13: Buyer delivery confirmation and system evidence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/evidence.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `confirm_delivery(transaction_id, buyer_id, confirmed_at, condition, photos)`.

- [ ] **Step 1: Write failing test**

```python
async def test_confirmed_at_out_of_bounds_rejected():
    with pytest.raises(VerifundError):
        await service.confirm_delivery("vf_1", "buyer_1", future_timestamp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Validate `confirmed_at` within ±N hours of carrier event and not in future. Create system-generated, buyer-attributed `delivery_confirmation` evidence (`origin=system`, `attributed_to=buyer`). Start inspection clock at `min(buyer, carrier)` when both agree.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/evidence.py
git commit -m "feat(delivery): buyer-attested carrier-corroborated"
```

### Task 14: Carrier aggregator adapter

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/carrier.py`
- Test: `tests/unit/test_verifund_carrier.py`

**Interfaces:**
- Produces: `CarrierClient.fetch(tracking_number) -> CarrierRecord`.

- [ ] **Step 1: Write failing test**

```python
async def test_carrier_outage_returns_review_not_block():
    client = FakeCarrier(raise_on_call=True)
    record = await client.fetch("1Z...")
    assert record.status == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_carrier.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Define protocol and a fake/in-memory implementation with retry/backoff and ops alert. Real
aggregator behind the same interface, including a PayPal Tracking adapter (Orders v2
`track`, Tracking v1 fallback, carrier-code validation, webhook/polling status updates).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_carrier.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/carrier.py
git commit -m "feat(carrier): aggregator adapter with retry"
```

### Task 15: Acceptance clock and reconciler release

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_reconciler.py`

**Interfaces:**
- Produces: `run_deemed_acceptance()`.

- [ ] **Step 1: Write failing test**

```python
async def test_reconciler_releases_on_deemed_acceptance():
    seed_release_permitted_transaction_past_deadline()
    await reconciler.run_once()
    assert transaction.state == "RELEASED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Use `max(inspection, dispute)` from agreement. Release only if all requirements `PASS` and no dispute. Run verification on `RELEASE_PERMITTED` transactions inside the dispute window so disputes can be opened. Implement `extend_deadline`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(acceptance): deemed acceptance release path"
```

### Task 16: State machine transitions

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/domain.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: transitions for `REMEDIATION_REQUIRED`, `DISPUTE_OPEN`, `REFUNDED`, `ACCEPT`, `CONFIRM_DELIVERY`.

- [ ] **Step 1: Write failing test**

```python
def test_accept_is_final():
    assert "DISPUTE_OPEN" not in allowed_transitions("PAYOUT_PENDING", "buyer")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add states, transitions, upload permissions, stage mapping. `ACCEPT` moves `VERIFICATION_PENDING`/`RELEASE_PERMITTED` → `PAYOUT_PENDING` and is final. `CONFIRM_DELIVERY` records delivery without state change.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/domain.py
git commit -m "feat(state): buyer anchor and dispute transitions"
```

---

## Milestone C — dispute and remediation

### Task 17: First-class refund path

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_verifund_fake_payments.py`

**Interfaces:**
- Produces: `refund(transaction_id, remedy) -> REFUNDED`.

- [ ] **Step 1: Write failing test**

```python
async def test_upheld_refund_moves_to_refunded():
    await service.dispute_decision("vf_1", decision="upheld", remedy="refund")
    assert transaction.state == "REFUNDED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_fake_payments.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

PayPal refund call, ledger reversal, idempotency, webhook handling, terminal `REFUNDED`. Until this ships, captured-fund cancellation stays forbidden.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_fake_payments.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(refunds): first-class refund path"
```

### Task 18: Evidence-gated dispute opening

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `open_dispute(transaction_id, buyer_id, requirement_ids, reason_code, claim, evidence)`.

- [ ] **Step 1: Write failing test**

```python
async def test_dispute_without_artifact_rejected_no_transition():
    result = await service.open_dispute("vf_1", "buyer_1", requirement_ids=["hardware"], reason_code="not_as_described", claim="...", evidence=[])
    assert result.transitioned is False
    assert transaction.state != "DISPUTE_OPEN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Validity rules from §3.8: artifact intake, binding to transaction and agreement version, evaluable claim. Valid dispute opens `DISPUTE_OPEN` from `VERIFICATION_PENDING` or `RELEASE_PERMITTED`. Invalid dispute is audit event, no transition, one retry inside dispute window.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/buyer.py
git commit -m "feat(dispute): evidence-gated opening"
```

### Task 19: Dispute decision and system failure resolution

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `dispute_decision(...)`, `resolve_system_failure(...)`.

- [ ] **Step 1: Write failing test**

```python
async def test_dismissed_dispute_returns_to_release_permitted():
    await service.dispute_decision("vf_1", decision="dismissed")
    assert transaction.state == "RELEASE_PERMITTED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`dispute-decision` records decision, remedy, reviewer. `dismissed` returns to release/verification; `upheld` applies remedy and moves to `REFUNDED` or `REMEDIATION_REQUIRED`; `settled` records split. `resolve-system-failure` releases or cancels system-owned failures.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/ops.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(ops): dispute decisions and system failure resolution"
```

### Task 20: Remediation deadlines and sweeper coverage

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_reconciler.py`

**Interfaces:**
- Produces: `extend_deadline`, remediation sweep.

- [ ] **Step 1: Write failing test**

```python
async def test_remediation_deadline_miss_moves_to_review():
    seed_remediation_past_deadline()
    await reconciler.run_once()
    assert transaction.state == "REVIEW_REQUIRED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Remediation deadline defaults to 72h, extendable. Sweeper covers `VERIFICATION_PENDING` and `REMEDIATION_REQUIRED`. System-owned misses route to `REVIEW`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(remediation): deadlines and sweeper"
```

### Task 21: Storage adapter, scanning, signed URLs

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/evidence.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/storage.py`
- Test: `tests/unit/test_verifund_repository_aux.py`

**Interfaces:**
- Produces: `ObjectStore.put/get/signed_url`.

- [ ] **Step 1: Write failing test**

```python
async def test_evidence_intake_accepts_webp_and_csv():
    item = await store.put(... media_type="image/webp" ...)
    assert item.scan_status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Private object store adapter with SSE, malware scanning status, retention/legal hold, short-lived signed URLs. Keep SHA-256 content addressing. Expand intake allowlist to `image/webp`, video types, `text/csv`, and `artifact_type=reference`. Add `captured_at` to returned `EvidenceItem`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/evidence.py apps/verifund_control_plane/verifund_control_plane/storage.py
git commit -m "feat(storage): object store and intake allowlist"
```

### Task 22: Token reissue on agreement version bump

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Test: `tests/unit/test_agreement_tokens.py`

**Interfaces:**
- Produces: `reissue_seller_token(transaction_id)`.

- [ ] **Step 1: Write failing test**

```python
async def test_version_bump_reissues_seller_token():
    await apply_change_request("vf_1")
    assert latest_seller_token_jti != previous_jti
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Reissue seller tokens on `sync_transaction_pointer` or document invalidation. Add ops endpoint.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/ops.py
git commit -m "feat(tokens): reissue on agreement version bump"
```

---

## Milestone D — console and mock alignment

### Task 23: Console seller app shell and routes

**Files:**
- Create: `apps/console/app/seller/layout.tsx`
- Create: `apps/console/app/seller/dashboard/page.tsx`
- Create: `apps/console/app/seller/orders/page.tsx`
- Create: `apps/console/app/seller/fulfillment/page.tsx`
- Create: `apps/console/app/seller/fulfillment/[id]/page.tsx`
- Create: `apps/console/app/seller/fulfillment/[id]/evidence/page.tsx`
- Create: `apps/console/app/seller/fulfillment/[id]/activity/page.tsx`
- Create: `apps/console/app/seller/evidence/page.tsx`
- Create: `apps/console/app/seller/payouts/page.tsx`
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: seller bearer token, scoped endpoints.

- [ ] **Step 1: Implement**

Mirror prototype routes under `/seller/*`. Each page fetches real scoped endpoints; no mock data. Store seller token from invitation exchange and attach as Bearer.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): seller app shell and routes"
```

### Task 24: Console status vocabulary collapse

**Files:**
- Modify: `apps/console` badge/status map
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: backend transaction state + requirement status.

- [ ] **Step 1: Implement**

Replace two vocabularies with one enum plus transaction-state → label map from §3.9.4. Add `REMEDIATION_REQUIRED`, `DISPUTE_OPEN`, `REFUNDED`. No `REJECTED` evidence badge.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): single status vocabulary"
```

### Task 25: Console upload modal and reference artifacts

**Files:**
- Modify: console upload modal
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: `accepted_formats`, `source`.

- [ ] **Step 1: Implement**

Collect `captured_at`; provide reference/URL input when `source=reference`; render formats from `accepted_formats`; include `image/webp`, video, `text/csv`.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): reference artifacts and captured_at"
```

### Task 26: Console invitation exchange and agreement gating

**Files:**
- Modify: console access screen and agreement view
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: `POST /fulfillment/access/{token}`.

- [ ] **Step 1: Implement**

Wire invitation exchange; gate agreement routes behind auth; add seller agreement read.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): invitation exchange and gated agreement"
```

### Task 27: Mock alignment notes

**Files:**
- Modify: `docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md` (already)
- No code change in external mock.

**Interfaces:**
- Produces: documentation only.

- [ ] **Step 1: Verify mock ids/formats mirrored**

Check `product_photos`, `serial`, `hardware`, `warranty`, `shipping`, `delivery_confirmation`, `invoice` and formats include `image/webp`, video, `text/csv`.

- [ ] **Step 2: Commit documentation if needed**

```bash
git add docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md
git commit -m "docs: align mock and contract ids"
```


---

## Milestone E — PayPal tracking integration

### Task 28: PayPal tracking adapter

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/paypal_tracking.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/carrier.py`
- Test: `tests/unit/test_verifund_paypal_tracking.py`

**Interfaces:**
- Produces: `PayPalTrackingClient.fetch(tracking_number, carrier) -> CarrierRecord`.

- [ ] **Step 1: Write failing test**

```python
async def test_paypal_tracking_returns_delivered():
    client = FakePayPalTracking(status="DELIVERED")
    record = await client.fetch("1Z...", "UPS")
    assert record.status == "delivered"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_paypal_tracking.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

OAuth token handling, Orders v2 `track`, Tracking v1 fallback, carrier-code validation, retry/backoff, ops alert.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_paypal_tracking.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/paypal_tracking.py apps/verifund_control_plane/verifund_control_plane/carrier.py
git commit -m "feat(carrier): PayPal tracking adapter"
```

### Task 29: PayPal tracking webhooks and polling

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_reconciler.py`

**Interfaces:**
- Produces: `handle_paypal_tracking_webhook`, `refresh_paypal_tracking`.

- [ ] **Step 1: Write failing test**

```python
async def test_paypal_tracking_webhook_updates_delivery_requirement():
    await handle_paypal_tracking_webhook(payload_delivered)
    assert delivery_requirement.status == "PASS" if buyer_confirmed else "REVIEW"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Idempotent webhook processing, polling fallback, status mapping, tracker ID persistence, reconciler trigger.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(carrier): PayPal tracking webhooks and polling"
```

---

## Self-Review

1. **Spec coverage:** Every Round 4 decision maps to a task: 28/29 → Task 17-19; 30 → Task 1; 31 → Task 11-12; 32 → Task 13/14/19/20; 33 → Task 9; 34 → Task 8. Earlier decisions map to Tasks 3-8, 13, 15, 16, 21.
2. **Placeholder scan:** Each task includes test code, implementation notes, and commands.
3. **Type consistency:** `RequirementResult` field names are consistent across tasks; `captured_at` and `scan_status` added once.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-04-verifund-seller-evidence-target-implementation.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** - execute in this session using executing-plans, batch execution with checkpoints.

Which approach?
```

Need save to exact path. Use write.<|end|><|start|> fileList? Let's write.<|end|><|start|>startup to=write<|channel|>analysis <|constrain|>xml<|message|><rfl:parameter name="content">
# Verifund Seller Evidence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the requirement-driven, buyer-anchored seller evidence flow defined by the target design spec, replacing the hardcoded two-requirement, seller-self-certified flow.

**Architecture:** Contract-first. `Requirement` and `RequirementCheck` become part of agreement terms and are the only source of the seller checklist. Verification returns per-requirement results that roll up into transaction state. Delivery is buyer-attested and carrier-corroborated. Buyer actions use a buyer bearer token. Disputes are evidence-gated and hold funds until a human decides; refunds are a first-class path. Seller list screens get scoped read endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async/aiosqlite, Pydantic v2, pytest/pytest-asyncio, TypeScript/Next.js console, pnpm.

**Spec:** `docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md`

## Global Constraints

- Python `>=3.12`; line length 100; ruff target `py312`.
- Database changes go through `Repository.create_schema()` and fresh-DB tests; there is no Alembic migration in this repo.
- `Requirement.requirement_id` and `RequirementCheck.check_id` are stable across agreement versions; never rename without a migration note.
- AI-derived values contribute `REVIEW` only; deterministic `FAIL` is reserved for directly comparable fields.
- System-owned requirements (`delivery_confirmation`) are never `REMEDIATION_REQUIRED`.
- `ACCEPT` is final and waives later disputes.
- `captured_at` is already collected by intake; it must be surfaced, not re-collected.
- The prototype in `../verifund-seller-fulfillment` is outside this repo and untracked; mirror its ids/formats here, never import from it.

---

## File Structure

- `packages/verifund_contracts/verifund_contracts/models.py` — `Requirement`, `RequirementCheck`, `RequirementResult`, `RequirementCheckResult`, `RequirementStatus`, updates to `EvidenceItem`, `EvidenceSummary`, `VerificationProjection`, `AwardRequest`, `SellerProjection`, `RemedyTerms`.
- `packages/verifund_contracts/verifund_contracts/terms.py` — creation floors for requirements and checks.
- `apps/verifund_control_plane/verifund_control_plane/domain.py` — states, transitions, allowed actions, removal of `REQUIRED_EVIDENCE`.
- `apps/verifund_control_plane/verifund_control_plane/policy.py` — agreement-driven evaluation and rollup.
- `apps/verifund_control_plane/verifund_control_plane/service.py` — verification, buyer actions, projections, seller-scoped reads.
- `apps/verifund_control_plane/verifund_control_plane/repository.py` — schema and persistence for submissions, declarations, buyer tokens, payout reads.
- `apps/verifund_control_plane/verifund_control_plane/evidence.py` — intake allowlist and `captured_at`/`scan_status` on `EvidenceItem`.
- `apps/verifund_control_plane/verifund_control_plane/tokens.py` — buyer token issuance/verification.
- `apps/verifund_control_plane/verifund_control_plane/api/buyer.py` — new buyer routes.
- `apps/verifund_control_plane/verifund_control_plane/api/seller.py` — seller routes and scoped reads.
- `apps/verifund_control_plane/verifund_control_plane/api/ops.py` — narrowed release, dispute decision, resolve-system-failure.
- `apps/buyer_agent/buyer_agent/settlement_flow.py` — buyer-authored requirement catalog.
- `apps/seller_agent/seller_agent/settlement.py` — mandate validation, remove self-certified delivery.
- `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py` — copy requirements into terms.
- `apps/console` — workspace and status vocabulary updates.
- `tests/unit/` — new and updated tests.

---

## Milestone A — catalog and verification

### Task 1: Contract types for requirements and results

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/models.py`
- Test: `tests/unit/test_verifund_contracts.py`

**Interfaces:**
- Produces: `Requirement`, `RequirementCheck`, `RequirementStatus`, `RequirementResult`, `RequirementCheckResult`, updated `EvidenceItem`, `EvidenceSummary`, `VerificationProjection`, `AwardRequest`, `SellerProjection`.

- [ ] **Step 1: Write the failing test**

```python
from verifund_contracts import Requirement, RequirementCheck, RequirementResult, RequirementStatus

def test_requirement_rollup_requires_checks():
    req = Requirement(
        requirement_id="hardware",
        title="Hardware diagnostic report",
        description="...",
        owner="seller",
        kind="other",
        source="file",
        accepted_formats=["application/pdf"],
        checks=[RequirementCheck(check_id="ram", description="RAM", expected_value=32, operator="gte", unit="GB", verification_method="deterministic", ai_derived=False)],
        required=True,
    )
    result = RequirementResult(
        requirement_id="hardware",
        kind="other",
        owner="seller",
        source="file",
        status=RequirementStatus.PASS,
        checks=[],
        submissions=[],
        declared_at=None,
        declared_by=None,
        attempt=None,
        reasons=[],
        checked_at=None,
        remediation=None,
    )
    assert req.requirement_id == result.requirement_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -q`
Expected: FAIL with missing names.

- [ ] **Step 3: Write minimal implementation**

Add to `models.py`:

```python
class RequirementStatus(StrEnum):
    NOT_SUBMITTED = "not_submitted"
    PENDING_SCAN = "pending_scan"
    PASS = "pass"
    FAIL = "fail"
    REVIEW = "review"

class RequirementCheck(VerifundModel):
    check_id: str
    description: str
    expected_value: str | int | float | None = None
    operator: str  # eq | gte | lte | contains | exists
    unit: str | None = None
    verification_method: str
    ai_derived: bool = False

class Requirement(VerifundModel):
    requirement_id: str
    title: str
    description: str
    owner: str  # seller | system | buyer
    kind: str
    source: str  # file | reference
    accepted_formats: list[str] = Field(default_factory=list)
    checks: list[RequirementCheck] = Field(default_factory=list)
    required: bool = True

class RequirementCheckResult(VerifundModel):
    check_id: str
    status: str  # pass | fail | review | not_evaluated
    reasons: list[str] = Field(default_factory=list)
    observed_value: str | int | float | None = None

class RequirementResult(VerifundModel):
    requirement_id: str
    kind: str
    owner: str
    source: str
    status: RequirementStatus
    checks: list[RequirementCheckResult] = Field(default_factory=list)
    submissions: list["EvidenceItem"] = Field(default_factory=list)
    declared_at: datetime | None = None
    declared_by: str | None = None
    attempt: int | None = None
    reasons: list[str] = Field(default_factory=list)
    checked_at: datetime | None = None
    remediation: dict[str, Any] | None = None
```

Update `EvidenceItem`:

```python
class EvidenceItem(VerifundModel):
    evidence_id: str
    requirement_id: str | None = None
    kind: str
    sha256: str
    media_type: str
    size_bytes: int
    original_filename: str
    note: str | None = None
    origin: str | None = None  # seller | buyer | carrier | system
    attributed_to: str | None = None
    captured_at: datetime | None = None
    scan_status: str | None = None  # pending | clean | rejected
    agreement_version: int | None = None
    created_at: datetime
```

Replace `EvidenceSummary.required/received/complete` with `requirements: list[RequirementResult]`. Add `requirements` to `VerificationProjection`. Add `requirements: list[Requirement]` to `AwardRequest` with `evidence_required` retained as deprecated mirror. Add `not_as_described` to `RemedyTerms` and `REPAIR_OR_REPLACEMENT` to `RemedyPolicy`. Add `payout` to `SellerProjection` if missing.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/verifund_contracts/verifund_contracts/models.py tests/unit/test_verifund_contracts.py
git commit -m "feat(contracts): add requirement catalog and result types"
```

### Task 2: Creation floors for requirements and checks

**Files:**
- Modify: `packages/verifund_contracts/verifund_contracts/terms.py`
- Test: `tests/unit/test_agreement_generator.py` or contract tests

**Interfaces:**
- Consumes: `Requirement`, `RequirementCheck`.
- Produces: validation function `validate_requirements(requirements)`.

- [ ] **Step 1: Write failing test**

```python
def test_requirement_floor_rejects_empty_checks():
    with pytest.raises(ValueError):
        validate_requirements([Requirement(..., checks=[])])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_contracts.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement floors**

Implement `validate_requirements` enforcing:
- non-empty list;
- unique `requirement_id`;
- unique `check_id` within a requirement;
- non-empty `checks`;
- `accepted_formats` non-empty when `source == "file"`;
- `owner` present;
- `expected_value` present when `operator != "exists"` and not AI-derived;
- exactly one system-owned `delivery_confirmation` requirement.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_contracts.py tests/unit/test_agreement_generator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/verifund_contracts/verifund_contracts/terms.py
git commit -m "feat(terms): enforce requirement catalog floors"
```

### Task 3: Buyer agent authors the requirement catalog

**Files:**
- Modify: `apps/buyer_agent/buyer_agent/settlement_flow.py`
- Test: `tests/unit/test_buyer_settlement_flow.py`

**Interfaces:**
- Produces: `AwardRequest.requirements` including `product_photos`, `serial`, `hardware`, `warranty`, `shipping`, `delivery_confirmation`, `invoice`.

- [ ] **Step 1: Write failing test**

```python
def test_buyer_authors_seven_requirements():
    request = build_award_request(...)
    ids = [r.requirement_id for r in request.requirements]
    assert ids == ["product_photos", "serial", "hardware", "warranty", "shipping", "delivery_confirmation", "invoice"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_buyer_settlement_flow.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Replace `evidence_required` authoring with `requirements=[...]` per §3.9.2. Keep `evidence_required` as deprecated mirror derived from requirement ids for grandfathered callers.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_buyer_settlement_flow.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/buyer_agent/buyer_agent/settlement_flow.py
git commit -m "feat(buyer-agent): author requirement catalog"
```

### Task 4: Seller agent mandate validation

**Files:**
- Modify: `apps/seller_agent/seller_agent/settlement.py`
- Test: `tests/unit/test_seller_mandate.py`

**Interfaces:**
- Consumes: `Requirement`.
- Produces: validation error on unsatisfiable requirement.

- [ ] **Step 1: Write failing test**

```python
def test_seller_rejects_unobservable_eq_requirement():
    with pytest.raises(ValueError):
        validate_mandate(requirements_with_unobservable_eq)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_mandate.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Validate every requirement and check against the seller mandate before acceptance. Remove self-certified delivery handling (`settlement.py:25-60`).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_seller_mandate.py tests/unit/test_seller_settlement.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/seller_agent/seller_agent/settlement.py
git commit -m "feat(seller-agent): validate requirement mandate"
```

### Task 5: Agreement generator copies requirements

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py`
- Test: `tests/unit/test_agreement_generator.py`

**Interfaces:**
- Produces: `terms.requirements[]` from `AwardRequest.requirements[]`.

- [ ] **Step 1: Write failing test**

```python
def test_generator_copies_requirements():
    terms = generate_terms(award_request_with_requirements)
    assert [r.requirement_id for r in terms.requirements] == [...]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agreement_generator.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Replace `evidence_required` copy at `generator.py:83` with requirements copy. Keep deprecated mirror.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_agreement_generator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/agreements/generator.py
git commit -m "feat(agreements): copy requirements into terms"
```

### Task 6: Grandfathered agreement projection

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_grandfathering.py`

**Interfaces:**
- Produces: `project_requirements(agreement)` returning catalog for legacy agreements.

- [ ] **Step 1: Write failing test**

```python
def test_grandfathered_agreement_projects_evidence_required():
    catalog = project_requirements(legacy_agreement)
    assert [r.requirement_id for r in catalog] == legacy_agreement.terms.evidence_required
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_grandfathering.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Project `evidence_required` into `Requirement` entries at read time for `policy_version == 1`. Store `policy_version` on agreement.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_grandfathering.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(service): grandfather legacy agreements into catalog"
```

### Task 7: Remove hardcoded required evidence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/domain.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Consumes: stored agreement terms.

- [ ] **Step 1: Write failing test**

```python
def test_evaluate_uses_agreement_requirements():
    result = evaluate(agreement_with_custom_requirements, evidence)
    assert [r.requirement_id for r in result.requirements] == [r.requirement_id for r in agreement_with_custom_requirements.terms.requirements]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Delete `REQUIRED_EVIDENCE` usage. `evaluate()` takes `AgreementVersion` terms and returns `list[RequirementResult]` plus rollup.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/domain.py apps/verifund_control_plane/verifund_control_plane/policy.py
git commit -m "feat(policy): evaluate against agreement catalog"
```

### Task 8: Per-requirement verification and rollup

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/policy.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `evaluate() -> (list[RequirementResult], rollup_state)`.

- [ ] **Step 1: Write failing test**

```python
def test_review_wins_over_fail():
    results = evaluate(agreement, evidence_with_review_and_fail)
    assert rollup(results) == "REVIEW_REQUIRED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Implement per-check deterministic comparators. AI-derived checks contribute `REVIEW`. System-owned misses contribute `REVIEW`, not `REMEDIATION_REQUIRED`. Rollup:
- any `REVIEW` → `REVIEW_REQUIRED`;
- else any `FAIL` → `REMEDIATION_REQUIRED`;
- else all `PASS` → `RELEASE_PERMITTED` (subject to acceptance clock);
- seller-owned `NOT_SUBMITTED` before deadline stays pending;
- seller-owned miss at/after deadline → `REMEDIATION_REQUIRED` with `EVIDENCE_DEADLINE_MISSED`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/policy.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(verification): per-requirement rollup"
```

### Task 9: Submission attempts and declarations persistence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_verifund_repository_aux.py`

**Interfaces:**
- Produces: `add_evidence_submission`, `list_submissions`, `add_declaration`, `list_declarations`.

- [ ] **Step 1: Write failing test**

```python
async def test_declaration_records_attempt(repo):
    async with repo.transaction() as conn:
        await repo.add_declaration(conn, "vf_1", "hardware", 1, actor="seller", submission_ids=["sub_1"])
    rows = await repo.list_declarations("vf_1", "hardware")
    assert rows[0]["attempt"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `evidence_submissions` and `requirement_declarations` tables to `create_schema`. Evidence table gains `requirement_id`, `origin`, `attributed_to`, `artifact_type`, `reference`, `agreement_version`, `scan_status`. Keep `UniqueConstraint(transaction_id, sha256)` for blob dedupe.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(repo): submission attempts and declarations"
```

### Task 10: Seller-scoped read endpoints

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Test: `tests/unit/test_verifund_seller_reads.py`

**Interfaces:**
- Produces: `GET /seller/transactions`, `GET /seller/evidence`, `GET /seller/payouts`.

- [ ] **Step 1: Write failing test**

```python
async def test_seller_list_scoped_by_token():
    response = await client.get("/seller/transactions", headers={"Authorization": f"Bearer {seller_token}"})
    assert all(item["seller_id"] is None for item in response.json()["items"])  # no buyer identity leak
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Implement keyset paging, `counts_by_state`, batched evidence counts, `payout` on `SellerProjection`, `requirement_id` filter on evidence, `captured_at` and `scan_status` on entries. Reject `seller_id` query param.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_seller_reads.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/seller.py
git commit -m "feat(seller-api): scoped read coverage"
```

---

## Milestone B — buyer anchor and acceptance

### Task 11: Buyer bearer token

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tokens.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_agreement_tokens.py`

**Interfaces:**
- Produces: `issue_buyer_token(buyer_id, transaction_id, scopes=("txn:buy",))`, `verify_buyer_token`.

- [ ] **Step 1: Write failing test**

```python
def test_buyer_token_scope_denied():
    token = issue_buyer_token("buyer_1", "vf_1")
    with pytest.raises(VerifundError):
        verify_buyer_token(token, required_scope="txn:read")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Reuse `SellerTokenService` machinery with `actor_type="buyer"` and `buyer_tokens` table. Bind to `buyer_id` and `transaction_id`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tokens.py apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(auth): buyer bearer token"
```

### Task 12: Buyer API routes

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/main.py` (or router registration)
- Test: `tests/unit/test_verifund_buyer_api.py`

**Interfaces:**
- Produces: `POST /buyer/transactions/{id}/delivery-confirmed`, `/accept`, `/dispute`.

- [ ] **Step 1: Write failing test**

```python
async def test_buyer_delivery_requires_token():
    response = await client.post("/buyer/transactions/vf_1/delivery-confirmed", json={"confirmed_at": "..."})
    assert response.status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_buyer_api.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Register buyer router. Enforce buyer bearer token and ownership. Add request models.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_buyer_api.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/buyer.py
git commit -m "feat(buyer-api): buyer routes"
```

### Task 13: Buyer delivery confirmation and system evidence

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/evidence.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `confirm_delivery(transaction_id, buyer_id, confirmed_at, condition, photos)`.

- [ ] **Step 1: Write failing test**

```python
async def test_confirmed_at_out_of_bounds_rejected():
    with pytest.raises(VerifundError):
        await service.confirm_delivery("vf_1", "buyer_1", future_timestamp)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Validate `confirmed_at` within ±N hours of carrier event and not in future. Create system-generated, buyer-attributed `delivery_confirmation` evidence (`origin=system`, `attributed_to=buyer`). Start inspection clock at `min(buyer, carrier)` when both agree.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/evidence.py
git commit -m "feat(delivery): buyer-attested carrier-corroborated"
```

### Task 14: Carrier aggregator adapter

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/carrier.py`
- Test: `tests/unit/test_verifund_carrier.py`

**Interfaces:**
- Produces: `CarrierClient.fetch(tracking_number) -> CarrierRecord`.

- [ ] **Step 1: Write failing test**

```python
async def test_carrier_outage_returns_review_not_block():
    client = FakeCarrier(raise_on_call=True)
    record = await client.fetch("1Z...")
    assert record.status == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_carrier.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Define protocol and a fake/in-memory implementation with retry/backoff and ops alert. Real
aggregator behind the same interface, including a PayPal Tracking adapter (Orders v2
`track`, Tracking v1 fallback, carrier-code validation, webhook/polling status updates).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_carrier.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/carrier.py
git commit -m "feat(carrier): aggregator adapter with retry"
```

### Task 15: Acceptance clock and reconciler release

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_reconciler.py`

**Interfaces:**
- Produces: `run_deemed_acceptance()`.

- [ ] **Step 1: Write failing test**

```python
async def test_reconciler_releases_on_deemed_acceptance():
    seed_release_permitted_transaction_past_deadline()
    await reconciler.run_once()
    assert transaction.state == "RELEASED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Use `max(inspection, dispute)` from agreement. Release only if all requirements `PASS` and no dispute. Run verification on `RELEASE_PERMITTED` transactions inside the dispute window so disputes can be opened. Implement `extend_deadline`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(acceptance): deemed acceptance release path"
```

### Task 16: State machine transitions

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/domain.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: transitions for `REMEDIATION_REQUIRED`, `DISPUTE_OPEN`, `REFUNDED`, `ACCEPT`, `CONFIRM_DELIVERY`.

- [ ] **Step 1: Write failing test**

```python
def test_accept_is_final():
    assert "DISPUTE_OPEN" not in allowed_transitions("PAYOUT_PENDING", "buyer")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add states, transitions, upload permissions, stage mapping. `ACCEPT` moves `VERIFICATION_PENDING`/`RELEASE_PERMITTED` → `PAYOUT_PENDING` and is final. `CONFIRM_DELIVERY` records delivery without state change.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/domain.py
git commit -m "feat(state): buyer anchor and dispute transitions"
```

---

## Milestone C — dispute and remediation

### Task 17: First-class refund path

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Test: `tests/unit/test_verifund_fake_payments.py`

**Interfaces:**
- Produces: `refund(transaction_id, remedy) -> REFUNDED`.

- [ ] **Step 1: Write failing test**

```python
async def test_upheld_refund_moves_to_refunded():
    await service.dispute_decision("vf_1", decision="upheld", remedy="refund")
    assert transaction.state == "REFUNDED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_fake_payments.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

PayPal refund call, ledger reversal, idempotency, webhook handling, terminal `REFUNDED`. Until this ships, captured-fund cancellation stays forbidden.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_fake_payments.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(refunds): first-class refund path"
```

### Task 18: Evidence-gated dispute opening

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `open_dispute(transaction_id, buyer_id, requirement_ids, reason_code, claim, evidence)`.

- [ ] **Step 1: Write failing test**

```python
async def test_dispute_without_artifact_rejected_no_transition():
    result = await service.open_dispute("vf_1", "buyer_1", requirement_ids=["hardware"], reason_code="not_as_described", claim="...", evidence=[])
    assert result.transitioned is False
    assert transaction.state != "DISPUTE_OPEN"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Validity rules from §3.8: artifact intake, binding to transaction and agreement version, evaluable claim. Valid dispute opens `DISPUTE_OPEN` from `VERIFICATION_PENDING` or `RELEASE_PERMITTED`. Invalid dispute is audit event, no transition, one retry inside dispute window.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/buyer.py
git commit -m "feat(dispute): evidence-gated opening"
```

### Task 19: Dispute decision and system failure resolution

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_agent_service.py`

**Interfaces:**
- Produces: `dispute_decision(...)`, `resolve_system_failure(...)`.

- [ ] **Step 1: Write failing test**

```python
async def test_dismissed_dispute_returns_to_release_permitted():
    await service.dispute_decision("vf_1", decision="dismissed")
    assert transaction.state == "RELEASE_PERMITTED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`dispute-decision` records decision, remedy, reviewer. `dismissed` returns to release/verification; `upheld` applies remedy and moves to `REFUNDED` or `REMEDIATION_REQUIRED`; `settled` records split. `resolve-system-failure` releases or cancels system-owned failures.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/ops.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(ops): dispute decisions and system failure resolution"
```

### Task 20: Remediation deadlines and sweeper coverage

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_reconciler.py`

**Interfaces:**
- Produces: `extend_deadline`, remediation sweep.

- [ ] **Step 1: Write failing test**

```python
async def test_remediation_deadline_miss_moves_to_review():
    seed_remediation_past_deadline()
    await reconciler.run_once()
    assert transaction.state == "REVIEW_REQUIRED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Remediation deadline defaults to 72h, extendable. Sweeper covers `VERIFICATION_PENDING` and `REMEDIATION_REQUIRED`. System-owned misses route to `REVIEW`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(remediation): deadlines and sweeper"
```

### Task 21: Storage adapter, scanning, signed URLs

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/evidence.py`
- Create: `apps/verifund_control_plane/verifund_control_plane/storage.py`
- Test: `tests/unit/test_verifund_repository_aux.py`

**Interfaces:**
- Produces: `ObjectStore.put/get/signed_url`.

- [ ] **Step 1: Write failing test**

```python
async def test_evidence_intake_accepts_webp_and_csv():
    item = await store.put(... media_type="image/webp" ...)
    assert item.scan_status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Private object store adapter with SSE, malware scanning status, retention/legal hold, short-lived signed URLs. Keep SHA-256 content addressing. Expand intake allowlist to `image/webp`, video types, `text/csv`, and `artifact_type=reference`. Add `captured_at` to returned `EvidenceItem`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/evidence.py apps/verifund_control_plane/verifund_control_plane/storage.py
git commit -m "feat(storage): object store and intake allowlist"
```

### Task 22: Token reissue on agreement version bump

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Test: `tests/unit/test_agreement_tokens.py`

**Interfaces:**
- Produces: `reissue_seller_token(transaction_id)`.

- [ ] **Step 1: Write failing test**

```python
async def test_version_bump_reissues_seller_token():
    await apply_change_request("vf_1")
    assert latest_seller_token_jti != previous_jti
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Reissue seller tokens on `sync_transaction_pointer` or document invalidation. Add ops endpoint.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/api/ops.py
git commit -m "feat(tokens): reissue on agreement version bump"
```

---

## Milestone D — console and mock alignment

### Task 23: Console seller app shell and routes

**Files:**
- Create: `apps/console/app/seller/layout.tsx`
- Create: `apps/console/app/seller/dashboard/page.tsx`
- Create: `apps/console/app/seller/orders/page.tsx`
- Create: `apps/console/app/seller/fulfillment/page.tsx`
- Create: `apps/console/app/seller/fulfillment/[id]/page.tsx`
- Create: `apps/console/app/seller/fulfillment/[id]/evidence/page.tsx`
- Create: `apps/console/app/seller/fulfillment/[id]/activity/page.tsx`
- Create: `apps/console/app/seller/evidence/page.tsx`
- Create: `apps/console/app/seller/payouts/page.tsx`
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: seller bearer token, scoped endpoints.

- [ ] **Step 1: Implement**

Mirror prototype routes under `/seller/*`. Each page fetches real scoped endpoints; no mock data. Store seller token from invitation exchange and attach as Bearer.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): seller app shell and routes"
```

### Task 24: Console status vocabulary collapse

**Files:**
- Modify: `apps/console` badge/status map
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: backend transaction state + requirement status.

- [ ] **Step 1: Implement**

Replace two vocabularies with one enum plus transaction-state → label map from §3.9.4. Add `REMEDIATION_REQUIRED`, `DISPUTE_OPEN`, `REFUNDED`. No `REJECTED` evidence badge.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): single status vocabulary"
```

### Task 25: Console upload modal and reference artifacts

**Files:**
- Modify: console upload modal
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: `accepted_formats`, `source`.

- [ ] **Step 1: Implement**

Collect `captured_at`; provide reference/URL input when `source=reference`; render formats from `accepted_formats`; include `image/webp`, video, `text/csv`.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): reference artifacts and captured_at"
```

### Task 26: Console invitation exchange and agreement gating

**Files:**
- Modify: console access screen and agreement view
- Test: `cd apps/console && pnpm run typecheck`

**Interfaces:**
- Consumes: `POST /fulfillment/access/{token}`.

- [ ] **Step 1: Implement**

Wire invitation exchange; gate agreement routes behind auth; add seller agreement read.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && pnpm run typecheck`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/console
git commit -m "feat(console): invitation exchange and gated agreement"
```

### Task 27: Mock alignment notes

**Files:**
- Modify: `docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md` (already)
- No code change in external mock.

**Interfaces:**
- Produces: documentation only.

- [ ] **Step 1: Verify mock ids/formats mirrored**

Check `product_photos`, `serial`, `hardware`, `warranty`, `shipping`, `delivery_confirmation`, `invoice` and formats include `image/webp`, video, `text/csv`.

- [ ] **Step 2: Commit documentation if needed**

```bash
git add docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md
git commit -m "docs: align mock and contract ids"
```

---

## Self-Review

1. **Spec coverage:** Every Round 4 decision maps to a task: 28/29 → Task 17-19; 30 → Task 1; 31 → Task 11-12; 32 → Task 13/14/19/20; 33 → Task 9; 34 → Task 8. Earlier decisions map to Tasks 3-8, 13, 15, 16, 21.
2. **Placeholder scan:** Each task includes test code, implementation notes, and commands.
3. **Type consistency:** `RequirementResult` field names are consistent across tasks; `captured_at` and `scan_status` added once.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-04-verifund-seller-evidence-target-implementation.md`.

Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** - execute in this session using executing-plans, batch execution with checkpoints.

Which approach?
