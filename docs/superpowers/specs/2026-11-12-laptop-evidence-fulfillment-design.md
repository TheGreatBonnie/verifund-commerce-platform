# Laptop Evidence & Fulfillment: Design

**Status:** Approved for implementation planning
**Date:** 2026-11-12
**Supersedes:** `2026-11-04-verifund-seller-evidence-target-design.md` where they conflict (see D1)
**Source documents:** `canonical-laptop-seller-evidence-and-simulated-fulfillment.md`,
`seller-evidence-requirements.md`,
`verifund-evidence-fulfillment-backend-architecture.md`

---

## 1. Purpose

Make Verifund able to prove, from a machine-verifiable record, that the laptop
which was sold is the laptop that was packaged, accepted by a carrier,
delivered, and accepted by the buyer — and to authorize a seller payout only
when that chain holds and no blocking issue remains.

The deliverable is an extension of the existing control-plane spine, not a new
subsystem. See §3 for what already exists.

## 2. Scope

**In scope**

- A laptop-specific requirement catalog generated from the approved agreement.
- Provenance (challenge-code) verification.
- Carrier-authoritative shipment, acceptance, delivery, POD and weight data.
- First-class inspection and dispute records with a claim taxonomy.
- An explicit, explainable payout-blocker list surfaced to seller and buyer.
- Seven deterministic, replayable fulfilment scenarios with fixtures.
- Staged evidence grouping in the existing seller workspace.

**Out of scope (deliberate)**

- `fulfillment_tasks`, `fulfillment_requirements`, `verification_runs`,
  `evidence_verifications`, `release_evaluations`, `settlement_intents` tables.
- Alembic migrations or a PostgreSQL/Neon migration.
- S3/object storage, presigned URLs, real malware scanning, EXIF stripping.
- A transactional outbox, message broker, or new worker framework.
- Service extraction into microservices.
- OEM/warranty lookups, CV damage detection, image similarity scoring.
- Partial-settlement negotiation (`partial_agreement` scenario).
- Any change to `apps/seller_agent` (see D12).

**Product semantics come from the source documents. Implementation mechanics
come from the existing repository.** That rule resolves every remaining conflict.

---

## 3. Decision record

These decisions were settled in design review. They are binding on the plan.

| ID | Decision |
|---|---|
| D1 | The three 2026-11-12 documents supersede `2026-11-04-verifund-seller-evidence-target-design.md` wherever they conflict. Reopened explicitly: delivery authority, requirement catalog, review-state ownership, inspection/dispute persistence. |
| D2 | Precedence among the three: architecture document wins on mechanics, canonical document wins on policy semantics, requirements document is content reference. |
| D3 | Baseline evidence gates **fulfilment**, not deal activation. Requirements are generated when the buyer payment is confirmed and funds are held in the ledger. |
| D4 | Verification realism: deterministic checks are implemented for real; image/content extraction is adapter-based; nothing ambiguous auto-passes. |
| D5 | All seven required scenarios are implemented. UI polish is limited to `happy_path`, `specs_mismatch`, `never_delivers`, and one dispute. |
| D6 | Inspection window defaults to 48 hours; sandbox may compress it. Time is advanced through the existing injected clock, never by sleeping or hard-coded flags. |
| D7 | Requirement status stays derived, never persisted. The agreement version already pins the catalog. |
| D8 | The laptop catalog lives in `packages/verifund_contracts/verifund_contracts/terms.py`, so one projection path serves the seller API, `policy.evaluate`, and the console. |
| D9 | The carrier is authoritative for shipment and delivery facts on shipped flows. Buyer delivery confirmation is retained as corroboration. This reopens 2026-11-04 decision 12. |
| D10 | Provenance verification: an adapter extracts the code; a deterministic comparison against an active, unexpired, single-use challenge decides the outcome. |
| D11 | Storage stays on the local content-addressed `EvidenceStore`. SQLite stays. Schema changes are additive in the existing `create_all` + idempotent `ALTER TABLE` idiom. |
| D12 | No seller-agent work. Its `evidence_outbox` has no production producer; the live path is console → control plane. |
| D13 | Five-value requirement status vocabulary is retained. `ACTION_REQUIRED` and `UNDER_REVIEW` become a derived `action_owner` field, not new states. |
| D14 | Delivery timeout never triggers an automatic refund. Buyer funds are already captured; a timeout raises a blocker and routes to review. |

