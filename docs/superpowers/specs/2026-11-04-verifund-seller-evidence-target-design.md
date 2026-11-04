# Verifund Seller Evidence — Target Design

Date: 2026-11-04
Status: Design (decisions locked via grill session)
Related specs:
- `docs/superpowers/specs/verifund-seller-evidence-recommendation.md` (requirement-driven evidence)
- `docs/superpowers/specs/verifund-seller-fulfillment-workspace-recommendation.md` (workspace UI, now filled)
Related code: `apps/verifund_control_plane`, `apps/seller_agent`, `apps/buyer_agent`,
`packages/verifund_contracts`, `apps/console/features/chat/verifund-tools.tsx`,
`verifund-seller-fulfillment/` (mock).

## 1. Purpose

Define how a Verifund seller submits evidence, how that evidence is verified and approved,
and how the money moves — replacing the current transaction-level, seller-self-certified
flow with a requirement-driven, per-requirement flow anchored on buyer confirmation and
carrier corroboration.

No code changes are made by this document. It is the design target for implementation.

## 2. Decisions locked

### Round 1 — core model

| # | Question | Decision |
|---|---|---|
| 1 | Delivery trust anchor | Buyer confirms receipt |
| 2 | Agreement vs policy | Agreement wins |
| 3 | Buyer silence | Deemed acceptance only if all requirements PASS |
| 4 | Overrides | Objective failures only |
| 5 | Remediation | New `REMEDIATION_REQUIRED` state |
| 6 | Granularity | Per-requirement with derived rollup |
| 7 | External checks | Carrier only |
| 8 | AI authority | Extraction + `REVIEW` only |
| 9 | Workspace access | Bearer token is enough (demo) |
| 10 | Evidence storage | Private object store + lifecycle |

### Round 2 — contradictions resolved

| # | Question | Decision |
|---|---|---|
| 11 | Buyer identity | Console login (human buyer) |
| 12 | Delivery precedence | Both must agree (carrier + buyer) |
| 13 | Delivery evidence source | System-generated from buyer confirmation |
| 14 | Acceptance clock | `max(inspection, dispute)` |
| 15 | Agreement floors | Keep hard floors at creation |
| 16 | Existing transactions | Grandfathered |
| 17 | Review vs remediation | `REVIEW` wins |
| 18 | Override scope (final) | Only `manual_flag` |
| 19 | Evidence submissions | Immutable attempts, latest wins |
| 20 | Buyer dispute path | Authenticated `DISPUTE` action |
| 21 | Invoice semantics | Deterministic field compare can `FAIL` |
| 22 | Carrier integration | Aggregator API |
| 23 | Workspace contract | Mock is normative |

## 3. Target architecture

### 3.1 Requirement catalog comes from the stored agreement

Current state: required set is hardcoded in `domain.py:84` (`REQUIRED_EVIDENCE`) and
`policy.py:65` (`{"shipment_manifest", "delivery_confirmation"}`); `seller_projection`
uses the same constant (`service.py:951-954`); policy uses `settings.inspection_window_hours`
(`service.py:1011`, default 24h) instead of the agreement's 48h (`settlement_flow.py:113`).

Target:

- `evaluate()` (`policy.py:49`) takes the stored `AgreementVersion` terms.
- `evidence_required` defines the requirement list; each entry becomes a `RequirementResult`.
- `inspection.period_hours` and `inspection.starts_on` drive the acceptance clock.
- `settings.inspection_window_hours` becomes a fallback only for legacy agreements.
- `REQUIRED_EVIDENCE` is removed; `verify_if_ready` (`service.py:963-971`) checks
  completeness against the agreement list.
- Floors enforced at creation (already partly in `terms.py:56-63`: `period_hours >= 1`,
  `delivery_confirmation` present, non-empty evidence). Agreement wins on values, not structure.
- Grandfathering: agreements created before the change keep settings-based evaluation;
  store a `policy_version` on the agreement record.

### 3.2 Per-requirement results

New contract in `packages/verifund_contracts/verifund_contracts/models.py`:

```text
RequirementResult
  requirement_id: str
  kind: EvidenceKind
  status: NOT_SUBMITTED | PENDING_SCAN | PASS | FAIL | REVIEW
  evidence_id: str | None
  reasons: list[ReviewReason]
  checked_at: datetime | None
  remediation: { attempt, deadline, note } | None

EvidenceSummary
  requirements: list[RequirementResult]   # replaces required/received/complete
  deadline: datetime | None
  items: list[EvidenceItem]
```

Rollup:

- any `REVIEW` → transaction `REVIEW_REQUIRED`
- else any `FAIL` → `REMEDIATION_REQUIRED`
- else all `PASS` → `RELEASE_PERMITTED` (subject to acceptance clock)
- `NOT_SUBMITTED` before deadline → stay pending
- `NOT_SUBMITTED` at/after deadline → `REMEDIATION_REQUIRED` with `EVIDENCE_DEADLINE_MISSED`

