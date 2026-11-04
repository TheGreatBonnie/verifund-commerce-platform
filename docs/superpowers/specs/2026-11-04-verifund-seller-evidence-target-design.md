# Verifund Seller Evidence — Target Design

Date: 2026-11-04
Status: Design (decisions locked via grill sessions; round 3 recorded 2026-11-04)
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

### Round 3 — requirement catalog and dispute (2026-11-04)

| # | Question | Decision |
|---|---|---|
| 24 | Requirement catalog shape | Requirement objects in agreement terms |
| 25 | Catalog author | Buyer agent authors, floors enforced |
| 26 | Buyer dispute standard | Evidence-gated dispute |
| 27 | Undecided valid dispute | Hold and escalate, no auto-outcome |

Decision 24 supersedes the part of §3.1 that treated `evidence_required` as the
requirement list. Decision 27 re-opens an unbounded hold that §3.6's acceptance clock
otherwise closes; see §3.8 and §8.

## 3. Target architecture

### 3.1 Requirement catalog comes from the stored agreement

Current state: required set is hardcoded in `domain.py:84` (`REQUIRED_EVIDENCE`) and
`policy.py:65` (`{"shipment_manifest", "delivery_confirmation"}`); `seller_projection`
uses the same constant (`service.py:951-954`); policy uses `settings.inspection_window_hours`
(`service.py:1011`, default 24h) instead of the agreement's 48h (`settlement_flow.py:113`).

Target:

- `evaluate()` (`policy.py:49`) takes the stored `AgreementVersion` terms.
- `terms.requirements[]` defines the requirement list; each entry becomes a
  `RequirementResult` (§3.1.1). `evidence_required` is no longer the catalog.
- `inspection.period_hours` and `inspection.starts_on` drive the acceptance clock.
- `settings.inspection_window_hours` becomes a fallback only for legacy agreements.
- `REQUIRED_EVIDENCE` is removed; `verify_if_ready` (`service.py:963-971`) checks
  completeness against the agreement list.
- Floors enforced at creation (already partly in `terms.py:56-63`: `period_hours >= 1`,
  `delivery_confirmation` present, non-empty evidence). Agreement wins on values, not structure.
- Grandfathering: agreements created before the change keep settings-based evaluation;
  store a `policy_version` on the agreement record.

### 3.1.1 Requirement catalog (decisions 24, 25)

`terms.requirements[]` is the only source of the seller checklist and of verification.
`EvidenceKind` is demoted to the file class inside a requirement; it is no longer the
catalog.

```text
Requirement                        # in agreement terms, versioned with the agreement
  requirement_id: str              # stable across versions of the same agreement
  description: str
  owner: seller | system | buyer   # who must satisfy it / who may submit
  kind: EvidenceKind
  source: file | reference         # reference = tracking number, PR, deployment URL
  accepted_formats: list[str]      # required when source=file; empty when reference
  expected_value: str | int | None
  operator: eq | gte | lte | contains | exists
  unit: str | None
  required: bool
  verification_method: str         # deterministic check id, or "extraction"
```

Rules:

- **Buyer agent authors** the list into `AwardRequest.requirements[]`;
  `agreements/generator.py` copies it into `terms.requirements[]` (replacing the
  `evidence_required` copy at `generator.py:83`).
- **Seller agent validates** every requirement against its mandate before accepting the
  agreement, in the same place it already checks terms.
- **Floors enforced at creation** (`terms.py:56-63`): non-empty list; unique
  `requirement_id`; `expected_value` present whenever `operator` is not `exists`;
  `accepted_formats` non-empty when `source == file`; `owner` present on every entry;
  exactly one system-owned delivery requirement, still `delivery_confirmation`
  (`terms.py:60`), because the acceptance clock keys off it.
- **Ownership drives the workspace**: `owner=seller` renders an upload card,
  `owner=system` renders a status-only row, `owner=buyer` never appears in the seller
  workspace. This is what removes the contradiction between "mock is normative"
  (decision 23) and "the agreement defines the checklist".
- **Stable identity across versions**: evidence is filed against `requirement_id`, so an
  agreement version bump re-attaches existing submissions by id instead of stranding them
  behind the `agreement_hash` freshness check (`api/seller.py:36-41`).

Migration: grandfathered agreements (`policy_version` 1) are projected into the catalog at
read time as two entries — `shipment_manifest` (`owner=seller`) and `delivery_confirmation`
(`owner=system`) — so `REQUIRED_EVIDENCE` (`domain.py:84`) can be deleted without breaking
them.