---

## 4. What already exists (do not rebuild)

| Capability | Location |
|---|---|
| Requirement-addressed, immutable evidence submissions with attempt numbering, agreement hash/version pinning, reference artifacts, declarations | `apps/verifund_control_plane/verifund_control_plane/service.py:1054` (`add_evidence`), `repository.py:154` (`evidence`), `:181` (`evidence_submissions`), `:191` (`requirement_declarations`) |
| Deterministic requirement evaluation and rollup | `policy.py:458` (`evaluate`), `:323` (`matches_requirement`), `:443` (`catalog_fulfilled`), `:362` (`_declaration_covers`) |
| Requirement catalog projection from agreement terms | `packages/verifund_contracts/verifund_contracts/terms.py:72` (`project_requirements`) |
| Transaction state machine with CAS transitions | `domain.py:24` (`ALLOWED_TRANSITIONS`), `repository.py:648` (`transition`) |
| Ledger, idempotency, provider operations, webhook dedupe | `domain.py:273`/`:294`, `repository.py:141`/`:256`/`:208`/`:224` |
| PayPal port with sandbox and fake implementations | `paypal/port.py`, `paypal/sandbox.py`, `paypal/fake.py` |
| Reconciler sweeps (funding, payout, tracking, deadlines, scans, deemed acceptance, receipts, ledger) | `reconciler.py:110` |
| Content-addressed local evidence store with SHA-256 and media allowlist | `evidence.py:30` |
| Signed receipts, audit log, transaction event feed | `receipts.py`, `repository.py:324`, `:131` |
| Seller workspace: requirement cards, upload dialog, dispute panel, payouts | `apps/console/app/seller/fulfillment/[id]/` + `components/seller/` |
| Injected clock | `create_app(settings, clock=...)` (`app.py:51`) |

Consequence: the source documents' proposed schema (§11 of the architecture
document) is largely a normalisation of state that already exists in a coherent
form. Adopting it would replace working code with doc conformance.

---

## 5. Target architecture

```
approved agreement version
        │
        ├── terms.project_requirements(category, terms)      ← extended (D8)
        ▼
transaction (state machine unchanged)  ◄── payment confirmed, funds held
        │
        ├── seller evidence  ──► evidence / evidence_submissions / requirement_declarations
        │        └── provenance challenge (new)
        │
        ├── shipment         ──► shipments ──► carrier_events (new)
        │                                              ▲
        │                                CarrierAdapter ├── MockCarrierAdapter (sandbox)
        │                                              └── production adapter (later)
        │
        ├── delivery         ──► delivery_confirmations (new)
        ├── inspection       ──► inspection_records (new)
        └── dispute          ──► disputes (new)
        │
        ▼
policy.evaluate ──► blockers[] ──► release / _start_payout (unchanged)
                                        │
                                        ▼
                            ledger + PayPal payout (unchanged)
```

---

## 6. Requirement catalog

Category key: `electronics.laptop.refurbished`. Projected per transaction so
agreement-specific values (RAM minimum, battery threshold, warranty duration,
declared value) are authoritative.

| # | requirement_id | owner | source | stage | mandatory | constraints / checks |
|---|---|---|---|---|---|---|
| 1 | `serial` | seller | file | `product_identity` | yes | `serial_readable exists`; `serial_matches eq <declared>` |
| 2 | `provenance` | seller | file | `product_identity` | yes | `challenge_code eq <active challenge>` |
| 3 | `product_photos` | seller | file | `product_condition` | yes | `min_items 7`; `views_cover front,back,left,right,keyboard,screen,underside,serial` |
| 4 | `condition_declaration` | seller | `declaration` | `product_condition` | yes | `battery_health_pct gte`, `locks_disabled exists`, `mdm_not_enrolled exists`, `accessories contains charger`, `cosmetic_grade exists` |
| 5 | `hardware` | seller | file | `product_compliance` | yes | `ram_gb gte 32`, `storage_gb gte 1024`, `cpu contains <agreed>`, `gpu contains <agreed>` |
| 6 | `battery` | seller | file | `product_compliance` | yes | `battery_health_pct gte 80`, `cycles lte 500` |
| 7 | `warranty` | seller | file | `product_compliance` | yes | `warranty_days gte 90` |
| 8 | `packaging` | seller | file | `packaging` | yes | `min_items 3` (`views_cover unit_with_serial,inside_box,sealed_with_label`) |
| 9 | `shipping` | seller | reference | `packaging` | yes | carrier + tracking; `declared_value_minor`, `weight_expected_g` |
| 10 | `insurance_confirmation` | seller | file | `packaging` | conditional | `insured_value_minor gte declared_value_minor`; required only when `declared_value_minor` exceeds the policy threshold |
| 11 | `carrier_acceptance` | system | system | `delivery` | yes | `PICKED_UP` or `CARRIER_ACCEPTED` event exists |
| 12 | `delivery_confirmation` | system | system | `delivery` | yes | `DELIVERED` or `DELIVERED_SIGNED`; `pod_exists`; `signature_exists` when policy requires |
| 13 | `invoice` | seller | file | `packaging` | yes | — |

