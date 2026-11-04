# Verifund Seller Evidence — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the requirement-driven, buyer-anchored seller evidence flow defined by the target design spec, replacing the hardcoded two-requirement, seller-self-certified flow.

**Architecture:** Contract-first. `Requirement` and `RequirementCheck` become part of agreement terms and are the only source of the seller checklist. Verification returns per-requirement results that roll up into transaction state. Delivery is buyer-attested and carrier-corroborated. Buyer actions use a buyer bearer token. Disputes are evidence-gated and hold funds until a human decides; refunds are a first-class path. Seller list screens get scoped read endpoints.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async/aiosqlite, Pydantic v2, pytest/pytest-asyncio, TypeScript/Next.js console, pnpm.

**Spec:** `docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md`

> **Locked 2026-11-04 (post-analysis grill, see spec §2 Round 5):** PayPal Tracking is outbound-only — Tasks 28/29 rewritten (tracker sync at ship time, ops visibility, no `PASS`/`FAIL` path); legacy `kind` rejected; zero-submission declarations rejected; buyer token ops-issued; invitation ops-issued single-use with `txn:read`+`evidence:write`; dispute counter-evidence stored as `evidence.purpose='dispute'`; execution mode locked to **subagent-driven**.
> **Revision 2026-11-04 (post-analysis pass):** fixed truncated/corrupted file
> (stray transcript + duplicate copy removed; see git history), fixed Task 10 test
> (`seller_id` KeyError), Task 17 test (used `dispute_decision` before Task 19;
> now tests `refund()` directly), Task 14 (PayPal Tracking adapter moved solely
> to Milestone E), Task 1 (test name, `ReviewReason` typed reasons), Task 9
> (added `submission_attempt`), and added coverage for the spec §5 surface that
> had no task: **Task 9a** (upload re-addressing by `requirement_id`), **Task 10a**
> (seller events/agreement reads), **Task 10b** (declaration endpoints),
> **Task 12a** (ops-issued buyer token), **Task 12b** (invitation exchange +
> agreement route gating), **Task 18a** (dispute counter-evidence), **Task 19a**
> (ops release narrowing, non-overridable reasons, `return-to-remediation`),
> **Task 20a** (PENDING_SCAN sweep + re-verification), **Task 22a** (seller
> token compensating controls). All flagged decisions were locked in the same session — see the **Locked 2026-11-04** note above and spec §2 Round 5.

## Global Constraints

- Python `>=3.12`; line length 100; ruff target `py312`.
- Database changes go through `Repository.create_schema()` and fresh-DB tests; there is no Alembic migration in this repo.
- `Requirement.requirement_id` and `RequirementCheck.check_id` are stable across agreement versions; never rename without a migration note.
- AI-derived values contribute `REVIEW` only; deterministic `FAIL` is reserved for directly comparable fields.
- System-owned requirements (`delivery_confirmation`) are never `REMEDIATION_REQUIRED`.
- `ACCEPT` is final and waives later disputes.
- `captured_at` is already collected by intake; it must be surfaced, not re-collected.
- The prototype in `../verifund-seller-fulfillment` is outside this repo and untracked; mirror its ids/formats here, never import from it.
- PayPal Tracking never feeds verification, rollup, or the release gate; it is an outbound registration + ops visibility surface (spec §2 Round 5, decision 35).

---

## File Structure