### 3.2 Per-requirement results

New contract in `packages/verifund_contracts/verifund_contracts/models.py`:

```text
RequirementResult
  requirement_id: str
  kind: EvidenceKind
  owner: seller | system | buyer
  source: file | reference
  status: NOT_SUBMITTED | PENDING_SCAN | PASS | FAIL | REVIEW
  evidence_id: str | None
  attempt: int | None              # latest submission attempt considered
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
- a `FAIL` on an `owner=system` requirement is not seller-remediable and routes to
  `REVIEW_REQUIRED`, not `REMEDIATION_REQUIRED`

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

The delivery requirement is `owner=system` (§3.1.1), so it appears in the seller workspace
as a status row, never as an upload card. The seller submits `shipment_manifest` and
`invoice`, not delivery. Seller no longer self-certifies delivery
(`seller_agent/settlement.py:47-55` must be removed).

### 3.4 Verification authority

- Deterministic checks produce `PASS`/`FAIL`: hash, media type, manifest seller/agreement/tracking,
  invoice arithmetic, delivery timestamp, requirement presence.
- AI produces extraction plus `REVIEW` only; never `PASS`.
- Invoice semantic mismatches (total, currency, seller, line items) produce `FAIL`;
  extraction-only fields produce `REVIEW`.
- `NON_OVERRIDABLE_REASONS` (`domain.py:79-83`) expands to all verification failures
  except `MANUAL_FLAG`.
- `extend_deadline` replaces overriding a missed deadline.
- The same deterministic comparators re-analyse buyer evidence in a dispute (§3.8);
  there is no second adjudication engine.

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
- `DISPUTE` — evidence-gated (§3.8); a valid dispute moves to `DISPUTE_OPEN`, an invalid
  one is an audit event with no transition

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

### 3.8 Dispute (decisions 26, 27)

A dispute is **evidence-gated**. Validity is an intake standard, never a truth standard:
"well-formed and on-topic", not "proven".

On `POST /buyer/transactions/{id}/dispute`:

1. The request names one or more `requirement_id`s, a `reason_code`, and a specific claim
   (observed value or condition).
2. At least one artifact is attached and passes normal intake — media allowlist, size
   limit, SHA-256, bound to the transaction and current agreement version
   (`evidence.py:36-80`).
3. The claim must be evaluable: it must name a requirement and state what was observed.

| Case | Result |
|---|---|
| No artifact, or intake fails | `dispute.rejected` audit event with a reason code. **No transition**, inspection clock untouched, one re-submission allowed inside `dispute_window_hours` |
| Valid artifacts against catalog requirements | `DISPUTE_OPEN` |
| Duplicate, or the dispute window has closed | `409 conflict` |

`DISPUTE_OPEN`:

- Blocks release, blocks deemed acceptance, blocks `PAYOUT_PENDING`.
- The seller can submit counter-evidence scoped to the dispute (a dispute submission, not
  a requirement submission) and can read the buyer's claim.
- The seller workspace shows days open, the current escalation rung, and what is expected
  next — `DISPUTE_OPEN` must not be presented as a generic review.

Adjudication:

- Buyer evidence is re-analysed by the deterministic comparators from §3.4
  (battery health 78 vs agreed `>= 90` → objective `FAIL`, no human needed).
- Non-deterministic claims need a reviewer. AI never resolves a dispute.
- `POST /ops/transactions/{id}/dispute-decision` records `upheld | dismissed | settled`,
  the remedy, and the reviewer. `dismissed` returns the transaction to
  `RELEASE_PERMITTED`/`VERIFICATION_PENDING`; `upheld` applies `terms.remedies` and moves
  to `CANCELED` (refund) or `REMEDIATION_REQUIRED` (repair/replacement).

**Hold and escalate, no auto-outcome (decision 27).** A valid dispute keeps funds held until
a human decides. There is deliberately no timeout release and no timeout refund. The
accepted consequence is that without the ladder below, this is an unbounded hold with no
seller recourse — and `REVIEW_REQUIRED` currently grants the seller no actions at all
(`domain.py:265-267`). `DISPUTE_OPEN` therefore carries obligations that must ship with it:

1. Escalation rungs with dates: alert at open, at `dispute_window_hours`, and at the cap.
2. A seller response surface — otherwise the hold is one-sided.
3. A **forced outcome at the cap** (release, refund, or cancel). This is the only cell of
   the design still undecided; see §8.

### 3.9 Seller Fulfillment Workspace (mock → contract)

The prototype at `verifund-seller-fulfillment/` is normative for layout and vocabulary
(decision 23). This section is the binding map: which contract each screen reads, what each
requirement card field means, which backend status each badge stands for, and where the
prototype and the contract still disagree. Where the prototype shows something no contract
provides, the contract changes; where the prototype invents data, the prototype changes.

#### 3.9.1 Screens and the contract behind them

| Route | Mock content | Contract source | State |
|---|---|---|---|
| `/seller/dashboard` | 4 stat cards, priority tasks, progress % | none — only ops has a list (`GET /transactions`) | deferred (§3.9.5) |
| `/seller/orders` | order table with lifecycle status | as above | deferred |
| `/seller/fulfillment` | task table: next action, progress, status | as above | deferred |
| `/seller/fulfillment/{id}` overview | product, buyer, agreement version, `Payment processed`, order value, deadline, `x/y` verified, requirement list, read-only agreement summary | `GET /seller/transactions/{id}` → `SellerProjection`; terms exist only on `AgreementProjection`, which has no seller route (`AgreementView` omits `terms`) | projection gains `requirements[]`, `dispute`, `receipt`; add a seller agreement read |
| `/seller/fulfillment/{id}/evidence` | same cards plus `Requirement ID · Linked to AGR-2048 v1` | same projection + `GET /seller/transactions/{id}/evidence` | needs per-attempt status |
| `/seller/fulfillment/{id}/activity` | chronological event timeline | `GET /transactions/{id}/events` is ops-only | needs a seller event read |
| `/seller/evidence` | cross-transaction evidence library | none | deferred |
| `/seller/payouts` | payment vs payout states | `SellerProjection` has no payout block (buyer projection does) | deferred |
| `/seller/settings` | profile, channels, notifications | none | non-normative; outside evidence scope |
| `/fulfillment/access/{token}` | invitation gate | `SellerTokenService`, `LinkSigner` exist; no HTTP route | exchange endpoint required |
| Upload modal | requirement prefilled, file, description | `POST /seller/transactions/{id}/evidence` | add `requirement_id`, reference artifacts, `captured_at` |

#### 3.9.2 The five cards are catalog requirements, not `EvidenceKind`s

The mock's ids (`product_photos`, `serial`, `hardware`, `warranty`, `shipping`) are not
`EvidenceKind` values. They are `requirement_id`s in the §3.1.1 catalog:

| Mock card | `requirement_id` | `kind` | `owner` | `source` |
|---|---|---|---|---|
| Product photographs | `product_photos` | `other` | seller | file |
| Serial number photograph | `serial_number` | `other` | seller | file |
| Hardware diagnostic report | `hardware_specifications` | `other` | seller | file |
| Warranty documentation | `warranty_documentation` | `other` | seller | file |
| Shipping information | `shipping_information` | `shipment_manifest` | seller | reference (carrier + tracking) |
| *(no card)* | `delivery_confirmation` | `delivery_confirmation` | system | reference (carrier record + buyer confirmation) |

VF-2048 therefore has **six** requirements: five seller-owned cards and one system row. That
is the reconciliation between decision 23 (five cards) and §3.3 (the seller does not
self-certify delivery). The shipping card maps to `shipment_manifest` so the existing
manifest field comparisons keep their meaning; it moves from a file to a structured
reference.

#### 3.9.3 Requirement card fields

| Mock field (`data.ts`, `RequirementRow`) | Contract field |
|---|---|
| `Requirement.title` | new `title` on the catalog requirement (short label; `description` is the long form) |
| `Requirement.description` | `description` |
| `Requirement.id` | `requirement_id` |
| `Requirement.formats[]` | `accepted_formats[]` (omit when `source=reference`) |
| `Requirement.status` | rollup of `RequirementResult.status` |
| `Requirement.items[]` | submission attempts for that requirement |
| `item.id` (`EV-00820`) | `evidence_id` |
| `item.name` | `original_filename` / reference value |
| `item.requirement` (a title string) | `requirement_id` |
| `item.type` (`Image`, `Document`, `Video`, `Link`) | `artifact_type` + `media_type` |
| `item.submitted` | `created_at` |
| `item.status` | per-submission status (new field, §3.9.4) |
| footer `Linked to AGR-2048 v1` | `requirement_id` + `agreement_id` + `agreement_version` |

#### 3.9.4 One status vocabulary, not two

| Mock badge | Where used | Contract expression |
|---|---|---|
| Required | requirement not submitted | `RequirementResult.status = NOT_SUBMITTED` while the seller may still upload |
| Processing | just-submitted item | `PENDING_SCAN`; transaction stays `VERIFICATION_PENDING` |
| Under review | item or requirement needing a human | `REVIEW` → `REVIEW_REQUIRED` |
| Verified | requirement satisfied | `PASS` |
| Action required | remediable failure / `Resolve evidence request` | `FAIL` on a seller-owned requirement → `REMEDIATION_REQUIRED` |
| Evidence required | workspace and task-list label | `FULFILLMENT_PENDING` with outstanding seller requirements |
| In progress | task list | `VERIFICATION_PENDING` with a mix of `PASS` and `NOT_SUBMITTED` |
| Fulfillment required | orders list | `FUNDED`, before fulfillment starts |
| Payment processed | header, payouts | `funding.status == captured`; never phrased as escrow |
| Fulfillment verified | payouts | all requirements `PASS`, `verification.status == "passed"` (`RELEASE_PERMITTED` or later) |

The prototype has **two** vocabularies. `EvidenceStatus` in `data.ts` declares five values;
`ui.tsx` maps eight badge strings, but two strings the pages actually pass —
`Evidence required` and `Fulfillment required` — are absent from that map and fall through
to the neutral grey chip, while `In progress` and `Fulfillment verified` are mapped yet sit
outside the `EvidenceStatus` type union. Production needs one enum plus an explicit
transaction-state → label map.

There is deliberately no `REJECTED` evidence badge. The recommendation doc lists
`REJECTED`, but this design maps a failed requirement to `Action required` and reserves
rejection for disputes (§3.8). Do not add a sixth badge.

#### 3.9.5 What must change

**Prototype changes (the contract is right, the mock invents):**

1. Replace `initialRequirements` with `SellerProjection.requirements[]`; the five ids become
   `requirement_id`s with `owner=seller`, plus the system-owned `delivery_confirmation` row.
2. Delete hardcoded progress (`40/70/60` on the dashboard, `40/70/85/60/20` on the task
   list). The workspace already computes `verified / total`; the list screens must too.
3. Upload modal: collect `captured_at`, and provide a reference/URL input when
   `source=reference` (the shipping card currently asks for a tracking number through a
   file picker).
4. Replace the invented receipt id (`SUB-00822`) with the submission/evidence id returned by
   the server.
5. Collapse the two status vocabularies into one enum (§3.9.4).
6. Render formats from `accepted_formats` instead of the hardcoded `JPG/PNG/WEBP/MP4`,
   `Tracking number`, `URL` chips.
7. The access screen must not treat "Continue to demo workspace" as the production flow;
   token exchange is a server call.
8. Per-requirement status updates are not client-side; the card renders the backend rollup.

**Backend additions the prototype forces — required for the workspace milestone:**

1. `SellerProjection` gains `requirements[]`, per-attempt status, `dispute`, and a submission
   receipt identity returned by the upload call.
2. Upload addressed by `requirement_id`, with `reference` artifacts and `captured_at`.
3. A seller-authenticated agreement read for the "View agreement" action and the agreement
   summary card. `GET /agreements/{id}` returns `AgreementView`, which omits `terms`; the
   only surface carrying terms is `AgreementProjection` (via `build_projection`) and the
   HTML document route. Both agreement routes are currently unauthenticated (§8).
4. `POST /fulfillment/access/{token}` invitation exchange, validating expiry, identity,
   seller ownership, transaction match, and permitted actions before redirecting.

**Seller-scoped reads — specified in §3.10, not deferred:**

5. Seller-scoped transaction list and dashboard counts.
6. Seller payout read.
7. Cross-transaction evidence library.

**Still deferred:**

8. Seller event/activity feed (needs a seller-scoped event read; `GET /transactions/{id}/events`
   stays ops-only for now).
9. Settings (channels, notifications).

**Format reconciliation.** The mock advertises `WEBP`, `MP4`, `Tracking number`, and `URL`.
Intake (`evidence.py:15`) accepts only `json`, `txt`, `pdf`, `png`, `jpeg`, and only as a
multipart file. Required change: add `image/webp` and video types to the allowlist, and add
`artifact_type=reference` so a tracking number or URL is a first-class submission rather
than a file pretending to be one.

### 3.10 Seller-scoped read coverage

Covers the five prototype screens whose data source was previously undefined:
`/seller/dashboard`, `/seller/orders`, `/seller/fulfillment`, `/seller/evidence`, and
`/seller/payouts`. It adds read paths only — no new evidence logic, no new states.

The prototype is authoritative for layout; it is **not** authoritative for these screens'
values. Four of its figures cannot be served honestly by the current model, so this
specification replaces them rather than reproducing them (§3.10.6).

#### 3.10.1 Authentication and scoping

- Bearer seller token, scope `txn:read`, same verification chain as the per-transaction
  routes: signature, expiry, revocation, seller ownership (`api/seller.py:18-43`).
- `claims.seller_id` is the **only** scoping key. A `seller_id` query parameter is rejected,
  not ignored, so a caller cannot mistake the endpoint for a filterable admin surface.
- Every query is bounded by `seller_id` in SQL; results never rely on post-filtering.
- A seller token can never widen its scope: the list endpoints return only that seller's
  rows, while the existing per-transaction routes keep their `403` cross-seller and `404`
  unknown-id behaviour.

#### 3.10.2 Endpoints

| Endpoint | Serves |
|---|---|
| `GET /seller/transactions?state=&limit=&cursor=` | dashboard counts, orders table, fulfillment task list |
| `GET /seller/evidence?kind=&limit=&cursor=` | evidence library |
| `GET /seller/payouts` | payouts screen |

`limit` defaults to 50, bounds `1..200`; out-of-range is `400 invalid_request`. Cursors are
opaque and keyset-based: `(created_at, transaction_id)` for transactions,
`(created_at, evidence_id)` for evidence. `repo.list_transactions`
(`repository.py:335-357`) already filters by `seller_id` and `state` but has no cursor, so
keyset paging is a small repo addition, not a new query surface.

#### 3.10.3 Response shapes

```text
SellerTransactionSummary
  transaction_id, run_id
  state: TransactionState                 # enum value, never a display string
  agreement_id, agreement_version
  amount_cents, currency, quantity
  line_items: [{ sku, name, quantity }]
  delivery_days, warranty_months, returns_days
  deadlines: { evidence: datetime|null, inspection: datetime|null }
  evidence: { submitted: int, required: int, complete: bool, received_kinds: [str] }
  allowed_actions: [str]                  # from allowed_actions(state, "seller")
  next_action: submit_evidence | replace_evidence | respond_to_dispute | none
  payout: { status: pending|paid|failed|none, amount_cents, updated_at } | null
  updated_at