`min_items` and `views_cover` are **requirement-level constraints evaluated by
policy over a set of submissions**, not artifact checks on a single file.
`views_cover` is satisfied by the union of each submission's declared
`view_label`, which is what keeps coverage deterministic without computer vision.
Artifact checks (`ram_gb gte 32`, `warranty_days gte 90`, …) continue to use the
existing per-item comparison machinery.

Notes:

- Seven requirements already exist in
  `apps/buyer_agent/buyer_agent/settlement_flow.py:55-258`: `serial`,
  `product_photos`, `hardware`, `warranty`, `shipping`, `delivery_confirmation`,
  `invoice`. Six are new: `provenance`, `condition_declaration`, `battery`,
  `packaging`, `insurance_confirmation`, `carrier_acceptance`. Existing ids are
  preserved; no renaming.
- The fixture directory `verifund-test-laptop-evidence/manifest.json` uses a
  different id set (`product_identity`, `serial_number`,
  `hardware_specifications`, `shipping_delivery`, `buyer_acceptance`) and must be
  remapped to the ids above.
- `carrier_acceptance` and `delivery_confirmation` are **system-owned**: the
  seller can neither upload to them nor mark them complete. `policy.evaluate`
  resolves them from shipment state.
- `insurance_confirmation` mandatory-ness is computed at projection time from
  the agreement's declared value and the configured threshold.

---

## 7. Contract changes (`packages/verifund_contracts`)

`terms.py`

- Add `stage: str | None` to `Requirement`, one of
  `product_identity | product_condition | product_compliance | packaging | delivery`.
- Add `min_items: int = 1`.
- Add `required_views: list[str] = []`.
- Extend `project_requirements` with the category template table (§6) and the
  threshold rules.
- Category resolution: `electronics.laptop.refurbished` is read from the
  agreement terms (product category on the offer), falling back to the existing
  generic catalog when no category is present. Existing agreements therefore
  project exactly as they do today, and new fields default
  (`stage=None`, `min_items=1`, `required_views=[]`), so old transactions keep
  evaluating correctly.
- Keep the existing `floors` behaviour so agreements can raise but not lower
  mandatory requirements.

`models.py`

- `RequirementSource` gains `declaration` (`file | reference | declaration`).
- `RequirementStatus` unchanged (`not_submitted | pending_scan | pass | fail | review`).
- New enum `ActionOwner` (`seller | reviewer | none`) — derived, not stored.
- New enum `CarrierEventStatus`:
  `LABEL_CREATED | CARRIER_ACCEPTED | PICKED_UP | IN_TRANSIT | OUT_FOR_DELIVERY |
  DELIVERED | DELIVERED_SIGNED | DELIVERY_EXCEPTION | DELIVERY_FAILED |
  RETURN_TO_SENDER | LOST | UNKNOWN`.
- New enum `DisputeClaimType`:
  `EMPTY_BOX | WRONG_DEVICE | UNDISCLOSED_DAMAGE | NOT_POWERING_ON |
  MISSING_ACCESSORY | OTHER`.

`EvidenceSubmission` gains `view_label: str | None` (the seller's declared view
for coverage checks, which is how `views_cover` stays deterministic without CV).

`SellerProjection` (console contract, `apps/console/lib/seller-types.ts`) gains
`blockers`, `shipment`, `inspection`, and per-requirement `action_owner` and
`view_label`.

---

## 8. New domain objects