- `packages/verifund_contracts/verifund_contracts/models.py` — `Requirement`, `RequirementCheck`, `RequirementResult`, `RequirementCheckResult`, `RequirementStatus`, updates to `EvidenceItem`, `EvidenceSummary`, `VerificationProjection`, `AwardRequest`, `SellerProjection`, `RemedyTerms`.
- `packages/verifund_contracts/verifund_contracts/terms.py` — creation floors for requirements and checks.
- `apps/verifund_control_plane/verifund_control_plane/domain.py` — states, transitions, allowed actions, removal of `REQUIRED_EVIDENCE`.
- `apps/verifund_control_plane/verifund_control_plane/policy.py` — agreement-driven evaluation and rollup.
- `apps/verifund_control_plane/verifund_control_plane/service.py` — verification, buyer actions, projections, seller-scoped reads.
- `apps/verifund_control_plane/verifund_control_plane/repository.py` — schema and persistence for submissions, declarations, buyer tokens, payout reads.
- `apps/verifund_control_plane/verifund_control_plane/evidence.py` — intake allowlist, `artifact_type=reference`, `purpose` (`requirement|dispute`), and `captured_at`/`scan_status` on `EvidenceItem`.
- `apps/verifund_control_plane/verifund_control_plane/storage.py` — private object store adapter, SSE, signed URLs, scan-status callback.
- `apps/verifund_control_plane/verifund_control_plane/carrier.py` — `CarrierClient` protocol, fake implementation, retry/backoff, ops alert.
- `apps/verifund_control_plane/verifund_control_plane/paypal_tracking.py` — PayPal Tracking adapter (Milestone E).
- `apps/verifund_control_plane/verifund_control_plane/tokens.py` — buyer token, invitation token (purpose `invitation`), and seller token compensating controls.
- `apps/verifund_control_plane/verifund_control_plane/api/buyer.py` — new buyer routes.
- `apps/verifund_control_plane/verifund_control_plane/api/seller.py` — seller routes, scoped reads, declaration endpoints, dispute counter-evidence.
- `apps/verifund_control_plane/verifund_control_plane/api/ops.py` — narrowed release, dispute decision, resolve-system-failure, return-to-remediation, issue-buyer-token, issue-invitation.
- `apps/verifund_control_plane/verifund_control_plane/agreements/routes.py` — gate unauthenticated agreement reads.
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

def test_requirement_and_result_types_construct():
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
    reasons: list[ReviewReason] = Field(default_factory=list)
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
    reasons: list[ReviewReason] = Field(default_factory=list)
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