SellerTransactionList
  items: [SellerTransactionSummary]
  counts_by_state: { TransactionState: int }   # over ALL seller transactions, not the page
  next_cursor: str | null

SellerEvidenceEntry
  evidence_id, transaction_id, kind, media_type, size_bytes,
  original_filename, note, created_at
  transaction_state: TransactionState
  verification: { status, reasons: [str], checked_at: datetime|null }   # transaction-level

SellerEvidenceLibrary
  items: [SellerEvidenceEntry]
  next_cursor: str | null

SellerPayoutView
  transactions: [{ transaction_id, amount_cents, currency, state, payout }]
  totals: { pending_cents: int, paid_cents: int, failed_cents: int }
```

`SellerProjection` (`models.py:809`) additionally gains `payout`, the field the buyer
projection already exposes, so the workspace header and the payouts screen read the same
source.

#### 3.10.4 Field provenance (what exists today)

| Field | Source now |
|---|---|
| `state`, `agreement_id`, `agreement_version`, `amount_cents`, `deadlines` | `TransactionRecord` |
| `line_items`, `quantity`, `delivery_days`, `warranty_months`, `returns_days` | `AgreementProjection` via `build_projection` |
| `evidence.submitted` / `.required` / `.complete` | realized `REQUIRED_EVIDENCE` kinds (`domain.py:84`) until §3.1.1 lands |
| `allowed_actions` | `allowed_actions(state, "seller")` (`domain.py:265-267`) |
| `next_action` | derived from `allowed_actions`; `submit_evidence` is the only value reachable before §3.5/§3.8 |
| `payout` | `record.payout` (already used by the buyer projection) |
| evidence rows | `evidence` table, which already carries `seller_id` (`repository.py:136`) |
| `verification` | `record.verification` — **transaction-level**, not per evidence item |
| `counts_by_state` | one grouped count over the seller's transactions |

Cost note: `service.list_transactions` (`service.py:320-339`) calls `list_evidence` per
row. The seller list must batch evidence counts into one grouped query, or the dashboard
becomes N+1 in the number of active transactions.

`counts_by_state` is computed over all of the seller's transactions rather than the returned
page, because the dashboard labels are counts of work, not previews of a page.

#### 3.10.5 Field life cycle

These fields are defined so they do not need a breaking change when the requirement model
lands:

- `evidence.submitted` / `.required` count requirement results once §3.2 exists; until then
  they count evidence kinds. No percentage is returned in either case.
- `next_action` gains `replace_evidence` when `REMEDIATION_REQUIRED` exists (§3.5) and
  `respond_to_dispute` when `DISPUTE_OPEN` exists (§3.8). Adding enum members is additive.
- `payout.status` keeps the payout states distinct from payment capture; the payouts screen
  must not derive a release from `funding.status`.

#### 3.10.6 What is deliberately not copied from the prototype

| Prototype | Why it is replaced |
|---|---|
| `verified / total` percentage (`40%`, hardcoded `40/70/85/60/20`) | Verification is per requirement and does not exist per item yet; a percentage would assert a completeness the model cannot support. Counts are returned instead |
| Per-item `Verified` / `Under review` badges in the evidence library | `VerificationProjection` is transaction-level; per-item status arrives with §3.2. The library shows transaction-level verification and links to the workspace |
| `Awaiting fulfillment $4,150` on payouts | This is a state count disguised as money. Totals are computed from payout records only (`pending`/`paid`/`failed`); no "awaiting" currency figure is produced |
| `Payment processed` as a free badge, and `Fulfillment verified` as a payout state | The list returns `state` plus `payout.status`; labels are a frontend map over enums, not values from the API |
| `Buyer: Maya Chen` in the workspace header | `SellerProjection` exposes no buyer identity and the agreement stores only `buyer_id`. Exposing buyer display names to sellers is a product/privacy decision, not something to inherit from a mock |
| Mock rows `VF-2051`, `VF-2054`, `VF-2057`, `VF-2060` | Demo data; the list returns whatever the authenticated seller actually has |

Buyer identity is the one omission that changes a visible element of the mock. Recorded here
so it is decided deliberately rather than discovered at implementation time.

#### 3.10.7 Sequencing

Independent of steps 1–11 except for contract types. Recommended after step 5
(per-requirement verification), because `evidence.submitted/required` and `next_action` are
then written once against requirement results instead of against `REQUIRED_EVIDENCE`. It is
not blocked by step 5: the kind-based counts are correct today, just shorter-lived.

#### 3.10.8 Non-goals

- Event/activity feed for sellers — stays ops-only in this milestone.
- Settings, messaging channels, notification preferences — no contract.
- Search across transactions beyond the `state` filter.
- Requirement-level progress on these list screens; that arrives with §3.2 and is consumed by
the workspace first.

## 4. State machine (final)

```text
AWARDED → AGREED → FUNDING_PENDING → FUNDED → FULFILLMENT_PENDING
  → VERIFICATION_PENDING → (REMEDIATION_REQUIRED ↔ VERIFICATION_PENDING)
  → RELEASE_PERMITTED → PAYOUT_PENDING → RELEASED
  → REVIEW_REQUIRED (any REVIEW; reversible to REMEDIATION/VERIFICATION)
  → DISPUTE_OPEN (valid buyer dispute; exits only by reviewer decision or ladder cap)