`VerificationProjection` gains `requirements: list[RequirementResult]`.

### 3.3 Delivery is buyer-attested, carrier-corroborated

1. Seller submits `shipment_manifest` and `invoice` (and any other seller-owned requirement).
2. Carrier record is fetched via aggregator (EasyPost/Shippo) against the PO tracking number.
3. Buyer calls `CONFIRM_DELIVERY` with `confirmed_at`.
4. `delivered_at = buyer confirmed_at`; inspection clock starts.
5. Control plane creates a **system-generated, buyer-attributed** `delivery_confirmation`
   evidence record linked to the buyer confirmation and carrier record.
6. Carrier and buyer must agree. Carrier says delivered + buyer confirms → `PASS`.
   Either side disagrees or is missing → `REVIEW`.

Seller no longer self-certifies delivery (`seller_agent/settlement.py:57` must be removed).

### 3.4 Verification authority

- Deterministic checks produce `PASS`/`FAIL`: hash, media type, manifest seller/agreement/tracking,
  invoice arithmetic, delivery timestamp, requirement presence.
- AI produces extraction plus `REVIEW` only; never `PASS`.
- Invoice semantic mismatches (total, currency, seller, line items) produce `FAIL`;
  extraction-only fields produce `REVIEW`.
- `NON_OVERRIDABLE_REASONS` (`domain.py:79-83`) expands to all verification failures
  except `MANUAL_FLAG`.
- `extend_deadline` replaces overriding a missed deadline.

### 3.5 Remediation loop

New state `REMEDIATION_REQUIRED`:

```text
VERIFICATION_PENDING → REMEDIATION_REQUIRED     (objective FAIL)
REMEDIATION_REQUIRED → VERIFICATION_PENDING      (new submission)
REMEDIATION_REQUIRED → REVIEW_REQUIRED           (deadline missed / repeated failure)
REMEDIATION_REQUIRED → CANCELED                  (buyer or seller cancels)
```

- Add to `EVIDENCE_UPLOAD_STATES` (`domain.py:85-89`), `STAGE_BY_STATE`, `ALLOWED_TRANSITIONS`.
- `verify()` early-return (`service.py:975-981`) must not block re-verification after resubmission.
- Remediation has its own deadline, separate from `deadlines.evidence` (set at PO report,
  `service.py:1863-1865`).
- `by_kind.setdefault` (`policy.py:61`) becomes "latest submission by `created_at`".
- Duplicate SHA (`repository.py:145`) stays for blob dedupe, but a new submission row is
  created per attempt; blobs are shared.

`REVIEW_REQUIRED` becomes reversible: add transitions back to `REMEDIATION_REQUIRED` and
`VERIFICATION_PENDING` so ops can return a transaction to the seller after resolving review.

### 3.6 Acceptance and release

Buyer actions:

- `CONFIRM_DELIVERY` — starts inspection; not acceptance
- `ACCEPT` — early acceptance, releases immediately
- `DISPUTE` — blocks release, moves to `REVIEW_REQUIRED`

Deemed acceptance:

- At `delivered_at + max(inspection, dispute)`, if all requirements are `PASS` and no
  dispute exists → system release as `system:deemed_acceptance`.
- If any requirement is not `PASS`, deemed acceptance does not fire.
- Reconciler (`reconciler.py:147-156`) must actually release on this path; today it only
  counts stale `RELEASE_PERMITTED` (`reconciler.py:158-166`).

### 3.7 Access and storage

- Seller token stays bearer-only for the demo, with compensating controls: short TTL, scope
  check, revocation, rate limiting, no `Authorization` logging, rotation on remediation,
  upload notifications.
- Buyer confirmation requires a separate buyer credential (console login recommended).
- Evidence moves to a private object store with SSE, malware scanning, retention/legal hold,
  short-lived signed URLs. Keep SHA-256 content addressing; separate blob from submission record.

## 4. State machine (final)

```text
AWARDED → AGREED → FUNDING_PENDING → FUNDED → FULFILLMENT_PENDING
  → VERIFICATION_PENDING → (REMEDIATION_REQUIRED ↔ VERIFICATION_PENDING)
  → RELEASE_PERMITTED → PAYOUT_PENDING → RELEASED
  → REVIEW_REQUIRED (any REVIEW; reversible to REMEDIATION/VERIFICATION)
```

Seller `upload_evidence` allowed in: `FUNDED`, `FULFILLMENT_PENDING`, `VERIFICATION_PENDING`,
`REMEDIATION_REQUIRED`.

## 5. API surface

Seller (existing, shape unchanged, projection enriched):

- `GET /seller/transactions/{id}` — projection now includes `requirements[]`
- `POST /seller/transactions/{id}/evidence` — `kind` validated against agreement
  requirements; returns submission attempt

Buyer (new):

- `POST /buyer/transactions/{id}/delivery-confirmed` — `{ confirmed_at, condition?, photos? }`
- `POST /buyer/transactions/{id}/accept`
- `POST /buyer/transactions/{id}/dispute` — `{ reason, evidence? }`