Replace `EvidenceSummary.required/received/complete` with `requirements: list[RequirementResult]`. Add `requirements` to `VerificationProjection`. Add `requirements: list[Requirement]` to `AwardRequest` with `evidence_required` retained as deprecated mirror. Add `not_as_described` to `RemedyTerms` and `REPAIR_OR_REPLACEMENT` to `RemedyPolicy`. Add `payout` and a `dispute` block to `SellerProjection` if missing (`dispute` carries `status`, `reason_code`, `requirement_ids`, `claim`, `opened_at`, `escalation_rung`; surfaced only in `DISPUTE_OPEN` so the seller can read the buyer's claim and respond). Reasons on `RequirementResult`/`RequirementCheckResult` are `ReviewReason`.

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

Add `evidence_submissions` and `requirement_declarations` tables to `create_schema`. Evidence table gains `requirement_id`, `submission_attempt` (int; the open attempt the submission belongs to, distinct from the declaration's closing `attempt`), `origin`, `attributed_to`, `artifact_type`, `reference`, `agreement_version`, `scan_status`. Keep `UniqueConstraint(transaction_id, sha256)` for blob dedupe.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_repository_aux.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(repo): submission attempts and declarations"
```

### Task 9a: Upload endpoint re-addressed by `requirement_id`

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/evidence.py`
- Modify: `packages/verifund_contracts/verifund_contracts/models.py` (submission receipt)
- Test: `tests/unit/test_verifund_agent_service.py` or new `tests/unit/test_verifund_upload.py`

**Interfaces:**
- Produces: `POST /seller/transactions/{id}/evidence` addressed by `requirement_id`; typed `EvidenceSubmission` receipt `{ submission_id, attempt, evidence_id, requirement_id, receipt_id, artifact_type, scan_status }`.

**Decision (locked 2026-11-04):** legacy `kind` is rejected with `422` naming `requirement_id` — no mirror. `source` mismatch (file vs reference) is also `422`. `required=false` requirements are uploadable.

- [ ] **Step 1: Write failing test**

```python
async def test_upload_addressed_by_requirement_id_returns_receipt():
    response = await client.post(
        f"/seller/transactions/{vf_id}/evidence",
        headers=auth_seller,
        data={"requirement_id": "hardware", "captured_at": "2026-11-04T10:00:00Z"},
        files={"file": ("diag.csv", b"ram_gb,32\n", "text/csv")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["requirement_id"] == "hardware"
    assert body["submission_id"] and body["receipt_id"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_upload.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`kind` is no longer the addressing key. The route requires `requirement_id` and a file **or** a reference artifact (`reference` string + `reference_type=tracking|url`) for `source=reference` requirements; `captured_at` stays accepted and is surfaced on `EvidenceItem`. Validate against the catalog: requirement must exist on the agreement in effect, `owner == "seller"`, `required` when enforcement is on; reject `source=file` + reference-only submissions and vice versa with `422 invalid_request`. Derive `kind` from the requirement (`requirement.kind`). Create the `evidence` blob row (dedupe by `transaction_id, sha256`) **and** an `evidence_submissions` attempt row in one transaction; store `agreement_version` on the evidence row; reject an agreement-version mismatch with `409`. Malware scan stays asynchronous: new items get `scan_status=pending`. Response is the receipt. For a new submission after a declaration, bump `submission_attempt` and reset `declared_at`/`declared_by` on the `RequirementResult` projection. Console back-compat (`kind`) is out of scope — the console is not wired until Milestone D.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_upload.py tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/seller.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/evidence.py packages/verifund_contracts/verifund_contracts/models.py
git commit -m "feat(seller-api): requirement-addressed evidence upload"
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
    assert response.status_code == 200
    items = response.json()["items"]
    assert items  # seller sees rows scoped to its token
    assert all("seller_id" not in item for item in items)  # no party-identity leak
    assert all(item["state"] for item in items)  # enum values, never display strings
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

### Task 10b: Declaration endpoints (declare completion, audit trail)

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Test: `tests/unit/test_verifund_seller_reads.py` or new `tests/unit/test_verifund_declarations.py`

**Interfaces:**
- Produces: `POST /seller/transactions/{id}/requirements/{requirement_id}/declare`, `GET /seller/transactions/{id}/requirements/{requirement_id}/declarations`.

**Decisions (locked 2026-11-04):** declaring with zero open-attempt submissions is rejected with `400`. Declaration after a `FAIL` on the requirement is allowed and starts a new attempt.

- [ ] **Step 1: Write failing test**

```python
async def test_declare_completes_requirement_and_records_attempt():
    await upload_file(transaction_id, "hardware", "diag.csv", b"ram_gb,32\n")
    response = await client.post(
        f"/seller/transactions/{transaction_id}/requirements/hardware/declare",
        headers=auth_seller,
        json={},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["declared_at"] and body["attempt"] == 1
    trail = await client.get(
        f"/seller/transactions/{transaction_id}/requirements/hardware/declarations",
        headers=auth_seller,
    )
    assert [row["attempt"] for row in trail.json()["items"]] == [1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_declarations.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`declare` gathers the currently open-attempt submission ids for `(transaction_id, requirement_id)`, writes a `requirement_declarations` row (`attempt = len(existing) + 1`, `actor=seller:{seller_id}`, `submission_ids`), flips the requirement's `declared_at`/`declared_by` on the projection, and re-runs verification. Verification treats a declared requirement as `PASS` only when every submitted file is valid; otherwise `FAIL` (seller-remediable). An undeclared cumulative requirement stays `NOT_SUBMITTED`/in-progress. A submission after declaration opens a new attempt and resets the declaration. `declarations` returns the audit trail (`attempt`, `declared_at`, `actor`, `submission_ids`), newest first. Reject declaring with zero open-attempt submissions (`400`). Enforce seller ownership and `evidence:write` scope like the other seller routes; `403` cross-seller, `404` unknown transaction.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_declarations.py tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/seller.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(seller-api): requirement declaration endpoints"
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

### Task 12a: Buyer token issuance for the console buyer

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/tokens.py` (if TTL/scope helpers missing)
- Test: `tests/unit/test_agreement_tokens.py`

**Interfaces:**
- Produces: `POST /ops/transactions/{id}/issue-buyer-token` → one-time buyer bearer token (`txn:buy`), bound to `buyer_id` and `transaction_id`.

**Decision (locked 2026-11-04):** ops-triggered only (`POST /ops/transactions/{id}/issue-buyer-token`), mirroring `reissue-seller-token`. Automatic award-time issuance is out of scope; no self-serve or `X-Actor-Id`-authenticated issuance.

- [ ] **Step 1: Write failing test**

```python
async def test_ops_issues_buyer_token_accepted_by_buyer_routes():
    issued = await client.post("/ops/transactions/vf_1/issue-buyer-token", headers=ops_auth)
    token = issued.json()["token"]
    response = await client.post(
        "/buyer/transactions/vf_1/delivery-confirmed",
        headers={"Authorization": f"Bearer {token}"},
        json={"confirmed_at": "2026-11-04T10:00:00Z"},
    )
    assert response.status_code in {200, 201, 422}  # 422 only if bound checks reject the clock value
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Ops-authenticated issuance; token returned once and never logged. Record `buyer_id` on the `buyer_tokens` row. Document the hand-off channel to the buyer console (demo: shown to the ops user). Rate-limit issuance; audit `buyer_token.issued`. Do not reuse the seller token service's agreement-hash claim — buyer tokens carry `transaction_id` + `buyer_id` only.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_agreement_tokens.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/ops.py apps/verifund_control_plane/verifund_control_plane/service.py
git commit -m "feat(auth): ops-issued buyer tokens"
```

### Task 12b: Invitation exchange and agreement-route gating

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tokens.py` (purpose `invitation`)
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (invitation rows or reuse `seller_tokens` with purpose)
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py` or new `api/fulfillment.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/agreements/routes.py` (gate reads)
- Test: `tests/unit/test_agreement_tokens.py` or new `tests/unit/test_invitation_exchange.py`

**Interfaces:**
- Produces: `POST /fulfillment/access/{token}` → exchanges an invitation token for a scoped seller bearer token; `POST /ops/transactions/{id}/issue-invitation` for issuance; gated `GET /agreements` / `GET /agreements/{id}`.

**Decisions (locked 2026-11-04):** ops issues the invitation (never the award path); exchange is single-use (`jti` revoked on exchange); exchange returns `txn:read` + `evidence:write` (no `txn:buy`); agreement routes require a bearer token with ownership checks (seller: own transaction; buyer: own transaction; ops: all); the internal HTML/document route stays out of the public surface; `X-Actor-Id`-style header trust must not authorize these routes.

- [ ] **Step 1: Write failing test**

```python
async def test_invitation_exchange_is_single_use():
    invitation = await client.post("/ops/transactions/vf_1/issue-invitation", headers=ops_auth)
    token = invitation.json()["token"]
    first = await client.post(f"/fulfillment/access/{token}")
    assert first.status_code == 200
    seller_token = first.json()["token"]
    assert seller_token
    second = await client.post(f"/fulfillment/access/{token}")
    assert second.status_code in {401, 409}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_invitation_exchange.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Create an `invitation` purpose in the token service: single transaction, bound `seller_id`, short TTL, single-use enforced by revoking the `jti` on exchange. Exchange validates signature, expiry, revocation, that the bound seller owns the transaction, and returns a standard seller bearer token with the agreed scope set plus an allowed-actions list (`submit_evidence`, `replace_evidence`, `respond_to_dispute` as applicable). Rate-limit exchange; audit `invitation.exchanged`. Gate `GET /agreements` and `GET /agreements/{id}` behind seller/buyer/ops auth per the open decision, and point the workspace's "View agreement" at the seller-scoped `GET /seller/agreements/{id}` instead. The unauthenticated agreement HTML/document route stays internal-only.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_invitation_exchange.py tests/unit/test_agreement_generator.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tokens.py apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/api/fulfillment.py apps/verifund_control_plane/verifund_control_plane/agreements/routes.py
git commit -m "feat(access): invitation exchange and gated agreement reads"
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

Define the `CarrierClient` protocol and a fake/in-memory implementation with retry/backoff and an ops alert on outage; a carrier outage leaves the delivery requirement `REVIEW` with a retry scheduled, never a permanent block and never `FAIL`. Real aggregator adapters (EasyPost/Shippo/PayPal Tracking) land behind the same protocol in Milestone E — do not implement PayPal Tracking in this task.

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
async def test_refund_moves_to_refunded():
    await service.refund("vf_1", remedy="refund")
    assert transaction.state == "REFUNDED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_fake_payments.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

PayPal refund call, ledger reversal (double-entry against the capture), idempotency keyed on transaction + remedy, refund webhook handling, terminal `REFUNDED`. This task delivers the path itself, tested directly via `service.refund(...)`; Task 19 wires it from the `dispute-decision` flow (`upheld` + refund remedy). Until this ships, captured-fund cancellation stays forbidden.

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

### Task 18a: Seller dispute counter-evidence and claim read

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/seller.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/evidence.py` (`purpose` column)
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (`purpose` on `evidence`, default `requirement`)
- Test: `tests/unit/test_verifund_agent_service.py` or new `tests/unit/test_dispute_counter_evidence.py`

**Interfaces:**
- Produces: `POST /seller/transactions/{id}/dispute-evidence` (dispute-scoped, seller token); seller projection exposes the buyer claim in `DISPUTE_OPEN` (from Task 1's `dispute` block).

**Decision (locked 2026-11-04):** dispute artifacts reuse `evidence` with `purpose='dispute'` (ignored by verification and rollup); no separate table.

- [ ] **Step 1: Write failing test**

```python
async def test_dispute_counter_evidence_never_satisfies_requirement():
    await open_valid_dispute(transaction_id)  # helper from Task 18
    response = await client.post(
        f"/seller/transactions/{transaction_id}/dispute-evidence",
        headers=auth_seller,
        data={"requirement_id": "hardware"},
        files={"file": ("counter.png", b"\x89PNG...", "image/png")},
    )
    assert response.status_code == 201
    result = await service.verify(transaction_id)
    hardware = next(r for r in result.requirements if r.requirement_id == "hardware")
    assert hardware.attempt is not None  # unchanged by dispute artifact
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_dispute_counter_evidence.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`purpose` defaults to `requirement`; dispute submissions carry `purpose='dispute'` plus the open dispute id; intake rules (allowlist, size, SHA-256, transaction + agreement-version binding) are identical to requirement uploads. The endpoint is permitted only while `DISPUTE_OPEN`, is never read by verification or rollup, and never starts/closes a requirement attempt. The seller projection gains the `dispute` block (claim, `reason_code`, `requirement_ids`, `opened_at`, `escalation_rung`, `action_required='respond_to_dispute'`) so the workspace can render what is expected next. Add `respond_to_dispute` to `next_action` derivation.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_dispute_counter_evidence.py tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/seller.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/evidence.py apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(dispute): seller counter-evidence surface"
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

### Task 19a: Narrow ops release, non-overridable reasons, return-to-remediation

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/domain.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Test: `tests/unit/test_verifund_agent_service.py` or new `tests/unit/test_ops_narrowing.py`

**Interfaces:**
- Produces: `release()` accepting `RELEASE_PERMITTED` and `REVIEW_REQUIRED` only (409 while a dispute is open); `return-to-remediation` endpoint; expanded `NON_OVERRIDABLE_REASONS`.

- [ ] **Step 1: Write failing tests**

```python
def test_release_refused_during_open_dispute():
    seed_transaction_in("RELEASE_PERMITTED", dispute_status="open")
    with pytest.raises(VerifundError) as exc:
        await service.release("vf_1", reason="manual_flag", actor="ops")
    assert exc.value.code == "conflict"

def test_non_verification_failure_not_overridable():
    assert ReviewReason.FUNDING_MISMATCH in NON_OVERRIDABLE_REASONS
    assert ReviewReason.INVALID_EVIDENCE_HASH in NON_OVERRIDABLE_REASONS
    assert ReviewReason.MANUAL_FLAG not in NON_OVERRIDABLE_REASONS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_ops_narrowing.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`NON_OVERRIDABLE_REASONS` expands to every verification failure reason except `MANUAL_FLAG` (inspection-window overshoot and future-delivery reasons remain overridable only via `extend_deadline`, never via `release`). `release()` rejects any source state other than `RELEASE_PERMITTED`/`REVIEW_REQUIRED` and refuses unconditionally during an open dispute. `extend_deadline` is the only way to move an evidence deadline. `POST /ops/transactions/{id}/return-to-remediation` moves `REVIEW_REQUIRED → REMEDIATION_REQUIRED` with a mandatory note and re-arms the remediation deadline (default 72h), replacing the removed "override a missed deadline" capability. Audit `ops.returned_to_remediation`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_ops_narrowing.py tests/unit/test_verifund_agent_service.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/domain.py apps/verifund_control_plane/verifund_control_plane/api/ops.py
git commit -m "feat(ops): narrow release and non-overridable reasons"
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

### Task 20a: PENDING_SCAN settlement and re-verification trigger

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/domain.py` (new `ReviewReason` member)
- Test: `tests/unit/test_verifund_reconciler.py`

**Interfaces:**
- Produces: reconciler sweep that settles `scan_status=pending` (calls the scan provider; marks `clean` or `rejected`) and re-runs verification for affected transactions; pending items older than `settings.scan_pending_timeout_minutes` (default 60) route the transaction to `REVIEW_REQUIRED` with `PENDING_SCAN_TIMEOUT`.

- [ ] **Step 1: Write failing test**

```python
async def test_pending_scan_timeout_routes_to_review():
    seed_evidence_item(scan_status="pending", created_at=now - timedelta(minutes=120))
    await reconciler.run_once()
    assert transaction.state == "REVIEW_REQUIRED"

async def test_scan_completion_triggers_reverification():
    seed_evidence_item(scan_status="pending")
    await reconciler.run_once()   # provider marks clean (fake)
    assert transaction.verification is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

The reconciler already owns deadline sweeps; extend it with a scan-settlement sweep. A `rejected` scan result counts as an invalid file at declaration time (seller-remediable `FAIL`, never `REVIEW` and never AI-derived). A `clean` result flips `scan_status`, then verification is re-run; AI-derived `FAIL` still forbidden, so a clean scan whose extraction looks wrong produces `REVIEW`. Scan provider is behind a `ScannerPort` protocol (fake in tests; real provider selected via settings). If the provider is unavailable, leave items `pending` and alert ops — do not fail the requirement.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/domain.py
git commit -m "feat(verification): scan settlement and re-verification sweep"
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

### Task 22a: Seller token compensating controls

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/tokens.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (if revocation listing helpers missing)
- Modify: `apps/verifund_control_plane/verifund_control_plane/settings.py` (`seller_token_ttl_minutes`, `seller_rate_limit_per_minute`)
- Test: `tests/unit/test_agreement_tokens.py` or new `tests/unit/test_seller_token_controls.py`

**Interfaces:**
- Produces: short-TTL enforcement, per-seller rate limiting, remediation-triggered token rotation, log-redaction guarantee.

- [ ] **Step 1: Write failing tests**

```python
async def test_rate_limit_blocks_burst():
    for _ in range(settings.seller_rate_limit_per_minute + 1):
        response = await client.get("/seller/transactions", headers=auth_seller)
    assert response.status_code == 429

def test_bearer_not_logged(caplog):
    with caplog.at_level("INFO"):
        await client.get("/seller/transactions", headers=auth_seller)
    assert "Bearer " not in caplog.text

def test_remediation_rotation_revokes_old_token():
    old_jti = seller_token.jti
    await transition_to("REMEDIATION_REQUIRED")
    assert await repo.is_token_revoked(old_jti)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_seller_token_controls.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Short TTL for seller tokens via `settings.seller_token_ttl_minutes` (default 60 for demo; revocation already supported). Per-seller fixed-window rate limiter on seller routes (429 + `rate_limited` code). On any transition into `REMEDIATION_REQUIRED`, revoke the transaction's active seller tokens and reissue via the Task 22 path (rotation on remediation) so a token captured before remediation is useless. Verify the request logger redacts `Authorization` values (add a redaction filter if missing). Upload/claim notifications remain out of scope — no notification channel exists yet; note in the demo runbook instead. No buyer-token changes here.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_seller_token_controls.py tests/unit/test_agreement_tokens.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/tokens.py apps/verifund_control_plane/verifund_control_plane/repository.py apps/verifund_control_plane/verifund_control_plane/settings.py
git commit -m "feat(security): seller token compensating controls"
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
- Consumes: `POST /fulfillment/access/{token}` (produced by **Task 12b**).

- [ ] **Step 1: Implement**

Wire invitation exchange (produced by Task 12b): the access screen makes the server call and stores the returned seller token as Bearer; "Continue to demo workspace" is not the production flow. Gate the agreement routes is a backend concern (Task 12b) — this task only consumes the seller-scoped `GET /seller/agreements/{id}` for the "View agreement" action and the agreement summary card.

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

### Task 28: PayPal tracker sync (outbound, post-capture)

**Files:**
- Create: `apps/verifund_control_plane/verifund_control_plane/paypal_tracking.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py` (sync trigger on accepted shipping reference)
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py` (persist `tracker_id`)
- Test: `tests/unit/test_verifund_paypal_tracking.py`

**Interfaces:**
- Produces: `PayPalTrackingClient.sync(*, transaction_id, capture_id, tracking_number, carrier, items) -> tracker_id`.

Outbound only (locked 2026-11-04) — no `PASS`/`FAIL`, no webhook handling, no Tracking v1, no verification/rollup reads. Carrier is validated against PayPal's carrier enum with `OTHER` + `carrier_name_other` fallback (sandbox: `OTHER` / `Verifund Sandbox Carrier` per `verifund-test-laptop-evidence/paypal-tracking-evidence.json`). Delivery evidence stays exclusively with the `CarrierClient` adapter.

- [ ] **Step 1: Write failing test**

```python
async def test_tracker_sync_is_idempotent():
    client = FakePayPalTracking()
    kwargs = dict(transaction_id="vf_1", capture_id="8MC585209K746392H",
                  tracking_number="TEST-TRACK-001", carrier="OTHER",
                  carrier_name_other="Verifund Sandbox Carrier", items=[{"sku": "sku01", "quantity": "1"}])
    first = await client.sync(**kwargs)
    second = await client.sync(**kwargs)
    assert first == second == "8MC585209K746392H-TEST-TRACK-001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_paypal_tracking.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

OAuth client-credentials token handling; Orders v2 `POST /v2/checkout/orders/{id}/track` with `capture_id`, `tracking_number`, `carrier`, `items[]` derived from award line items, `notify_payer=true`, `invoice_id=agreement_id`. One call per parcel. Tracker id `{capture_id}-{tracking_number}` persisted on the transaction record. Sync is triggered from the shipping-reference acceptance path (post-capture), entirely outside verification/rollup. Retry/backoff with an ops alert on persistent failure; `paypal.tracker_registered` audit event; tokens never logged. PayPal's documented API exports no carrier scans or delivered webhook — do not build one.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_paypal_tracking.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/paypal_tracking.py apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/repository.py
git commit -m "feat(paypal): outbound tracker sync on ship"
```

### Task 29: PayPal tracker visibility for ops and disputes

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py` (ops/dispute context)
- Modify: `apps/verifund_control_plane/verifund_control_plane/reconciler.py` (display refresh)
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/ops.py`
- Test: `tests/unit/test_verifund_reconciler.py`

**Interfaces:**
- Produces: tracker block `{ tracker_id, last_status, status_source: "merchant_push", updated_at }` in the ops transaction view and `dispute-decision` context.

Read-only display over the outbound sync of Task 28. Tracker data never enters verification, rollup, `REMEDIATION_REQUIRED` routing, or the release gate.

- [ ] **Step 1: Write failing test**

```python
async def test_dispute_context_includes_tracker():
    seed_transaction_with_tracker()
    context = await service.dispute_decision_context("vf_1")
    assert context["tracker"]["tracker_id"] == "8MC585209K746392H-TEST-TRACK-001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Refresh the persisted tracker id with `GET /v1/shipping/trackers/{transaction_id}-{tracking_number}` (the documented read-back for what was last registered); surface it in the ops transaction view and in the `dispute-decision` payload, where `non_delivery`/`late_delivery` reason codes benefit most (item-not-received defense). Statuses are merchant-pushed values (`SHIPPED | ON_HOLD | DELIVERED | CANCELLED`) and are always rendered with a `merchant_push` source label. Reconciler refreshes opportunistically; refresh failure is non-fatal. No path from tracker state to verification or `DISPUTE_OPEN` outcomes; ops still decides disputes.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_verifund_reconciler.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/service.py apps/verifund_control_plane/verifund_control_plane/reconciler.py apps/verifund_control_plane/verifund_control_plane/api/ops.py
git commit -m "feat(ops): surface PayPal tracker in dispute context"
```

---

## Self-Review

1. **Spec coverage:** Every Round 4 decision maps to a task — 28/29 → Tasks 16–19 and 19a; 30 → Tasks 1–2; 31 → Tasks 11, 12, 12a; 32 → Tasks 13, 14, 19, 19a, 20; 33 → Tasks 9, 10b; 34 → Tasks 1, 8. Earlier decisions map to Tasks 3–8, 13, 15, 16, 21. Spec §5 API surface: seller-scoped reads/events/agreement read → Tasks 10, 10a; `declare`/`declarations` → Task 10b; upload re-addressing → Task 9a; dispute counter-evidence → Task 18a; invitation exchange + agreement gating → Task 12b; buyer token issuance → Task 12a; ops release narrowing, non-overridable reasons, `return-to-remediation` → Task 19a; reissue on version bump → Task 22; `extend-deadline` → Task 20; scan settlement + re-verification → Task 20a; compensating controls → Task 22a.
2. **Placeholder scan:** Each task includes test code, implementation notes, and commands.
3. **Type consistency:** `RequirementResult` field names are consistent across tasks; `captured_at` and `scan_status` added once; `submission_attempt` added once on `evidence` (Task 9) and reused by declarations; `ReviewReason`-typed reasons throughout.
4. **Resolved (grill 2026-11-04, spec §2 Round 5):** PayPal Tracking is outbound-only (Tasks 28–29 rewritten; no webhook/polling assumption; tracker data never gates release); legacy `kind` rejected; zero-submission declarations rejected (`400`); buyer tokens ops-issued; invitations ops-issued, single-use, `txn:read`+`evidence:write`, bearer-gated agreement routes; dispute counter-evidence stored as `evidence.purpose='dispute'`; execution locked to subagent-driven; `serial` requirement_id fixed in spec §3.9.2.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-04-verifund-seller-evidence-target-implementation.md`.

**Locked 2026-11-04 (spec §2 Round 5, decision 41):** subagent-driven execution. Dispatch a fresh subagent per task using `superpowers:subagent-driven-development`, review between tasks, fix before proceeding. Inline execution is not used.