```

Transitions added by decisions 26–27:

```text
VERIFICATION_PENDING → DISPUTE_OPEN        (valid buyer dispute during inspection)
DISPUTE_OPEN → RELEASE_PERMITTED           (dismissed, or settled in seller's favor)
DISPUTE_OPEN → REMEDIATION_REQUIRED        (upheld; repair/replacement remedy)
DISPUTE_OPEN → CANCELED                    (upheld; refund remedy, or ladder cap)
DISPUTE_OPEN → REVIEW_REQUIRED             (referred; ladder cap outcome pending §8)
```

Seller `upload_evidence` allowed in: `FUNDED`, `FULFILLMENT_PENDING`, `VERIFICATION_PENDING`,
`REMEDIATION_REQUIRED`. Dispute counter-evidence is a separate, dispute-scoped submission
permitted in `DISPUTE_OPEN`; it does not satisfy a requirement.

## 5. API surface

Seller (existing, extended):

- `GET /seller/transactions/{id}` — projection now includes `requirements[]` and, when
  open, the `dispute` block
- `POST /seller/transactions/{id}/evidence` — `requirement_id` required and validated
  against the catalog (`owner=seller`), plus artifact: file or `reference`; returns the
  submission attempt. Replaces `kind` as the addressing key
- `POST /seller/transactions/{id}/dispute-evidence` — counter-evidence in `DISPUTE_OPEN`

Buyer (new):

- `POST /buyer/transactions/{id}/delivery-confirmed` — `{ confirmed_at, condition?, photos? }`
- `POST /buyer/transactions/{id}/accept`
- `POST /buyer/transactions/{id}/dispute` — `{ requirement_ids[], reason_code, claim,
  evidence[] }`; validity rules in §3.8

Ops (existing, narrowed):

- `POST /ops/transactions/{id}/release` — override only for `manual_flag`
- `POST /ops/transactions/{id}/extend-deadline`
- `POST /ops/transactions/{id}/return-to-remediation`
- `POST /ops/transactions/{id}/dispute-decision` — `{ decision, remedy?, note }`

## 6. Data model changes

Contracts (`models.py`):

- Add `RequirementResult` (with `owner`, `source`, `attempt`), `RequirementStatus`,
  and the `Requirement` catalog object from §3.1.1.
- Replace `EvidenceSummary.required/received/complete` with `requirements: list[RequirementResult]`.
- `VerificationProjection` adds `requirements`.
- `AwardRequest` gains `requirements: list[Requirement]`; keep `evidence_required` as a
  deprecated mirror for grandfathered callers (`inspection_period_hours` and
  `dispute_window_hours` are unchanged).
- Add `policy_version` to agreement and transaction.

DB (`repository.py`):

- `evidence` table: add `requirement_id`, `submission_attempt`, `source`
  (`seller|buyer|carrier|system`), `artifact_type` (`file|reference`), `reference` (URL or
  tracking value), `scan_status`.
- New `evidence_submissions` table (or attempt column on `evidence`) for "latest wins".
- `transactions` table: add `policy_version`, `acceptance` JSON block
  (status, deadline, decided_by, decided_at), and `dispute` JSON block
  (status, opened_at, reason_code, requirement_ids, deadline, escalation_rung,
  decided_by, decided_at, remedy).
- The requirement catalog lives in the stored agreement terms, not a new table; only
  `requirement_id` is denormalized onto evidence rows.
- `UniqueConstraint("transaction_id", "sha256")` stays for blob dedupe. A duplicate blob is
  a new *submission row*, not a no-op (`service.py:871`).

Projections (`service.py`):

- `_projection` and `seller_projection` populate `requirements[]`.
- Console release card (`verifund-tools.tsx:325-397`) reads per-requirement statuses
  instead of a single `override_allowed`.

## 7. Implementation sequence

1. Contracts — `RequirementResult`, `RequirementStatus`, the `Requirement` catalog object,
   updated summaries/projections, `policy_version`. Tests for serialization and floors.
2. Requirement catalog — buyer agent authors `AwardRequest.requirements[]`; seller agent
   mandate validation; `generator.py` copies requirements into terms; floors in `terms.py`;
   grandfathered-agreement projection (§3.1.1).
3. State machine — add `REMEDIATION_REQUIRED` and `DISPUTE_OPEN`, transitions, upload
   permissions, `STAGE_BY_STATE`, `policy_version` on agreement.
4. Agreement as catalog — `evaluate()` takes terms; remove `REQUIRED_EVIDENCE` and the
   hardcoded set at `policy.py:65`; grandfathering.
5. Per-requirement verification — rewrite `evaluate()` to return `list[RequirementResult]`
   plus rollup; `by_kind.setdefault` (`policy.py:61`) becomes latest submission; deterministic
   checks per requirement; system-owned failures cannot remediate.
6. Buyer actions — `CONFIRM_DELIVERY`, `ACCEPT`, evidence-gated `DISPUTE`; system-generated
   `delivery_confirmation`.
7. Dispute — `DISPUTE_OPEN` handling, seller counter-evidence, `dispute-decision` endpoint,
   escalation alerts. **Blocked** on the ladder-cap outcome (§8).
8. Carrier integration — aggregator client, tracking → transaction mapping, webhook/polling,
   scan-status gating.
9. Remediation + storage — submission attempts, reference submissions, object store adapter,
   scanning, signed URLs, compensating token controls.
10. Acceptance clock + reconciler — deemed acceptance release path; `max(inspection, dispute)`;
    `extend_deadline`.
11. AI boundary — extraction-only interface; AI never emits `PASS` and never resolves a dispute.
12. Seller-scoped reads — §3.10 endpoints, contracts, batched evidence counts, `payout` on
    `SellerProjection`. No new evidence logic.
13. Console + mock — per-requirement UI per §3.9; expand the intake allowlist (`webp`,
    video, reference artifacts); add `REMEDIATION_REQUIRED` and `DISPUTE_OPEN` statuses;
    collapse the prototype's two status vocabularies into one.

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
- A valid dispute holds funds with no automatic exit (decision 27). Until the ladder cap
  outcome is chosen, `DISPUTE_OPEN` can sit unresolved indefinitely while captured funds
  are held and no receipt can issue — the seller has no upload rights there unless the
  dispute-scoped counter-evidence surface ships with it.
- Buyer-authored catalogs shift negotiation load: a floor-compliant but unsatisfiable
  requirement (`operator=eq` on an unobservable value) pushes that requirement permanently
  to `REVIEW`. Floors cannot detect this; only seller-agent mandate validation can.
- `requirement_id` stability must be enforced when a change request is applied, or evidence
  re-attachment silently drops submissions and the seller re-submits work already verified.
- Evidence-gated disputes reject buyers who hold no artifact. The single retry limits the
  harm, but a subjective complaint still has no path; that gap is deliberate and should be
  stated in the buyer-facing terms.
- The prototype's list screens (dashboard, orders, fulfillment, evidence library, payouts)
  have no seller-scoped read endpoints today: only ops has `GET /transactions`, and
  `SellerProjection` carries no payout block. §3.10 specifies the three endpoints, but until
  they ship the prototype must stay mock-fed there; the workspace is the only screen whose
  data source changes in the workspace milestone.
- §3.10 removes buyer identity from the seller list, which the prototype shows in the
  workspace header. If buyer names are required for the demo, that is a deliberate exposure
  decision to record before implementation, not a field to add silently.
- `GET /agreements` and `GET /agreements/{id}` are unauthenticated while exposing terms and
  party ids. The workspace's "View agreement" action must not be wired to that surface
  before it is gated.

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
- `packages/verifund_contracts/verifund_contracts/models.py:96-108,744-767` — ReviewReason, evidence contracts
- `apps/console/features/chat/verifund-tools.tsx:325-397` — release gate
- `verifund-seller-fulfillment/src/lib/data.ts` — mock transaction, five requirement cards, status type
- `verifund-seller-fulfillment/src/components/FulfillmentWorkspace.tsx` — tabs, requirement card, upload modal, receipt toast
- `verifund-seller-fulfillment/src/components/ui.tsx` — badge status map (eight strings, five typed)
- `verifund-seller-fulfillment/src/app/seller/*/page.tsx` — dashboard, orders, fulfillment list, evidence library, payouts
- `verifund-seller-fulfillment/src/app/fulfillment/access/[token]/page.tsx` — invitation gate
- `apps/verifund_control_plane/verifund_control_plane/agreements/generator.py:25,83` — `evidence_required` copied from award
- `packages/verifund_contracts/verifund_contracts/terms.py:56-63,123-129` — creation floors
- `apps/buyer_agent/buyer_agent/settlement_flow.py:113-120` — buyer-authored evidence list, 48h inspection
- `apps/verifund_control_plane/verifund_control_plane/domain.py:265-267` — seller actions (none in review)
- `apps/verifund_control_plane/verifund_control_plane/policy.py:61,65` — first-submission-wins, hardcoded required set
- `apps/verifund_control_plane/verifund_control_plane/service.py:865-905` — upload state advance and dedupe no-op
- `apps/verifund_control_plane/verifund_control_plane/evidence.py:36-80` — intake validation and content addressing
- `apps/verifund_control_plane/verifund_control_plane/repository.py:335-357` — `list_transactions` (seller/state filters, no cursor)
- `apps/verifund_control_plane/verifund_control_plane/service.py:320-339` — per-row evidence fetch (N+1 to batch)
- `packages/verifund_contracts/verifund_contracts/models.py:809-827` — `SellerProjection` (no payout block)
- `apps/verifund_control_plane/verifund_control_plane/repository.py:136` — `evidence.seller_id`, enabling seller-scoped reads