Additive tables, existing repository idiom (`create_all` + idempotent
`ALTER TABLE`), all tenant-scoped, all with `created_at`.

```sql
provenance_challenges(
  id, organization_id, transaction_id, code, issued_at, expires_at, used_at,
  status,  -- active | used | expired | superseded
  UNIQUE(organization_id, transaction_id, code)
)

shipments(
  id, organization_id, transaction_id, carrier_key, tracking_number, service_level,
  declared_value_minor, insured_value_minor, currency, weight_expected_g,
  status, created_at, updated_at,
  UNIQUE(carrier_key, tracking_number)
)

carrier_events(
  id, shipment_id, carrier_key, provider_event_id, normalized_status,
  event_at, received_at, weight_g, payload_json,
  UNIQUE(carrier_key, provider_event_id)
)

delivery_confirmations(
  id, shipment_id, delivered_at, recipient_reference, signature_reference,
  pod_evidence_id, weight_g
)

inspection_records(
  id, organization_id, transaction_id, status,  -- pending | accepted | disputed | expired
  decision, deadline_at, resolved_at, resolved_by
)

disputes(
  id, organization_id, transaction_id, opened_by, claim_type, status,
  resolution, resolved_by, resolved_at
)
```

`DISPUTE_OPEN` remains a transaction state; the `disputes` row is the case
record. Existing evidence, verification, ledger and payout tables are unchanged
except for additive columns:

```sql
ALTER TABLE evidence_submissions ADD COLUMN reason_code TEXT;
ALTER TABLE evidence_submissions ADD COLUMN verification_method TEXT;
ALTER TABLE evidence_submissions ADD COLUMN rule_version INTEGER;
ALTER TABLE evidence_submissions ADD COLUMN confidence REAL;
ALTER TABLE evidence_submissions ADD COLUMN view_label TEXT;
```

These carry findings on the submission, which is where evidence-level findings
already live. No separate findings table is introduced.

---

## 9. Provenance challenge

**Issue** — `POST /seller/transactions/{id}/provenance-challenge`

- Default TTL 60 minutes, configurable (`provenance_ttl_minutes`).
- Issuing supersedes any active challenge for the transaction.
- Response: `{ code, issued_at, expires_at }`. The code embeds the transaction
  short id (`VF2048-839251` style) so it is self-identifying to a human.

**Verify** — inside `policy.evaluate`, when the `provenance` requirement has a
submission:

1. Extraction adapter returns `extracted_code` and `confidence`.
2. Deterministic rules, in order:
   - no active challenge → `review` (`CHALLENGE_MISSING`)
   - challenge expired → `fail` (`CHALLENGE_EXPIRED`), `action_owner=seller`
   - extracted code ≠ active code → `review` (`CHALLENGE_MISMATCH`)
   - active match → atomic `UPDATE ... WHERE status='active'` consumes the
     challenge, then `pass`.
3. Consuming twice is impossible; the conditional update is the single-use
   guarantee.

**Adapters**

- Sandbox: `FixtureChallengeExtractor` reads the expected code from the
  scenario fixture and returns it with `simulated: true`.
- Otherwise: `LlmVisionExtractor` (existing LLM infrastructure) returns a
  structured extraction with confidence and provider/model recorded.

The extraction result is stored as a verification finding on the submission.
The adapter never decides; the comparison does.

---

## 10. Carrier integration

**Protocol** (`carrier.py`, currently unreferenced — becomes live):

```python
class CarrierAdapter(Protocol):
    async def register_tracking(self, shipment) -> dict: ...
    async def get_tracking_events(self, tracking_number: str) -> list[dict]: ...
    async def get_proof_of_delivery(self, tracking_number: str) -> dict | None: ...
```

Selection mirrors `PaymentPort`, at the application boundary in `app.py`:
`mode == "sandbox"` → `MockCarrierAdapter`, else the production adapter.

**Registration** — `POST /seller/transactions/{id}/shipment`

Validates state and agreement version, resolves the `shipping` requirement,
creates the `shipments` row, calls `register_tracking`, and writes an outbox-free
`transaction_events` entry. Rejects a duplicate `(carrier, tracking)` pair.

**Ingestion**

`Reconciler._sweep_shipments` runs on the existing interval:

- Polls non-terminal shipments with bounded backoff.
- Inserts events idempotently by `(carrier_key, provider_event_id)`;
  out-of-order events are stored and the derived state is recomputed, never
  patched in place.
- On `DELIVERED` / `DELIVERED_SIGNED`, fetches POD when policy requires it,
  writes `delivery_confirmations`, verifies `carrier_acceptance` and
  `delivery_confirmation`, and starts inspection.
- Weight comparison: `abs(carrier_weight_g - weight_expected_g) / weight_expected_g`
  above the configured tolerance raises `WEIGHT_ANOMALY` (a blocker), never an
  adverse verdict.
- Stops polling terminal shipments.

**Rules encoded**

- `LABEL_CREATED` never satisfies `carrier_acceptance`.
- A delivered scan never satisfies `condition_declaration`, `serial`, or any
  seller evidence requirement.
- Missing weight is `unavailable`, never fabricated.

**Timeout** — delivery deadline from agreement terms or policy. On expiry
without delivery: `DELIVERY_TIMEOUT` blocker + `REVIEW_REQUIRED` action. No
automatic refund (D14).

**Buyer confirmation** — `POST /transactions/{id}/delivery-confirmed` remains,
records corroboration, and can no longer substitute for carrier delivery.

---

## 11. Inspection and disputes

**Inspection** — created when `delivery_confirmation` passes. Deadline =
carrier `delivered_at` + `inspection_window_hours` (48 default, compressed in
sandbox), stored on `inspection_records` with the policy version that produced
it.

States: `pending | accepted | disputed | expired`.

- `POST /transactions/{id}/accept` → `accepted`.
- `POST /transactions/{id}/dispute` with `claim_type` → `disputed` + a
  `disputes` row.
- Reconciler expiry: `expired` only if every requirement passed at expiry
  (deemed acceptance is a policy outcome, not an assumption). Otherwise the
  transaction moves to `REVIEW_REQUIRED`.

**Disputes** — seller counter-evidence continues to use
`POST /seller/transactions/{id}/dispute-evidence` (existing). Ops resolution
continues to use `POST /ops/dispute-decision` (existing) and must now record
claim type, rationale, reviewer, and resolution on the `disputes` row.

Buyer evidence submission for inspection/disputes is a gap: the console has
buyer settlement views but no buyer evidence upload. Scope decision: reuse the
seller evidence pipeline with `owner=buyer` requirements and a buyer-scoped
endpoint mirroring `POST /seller/transactions/{id}/evidence`. `owner=buyer`
requirements are never rendered in the seller workspace.

---

## 12. Verification and status semantics

`policy.evaluate` is extended along three axes:

1. **New requirement types** — `declaration` source (via
   `requirement_declarations`), `min_items`, `views_cover`, `challenge_code`.
2. **System-owned requirements** — `carrier_acceptance` and
   `delivery_confirmation` resolve from shipment/delivery state rather than
   evidence items.
3. **Blocker production** — see §13.

**Status mapping (D13)**

| Semantic | Status | `action_owner` |
|---|---|---|
| Not yet submitted | `not_submitted` | `seller` |
| Uploaded, scan running | `pending_scan` | `none` |
| Failed, seller can fix | `fail` | `seller` |
| Failed, material/terminal | `fail` + `reason_code` | `reviewer` |
| Ambiguous or low confidence | `review` | `reviewer` |
| Passed | `pass` | `none` |

No sixth status is introduced. `REJECTED` from the source documents maps to
`fail` + terminal `reason_code`.

**Findings** remain on the submission (`evidence_submissions`) with
`reason_code`, `confidence` where applicable, `verification_method`, and
`rule_version`. Extraction never writes a status directly.

---

## 13. Release policy and blockers

`policy.evaluate` returns `blockers: list[Blocker]` in addition to its outcome.
Blocker codes:

```
AGREEMENT_NOT_APPROVED
AGREEMENT_VERSION_STALE
BUYER_PAYMENT_NOT_CONFIRMED
PAYMENT_NOT_RECONCILED
REQUIREMENT_INCOMPLETE:<requirement_id>
REQUIREMENT_NEEDS_REVIEW:<requirement_id>
CARRIER_ACCEPTANCE_MISSING
DELIVERY_NOT_VERIFIED
DELIVERY_TIMEOUT
DELIVERY_EXCEPTION
WEIGHT_ANOMALY
POD_MISSING
SIGNATURE_MISSING
INSURANCE_NOT_CONFIRMED
INSPECTION_OPEN
INSPECTION_REQUIRES_REVIEW
DISPUTE_OPEN
PAYOUT_ALREADY_ISSUED
PAYOUT_RECIPIENT_INVALID
COMPLIANCE_HOLD
```