Ops (existing, narrowed):

- `POST /ops/transactions/{id}/release` — override only for `manual_flag`
- `POST /ops/transactions/{id}/extend-deadline`
- `POST /ops/transactions/{id}/return-to-remediation`

## 6. Data model changes

Contracts (`models.py`):

- Add `RequirementResult`, `RequirementStatus`.
- Replace `EvidenceSummary.required/received/complete` with `requirements: list[RequirementResult]`.
- `VerificationProjection` adds `requirements`.
- `AwardRequest`/terms already support `inspection_period_hours`, `evidence_required`,
  `dispute_window_hours` — no change.
- Add `policy_version` to agreement and transaction.

DB (`repository.py`):

- `evidence` table: add `requirement_id`, `submission_attempt`, `source`
  (`seller|buyer|carrier|system`), `scan_status`.
- New `evidence_submissions` table (or attempt column on `evidence`) for "latest wins".
- `transactions` table: add `policy_version`, `acceptance` JSON block
  (status, deadline, decided_by, decided_at).
- `UniqueConstraint("transaction_id", "sha256")` stays for blob dedupe.

Projections (`service.py`):

- `_projection` and `seller_projection` populate `requirements[]`.
- Console release card (`verifund-tools.tsx:325-397`) reads per-requirement statuses
  instead of a single `override_allowed`.

## 7. Implementation sequence

1. Contracts — `RequirementResult`, `RequirementStatus`, updated summaries/projections,
   `policy_version`. Tests for serialization.
2. State machine — add `REMEDIATION_REQUIRED`, transitions, upload permissions,
   `STAGE_BY_STATE`, `policy_version` on agreement.
3. Agreement as catalog — `evaluate()` takes terms; remove hardcoded sets; grandfathering;
   floors at creation (already partly there).
4. Per-requirement verification — rewrite `evaluate()` to return `list[RequirementResult]`
   plus rollup; fix `by_kind` to latest submission; deterministic checks per kind.
5. Buyer actions — `CONFIRM_DELIVERY`, `ACCEPT`, `DISPUTE` endpoints and transitions;
   system-generated `delivery_confirmation`.
6. Carrier integration — aggregator client, tracking → transaction mapping, webhook/polling,
   scan-status gating.
7. Remediation + storage — submission attempts, object store adapter, scanning, signed URLs,
   compensating token controls.
8. Acceptance clock + reconciler — deemed acceptance release path; `max(inspection, dispute)`;
   `extend_deadline`.
9. AI boundary — extraction-only interface; AI never emits `PASS`.
10. Console + mock — per-requirement UI; expand allowlist to match mock; add
    `REMEDIATION_REQUIRED` status.

## 8. Remaining risks / assumptions

- Carrier aggregator is a new external dependency with its own outage/retry semantics;
  scan-status gating makes evidence verification asynchronous.
- Grandfathering means two code paths (settings-based vs terms-based) must coexist until
  old transactions terminalize.
- Buyer confirmation as the anchor means a buyer who never confirms stalls the transaction
  indefinitely; consider an ops escalation after `delivery_days + N`.
- Bearer-only seller access remains the weakest link even with compensating controls; the
  buyer action surface makes this more acute.
- AI extraction quality determines ops load; if extraction is unreliable, invoices always
  go to `REVIEW`.

## 9. Source references

- `apps/verifund_control_plane/verifund_control_plane/domain.py:79-89` — non-overridable reasons, required evidence, upload states
- `apps/verifund_control_plane/verifund_control_plane/policy.py:49-144` — evaluate, setdefault, hardcoded required
- `apps/verifund_control_plane/verifund_control_plane/service.py:816-906` — add_evidence
- `apps/verifund_control_plane/verifund_control_plane/service.py:907-962` — seller_projection
- `apps/verifund_control_plane/verifund_control_plane/service.py:963-1080` — verify
- `apps/verifund_control_plane/verifund_control_plane/service.py:2085-2206` — release
- `apps/verifund_control_plane/verifund_control_plane/repository.py:131-146` — evidence table
- `apps/verifund_control_plane/verifund_control_plane/reconciler.py:147-166` — sweeps
- `apps/verifund_control_plane/verifund_control_plane/api/seller.py:18-43` — bearer auth
- `apps/seller_agent/seller_agent/settlement.py:25-60` — self-certified delivery
- `apps/buyer_agent/buyer_agent/settlement_flow.py:113-120` — 48h inspection, evidence_required
- `packages/verifund_contracts/verifund_contracts/models.py:96-108,744-767` — ReviewReason, evidence contracts
- `packages/verifund_contracts/verifund_contracts/terms.py:56-63` — validation floors
- `apps/console/features/chat/verifund-tools.tsx:325-397` — release gate
- `verifund-seller-fulfillment/src/lib/data.ts` — mock workspace spec