Properties:

- Emitted only when authoritative state is read inside a transaction; never from
  client-supplied booleans.
- Exposed on `SellerProjection` and the buyer settlement view, each with a
  human-readable explanation.
- Recorded as a `transaction_events` entry (`release.evaluated`) so the history
  is reconstructable. No new table.
- `service.release` refuses to proceed unless `blockers == []`; the existing
  idempotency key and ledger checks remain the final guard.

---

## 14. API additions

Seller:

```
POST  /seller/transactions/{id}/provenance-challenge   -> { code, issued_at, expires_at }
GET   /seller/transactions/{id}/provenance-challenge   -> active challenge or 404
POST  /seller/transactions/{id}/shipment               -> { shipment_id, status }
GET   /seller/transactions/{id}/shipment               -> shipment + normalized events + POD
```

Existing seller endpoints unchanged; `POST .../evidence` gains an optional
`view_label` multipart field.

Buyer:

```
POST  /transactions/{id}/evidence          (new, owner=buyer requirements)
POST  /transactions/{id}/dispute           (extended with claim_type)
GET   /transactions/{id}/inspection        (new, status + deadline + outcome)
```

Ops (all behind `require_ops`):

```
POST  /ops/shipments/{id}/poll             (manual poll, deterministic in tests)
POST  /ops/inspection/{id}/resolve         (reviewer resolution with rationale)
```

Client-supplied `status`, `delivered`, `payout_eligible` remain rejected.

---

## 15. Workspace UI deltas

Console changes are additive to `app/seller/fulfillment/[id]/`.

1. **Stage grouping** — requirement cards grouped by the five stages
   (Identity, Condition, Compliance, Packaging, Delivery) with a stage-level
   rollup. This is the main visual change and the one judges read first.
2. **Blocker panel** — "Payout not authorized because: …" with one row per
   blocker and a link to the offending requirement. Replaces the current binary
   payout status.
3. **Provenance card** — displays the active code with copy-to-clipboard, a
   countdown, and a regenerate action when expired.
4. **Shipment card** — carrier, tracking, event timeline, weight comparison, POD
   and signature status. System-owned: read-only.
5. **Inspection/dispute panel** — claim type, days open, escalation rung,
   expected next step, and seller counter-evidence upload.
6. **View labels** — the upload dialog gains a view selector for
   `product_photos` and `packaging`, which is what makes coverage deterministic.

No new design system work: existing `mm-*` conventions, `Panel`, `Status`,
`Badge`, `Alert` components.

---

## 16. Simulation

**Fixtures** — `fixtures/laptop/<scenario>/` for the seven scenarios, reusing
the images and PDFs already committed in `verifund-test-laptop-evidence/` after
remapping `manifest.json` to real requirement ids. Byte-identical files must not
be reused across requirements (§18).

**Adapters** — selected by `FULFILLMENT_MODE` / `settings.mode`:
`FixtureChallengeExtractor`, `MockCarrierAdapter`, `FixtureMediaVerifier`,
existing `FakePaymentPort`, existing `FakeScanner`.

**Clock** — the existing `clock` injection. Scenarios advance time; nothing
sleeps.

**Replay** — `scripts/run_scenario.py --scenario <key>` seeds a tenant,
agreement, transaction and the scenario's evidence, then drives the workflow to
a terminal state and prints the final state, blockers, ledger and provider
references. A pytest e2e asserts the same outcome.

**Scenarios**

| Scenario | Behaviour | Expected |
|---|---|---|
| `happy_path` | All requirements pass; carrier accepts; delivered with POD; buyer accepts or inspection expires clean | `PAYOUT_AUTHORIZED` → `PAYOUT_COMPLETED`, exactly one payout |
| `specs_mismatch` | `hardware` check fails (RAM below agreement) | `fail` + `REQUIREMENT_INCOMPLETE:hardware`; no payout |
| `packing_photo_missing` | `packaging` has fewer than `min_items` | `not_submitted`/`fail`; seller action; no payout |
| `weight_anomaly` | Pickup weight far below expected | `WEIGHT_ANOMALY` blocker + review; no payout |
| `never_delivers` | Events stall; clock passes the deadline | `DELIVERY_TIMEOUT`; review; no refund automatic |
| `dispute_seller_wins` | `EMPTY_BOX` claim; complete chain; POD and weight support seller | Dispute resolved for seller; payout proceeds only if all other conditions hold |
| `dispute_buyer_wins` | `UNDISCLOSED_DAMAGE` with credible buyer evidence | Seller payout denied; refund path per policy |

All generated evidence and carrier events carry `simulated: true` and a
`SIMULATED` label in the UI and in receipts.

---

## 17. Phases

| Phase | Scope | Files (primary) | Exit criterion |
|---|---|---|---|
| P1 | Catalog, `declaration` source, `min_items`/`views_cover`, view labels | `terms.py`, `models.py`, `buyer_agent/settlement_flow.py`, `policy.py`, `service.add_evidence` | Laptop agreement projects 13 requirements; `specs_mismatch` fails with a per-requirement finding |
| P2 | Provenance challenge | new table + service methods, `policy.py`, extraction adapters | Code issues, matches once, expires, refuses reuse; mismatch → `review` |
| P3 | Carrier, shipment, delivery, timeout | `carrier.py`, 3 new tables, `Reconciler._sweep_shipments`, `service` methods | Happy delivery verifies; `never_delivers` blocks without refund; duplicate/out-of-order events are idempotent |
| P4 | Inspection, disputes, claim types | 2 new tables, buyer/seller routes, reconciler expiry | Open dispute blocks payout; resolution is recorded, not inferred |
| P5 | Blockers + staged workspace | `policy.py`, `api/seller.py`, console components | Seller sees exactly what blocks payout and why |
| P6 | Scenarios, fixtures, replay | `fixtures/laptop/`, `scripts/run_scenario.py`, e2e tests | All seven replay deterministically from a clean database |

Each phase lands with tests in the same change; the lifecycle tests that
currently assert buyer-attested delivery are updated in the P3 change, not after.

---

## 18. Risks

| Risk | Mitigation |
|---|---|
| `UNIQUE(transaction_id, sha256)` collides when the same fixture bytes are used for two requirements | Distinct fixture file per requirement; add a test asserting two requirements with identical bytes do not cross-match |
| `min_items` / `views_cover` are new policy primitives; `catalog_fulfilled` currently evaluates item-at-a-time | Implement as an aggregation step over submissions with explicit unit tests before wiring into `evaluate` |
| Carrier authority changes `confirm_delivery` semantics | Update `tests/integration/test_verifund_lifecycle.py` in the same commit; keep buyer confirmation as corroboration |
| `source=declaration` widens the requirement union | Explicit branch in `add_evidence` (declarations arrive via the declarations endpoint, not the file endpoint) and in `matches_requirement` |
| 13 requirements is a heavy workspace | Grouping by stage, collapse passed stages by default |
| Signature/POD policy differs by value and carrier capability | Policy-driven, and a missing capability is `unavailable` + blocker, never a silent pass |

---

## 19. Definition of done

- [ ] A laptop agreement projects the 13 requirements with stage, source,
      mandatory and checks.
- [ ] Requirements remain derived; no requirement status table exists.
- [ ] Provenance challenge is single-use, expiring, and auditable.
- [ ] Carrier events are idempotent, ordered, and normalized; `LABEL_CREATED`
      cannot satisfy acceptance.
- [ ] Delivery, inspection and dispute are three distinct states with records.
- [ ] Every payout decision is explained by a blocker list, and the list is
      recorded in the transaction history.
- [ ] Seven scenarios replay deterministically; each asserts final state,
      blockers, ledger and provider reference.
- [ ] All simulated artifacts are labelled.
- [ ] No duplicate payout is possible on retry, webhook replay, or concurrent
      release.
- [ ] Tenant isolation and cross-tenant 404 behaviour hold for every new
      endpoint.

## 20. Non-goals restated

This design does not make Verifund a regulated escrow service, does not claim
PayPal custody, and does not assert that any single artifact proves liveness,
contents, or condition. It records what was submitted, what independent sources
reported, what policy concluded, and why money did or did not move.
