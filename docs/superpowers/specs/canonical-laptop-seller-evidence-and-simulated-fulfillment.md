# Canonical Spec: Laptop Seller Evidence, Verification, and Simulated Fulfillment (Verifund)

## 1. Purpose, scope, and core principles

This document is the canonical specification for the evidence a laptop seller must provide in Verifund, how that evidence is verified, how simulated fulfillment demonstrates the workflow, and how evidence contributes to **seller payout eligibility**.

It consolidates and supersedes the overlapping guidance in:
- `docs/superpowers/specs/seller-evidence-for-laptop.md`
- `docs/superpowers/specs/verifund-laptop-seller-evidence-and-simulated-fulfillment.md`
- `docs/superpowers/specs/seller-evidence-requirements.md`

### 1.1 Core principles

1. **Unbroken, verifiable chronological chain:** payout decisions must be supported by a machine-verifiable transaction record linking `product listing → product identity → product condition → packaging → shipment → delivery → buyer inspection/dispute → payout decision`.
2. **Submission ≠ verification ≠ payout authorization:** an uploaded file is not approved evidence; passed delivery is not proof of the correct item or condition; verified evidence does not by itself move money unless all release conditions are satisfied.
3. **Serial number as central identity anchor:** the laptop serial number is the primary reference connecting listing/agreement, seller evidence, packaging, carrier/shipment context, and buyer inspection across the transaction.
4. **Carrier provides facts; policy decides release:** carrier/tracking events are inputs. The release policy engine makes eligibility decisions after considering all applicable evidence and outcomes.
5. **Deterministic policy controls funds:** automated checks and LLM agents may gather, validate, summarize, or triage evidence, but **deterministic policy checks and authorized settlement services control payout/refund/settlement actions. An LLM must never independently release funds.**
6. **Do not overclaim evidence:** every evidence type has limits; the system must record source, confidence, findings, and review state rather than treating any single artifact as conclusive proof.

### 1.2 What Verifund must be able to establish

Before authorizing seller payout, Verifund should be able to answer:

1. **What was sold?** Make, model, configuration, and unique serial number are recorded and tied to the agreement.
2. **What condition was promised?** Seller description and declared defects are recorded before shipment as the baseline.
3. **Does the laptop match the agreement?** Specifications and relevant functional/condition claims satisfy agreed requirements (or an approved adjustment exists).
4. **Was the same laptop packaged?** Product identity is connected to packaging evidence with continuity.
5. **Was the package actually handed to a carrier?** A shipping label is not proof of carrier acceptance.
6. **Was the package delivered?** Delivery is supported by carrier events and, where required, proof of delivery/signature.
7. **Did the buyer receive what was agreed?** Buyer inspection/acceptance/claim/dispute outcome is resolved per policy.
8. **Can payout be released?** All applicable release conditions are satisfied with no unresolved blocking issue, restriction, or unreconciled settlement risk.

### 1.3 Scope and configurability

Exact requirements are **generated from** the transaction agreement, product category, transaction value, shipping method, destination/delivery risk, seller risk profile, and Verifund policy. A high-value laptop generally requires stronger identity, shipping, and delivery evidence than a low-value accessory. Thresholds and mandatory flags shown in examples (e.g. insurance, signature) are policy-configurable unless fixed by agreement.

---

## 2. Evidence statuses and requirement completion (normative)

### 2.1 Status model

Use explicit statuses; do not treat file presence as approval.

| Status | Meaning |
|---|---|
| `NOT_SUBMITTED` | The seller (or required party) has not supplied the required evidence. |
| `SUBMITTED` | Evidence has been uploaded/recorded but has not yet been checked. |
| `PROCESSING` | Automated or manual verification is in progress. |
| `VERIFIED` | The evidence passed the applicable checks for the requirement. |
| `REJECTED` | The evidence failed a check or is unusable (e.g. unreadable, mismatched, incomplete). |
| `NEEDS_REVIEW` | Automated checks are inconclusive or high-impact/ambiguous; a human decision is required. |
| `WAIVED` | An authorized policy decision waived the requirement, with a recorded reason and approver/context. |

### 2.2 Completion and history rules

- A requirement is **complete** only when its verification outcome is recorded and acceptable per policy (typically `VERIFIED`, or `WAIVED` where authorized). `SUBMITTED`/`PROCESSING` are not complete.
- Store **submission metadata and artifacts separately from verification results/findings** and from final policy decisions.
- **Preserve history:** do not overwrite historical evidence on replacement. Create a new evidence submission/verification record linked to the same requirement and retain originals, hashes, timestamps, reviewers, and reasons.
- Failed checks must be **explainable** (which field/item failed, why, and the next action/remediation).

---

## 3. Evidence chain by stage

### 3.1 Stage 1 — Deal creation: identity and condition baseline (pre-shipment)

Recorded before fulfillment activation/payout eligibility progresses; later evidence is compared against this baseline.

#### 3.1.1 Laptop serial number (central identity)
- **Seller provides:** full serial number, manufacturer/model, clear photo of physical serial label (where present), and serial from system information where available.
- **Why:** primary identity reference; enables detection/investigation of substitution or wrong-device claims.
- **Verification:** OCR/extract from label photo; compare to entered value and system-info record (where available); optional OEM/warranty lookup where supported; flag unreadable, inconsistent, duplicated, or suspicious values.
- **Release implication:** missing or mismatched/conflicting serial identity should normally **block deal activation/fulfillment progression**. A reviewer may resolve OCR/readability issues but must not silently accept conflicting device identities.
- **Limitations:** lookup availability varies; OCR can be uncertain (`NEEDS_REVIEW` when appropriate).

#### 3.1.2 Multi-angle product-condition photographs (baseline)
- **Seller provides:** clear photos (e.g. front/screen, back/top, left/right sides & ports, keyboard/trackpad, underside, serial label, screen powered on where practical) and disclosure of visible defects (scratches, dents, cracks, marks, damaged ports, missing keys, etc.).
- **Why:** establishes pre-shipment visual condition (“as described”) for comparison against buyer inspection.
- **Verification:** check required views present/clear; consistency with declared model/identity; image analysis for visible damage/inconsistencies as signal; store original file, timestamps, transaction/seller IDs, cryptographic hash, and audit metadata; compare to buyer images if a condition dispute arises.
- **Limitations:** photos do **not** prove liveness, non-manipulation, or that the photographed device is the one ultimately placed in/shipped in the package. Trusted capture, short-lived challenges, provenance/integrity checks, and continuity evidence increase confidence but no single photo is conclusive.

#### 3.1.3 Transaction-specific provenance/challenge photograph
- **Seller provides:** photo of the laptop displaying a unique, one-time, short-lived Verifund code generated for the specific transaction (used once, expires).
- **Why:** reduces reuse of stock/old/other-transaction images.
- **Verification:** generate challenge; validate extracted code matches active challenge for the transaction; enforce expiry/single-use; store image, hash, and submission metadata.
- **Limitations:** reduces reuse risk but does **not** independently prove genuine live capture or eliminate manipulation. Stronger assurance may require in-app/trusted capture and integrity checks.

#### 3.1.4 Hardware specifications and diagnostics
- **Seller provides:** actual configuration and supporting evidence (manufacturer/model, CPU, RAM, storage capacity/type, GPU, OS/activation where relevant, battery health/cycles where available, display/other agreed features) via system info and/or diagnostic reports.
- **Why:** cosmetic match does not guarantee agreed configuration or battery/feature compliance.
- **Verification:** compare each value to the agreement; validate required fields/formats; prefer structured/trusted diagnostic reports over screenshots where possible; flag material mismatches for correction or review.
- **Limitations:** screenshots can be edited/manipulated. Record evidence source and confidence; do not label a screenshot alone as independently verified hardware truth.

#### 3.1.5 Structured condition and functionality declaration
- **Seller provides:** schema-validated declaration covering (as applicable) overall cosmetic condition and known defects; battery health/cycles; power-on/boot; screen, keyboard, trackpad, webcam, speakers, microphone, Wi‑Fi, Bluetooth, ports; included accessories/charger; BIOS/firmware password status; MDM/enrollment or organizational management; activation/device-lock status; OS activation; previous repairs/replacement parts; warranty/remaining coverage; and any condition explicitly promised in the listing/agreement.
- **Why:** critical restrictions (locks, MDM, activation, missing accessories/licenses) may not be visible in photos.
- **Verification:** validate completeness/required fields; compare to listing/agreement; require supporting evidence for materially value/usability-affecting fields; route conflicting/high-risk declarations to review.
- **Limitations:** declaration is a **seller assertion, not independent proof**; corroborate with available diagnostics/inspection evidence where possible.

### 3.2 Stage 2 — Packaging and shipment submission (fulfillment)

Objective: connect the **identified** laptop to the **package** and to a carrier-accepted shipment.

#### 3.2.1 Packaging photographs (identity-to-shipment continuity)
- **Seller provides (recommended/typical set):**
  - Laptop immediately before sealing (serial visible where practical) / laptop inside protective packaging before sealing.
  - Relevant accessories/protective materials where applicable.
  - Sealed package photo, including shipping label if attached and any tamper-evident seal.
  - (Policy may require) unit + box + label in one photo with serial visible to tie device to shipment.
- **Why:** creates continuity between the baseline device and the dispatched package/label.
- **Verification:** clarity and transaction association; compare visible product/serial details to baseline records where possible; validate label corresponds to shipment record; store hashes/timestamps/metadata.
- **Limitations:** a photo beside/open box is weaker continuity than clearly inside box; neither proves contents remained unchanged after capture, nor that the carrier accepted that package.

#### 3.2.2 Packaging and shipment metadata
- **Record:** transaction ID, seller ID, package identifier (if used), carrier, tracking number, shipping service/method, shipment date, destination confirmation appropriate to privacy policy, declared package weight (if available), expected delivery date.
- **Verification:** tracking number must be associated with the correct transaction. A seller-entered tracking number is **not carrier-confirmed** until checked against a carrier source or the designated (simulated) carrier service.

#### 3.2.3 Shipping insurance (policy-driven)
- **Evidence/record:** coverage/declared value, policy reference, covered risks/exclusions when available.
- **Why:** shifts/supports carrier-loss risk handling and records value; may be required above policy thresholds.
- **Verification — distinguish states (not equivalent):** seller claims insured; insurance purchased; carrier/insurer confirms coverage; claim filed/paid. Apply configurable category/value/shipping-method policy (e.g. require confirmed coverage above a threshold).
- **Limitations:** declared/purchased is not confirmed coverage.

#### 3.2.4 Carrier pickup/acceptance weight (supporting signal)
- **Record:** carrier-reported acceptance/pickup weight when supplied.
- **Why:** anomaly detection (e.g. implausible/empty-box indicators).
- **Verification:** compare to expected package weight with configurable tolerance; flag significant differences for review.
- **Limitations:** **supporting evidence only** — does not prove correct laptop contents.

### 3.3 Stage 3 — Shipment and delivery verification

Verification is driven by carrier facts (or simulated carrier facts); **seller must not be able to mark delivery as complete**.

#### 3.3.1 Carrier tracking and acceptance events
Track and preserve original events, timestamps, and references. Distinguish key states (examples):

| Event | Meaning |
|---|---|
| `LABEL_CREATED` | Label exists; carrier may not yet have the package (**not** proof of dispatch/acceptance). |
| `PICKED_UP` | Carrier accepted/collected the package (carrier custody/acceptance signal). |
| `IN_TRANSIT` | Moving through carrier network. |
| `OUT_FOR_DELIVERY` | On delivery route. |
| `DELIVERED` / `DELIVERED_SIGNED` | Delivered (optionally with signature/equivalent confirmation per carrier/policy). |
| `DELIVERY_EXCEPTION` | Delivery problem/exception reported. |
| `RETURN_TO_SENDER` | Package being returned. |

**Rule:** label creation alone must not satisfy shipment/dispatch requirements.

#### 3.3.2 Proof of delivery (PoD)
- **Collect where supported/required:** delivery timestamp, tracking number, delivery status, recipient name/reference (subject to privacy rules), signature or signature reference, carrier PoD document/event reference, delivery location info if provided.
- **Why:** supports that carrier reports delivery to destination; signature may be required for higher-value/risk shipments per policy.
- **Limitations:** delivery scan/signature does **not** prove correct laptop inside or promised condition — buyer inspection and identity/condition checks remain necessary.

#### 3.3.3 Delivery weight (optional corroboration)
- Compare carrier delivery weight to pickup weight when available; material unexplained differences may trigger investigation. Not mandatory if carrier does not supply it.

### 3.4 Stage 4 — Buyer inspection and dispute handling

Delivery does not equal acceptance.

#### 3.4.1 Inspection window and buyer actions
- **Policy default:** **48-hour buyer inspection window** (as defined by the transaction agreement/scenario policy), applied consistently unless the agreement specifies otherwise.
- **Sandbox/demo override:** the inspection window **MAY be compressed** via configuration (e.g. minutes/hours) to allow full lifecycle demonstration and automated tests; the canonical policy intent remains 48 hours.
- **Buyer may:** accept; report mismatch/defect; submit photos/video/diagnostic results; open a dispute; request/agree to partial settlement where parties and policy permit.

#### 3.4.2 Buyer evidence and comparisons
- **Serial confirmation:** buyer photos received device serial; compare to seller/baseline record. A verified mismatch should **suspend automatic payout** and open investigation (consider submission error and other explanations; do not assume intent without review).
- **Condition photos/video:** compare to pre-shipment baseline; distinguish previously disclosed defects from new/undisclosed damage where evidence supports it (image comparison supports but does not replace human review when ambiguous).
- **Functionality checks (proportionate/risk-based):** power-on/boot, BIOS/firmware access where appropriate, OS startup, CPU/RAM/storage/GPU, battery/charging, display, keyboard/trackpad, Wi‑Fi/Bluetooth, webcam/mic/speakers, ports/charger, and lock/MDM/activation restrictions as relevant.

#### 3.4.3 Dispute handling principles
- Assemble an **evidence timeline** (baseline, packaging, carrier acceptance/events/weights, delivery/PoD, inspection submissions) and resolve under agreement/policy.
- **Do not auto-decide from a single artifact or signal** (one image, one weight). Route ambiguous, contradictory, or high-impact cases to `NEEDS_REVIEW`/human review.
- Example outcomes (policy-dependent): seller-favorable when chain and investigation support seller position; buyer-favorable when credible evidence shows material mismatch/undisclosed defect or nonconforming delivery attributable per policy; **partial settlement** only with required authorization, recorded allocation/reason/approvals, and auditable balance handling.

---

## 4. Payment, ledger, and settlement model (canonical)

### 4.1 Funds flow (separate payout model)

**Intended flow:** buyer pays into Verifund’s configured (sandbox) merchant account → Verifund records amount in an **internal ledger as funds held for the transaction** → fulfillment and verification occur → inspection/disputes resolve → **separate seller payout** is authorized and executed via provider → provider confirms → ledger reconciled.

- **Seller evidence authorizes seller payout (and/or refund/settlement actions per policy), not the buyer’s initial payment capture.**
- Do **not** conflate this with an authorization-then-capture-on-delivery model without redesigning states, provider operations, and assertions.
- Do **not** claim regulated escrow or a specific provider custody arrangement unless separately confirmed with the payment provider and appropriate legal/compliance review. This spec describes a **Verifund-controlled settlement workflow with an internal ledger** (and sandbox simulation), not a production-approved custody guarantee.

### 4.2 Suggested transaction states

Primary flow:

`PAYMENT_CONFIRMED → FUNDS_HELD_IN_LEDGER → FULFILLMENT_SUBMITTED → FULFILLMENT_VERIFIED → INSPECTION_PENDING → PAYOUT_AUTHORIZED → PAYOUT_COMPLETED`

Additional/exception states (as applicable): `EVIDENCE_REJECTED`, `FULFILLMENT_BLOCKED`, `DELIVERY_EXCEPTION`, `DISPUTE_OPEN`, `PAYOUT_SUSPENDED`, `REFUND_PENDING`, `REFUND_COMPLETED`, `PARTIAL_SETTLEMENT_PENDING`, `PARTIAL_SETTLEMENT_COMPLETED`.

**Rules:** an open dispute suspends automatic payout until resolved. Delivery timeout/exception triggers the cancellation/refund/investigation path defined by agreement and policy. **Delivery alone must never satisfy all payout conditions.**

### 4.3 Payout authorization conditions (all applicable)

Authorize seller payout only when:

1. **Product identity verified:** delivered/received device matches agreed identity (including serial where required).
2. **Product compliance verified:** specifications and declared/observed condition satisfy the agreement, or an approved adjustment is recorded.
3. **Seller fulfillment verified:** required packaging, carrier acceptance, shipment, and delivery evidence (and PoD/signature/weight/insurance as required) passed.
4. **Buyer inspection resolved:** buyer accepted, inspection period expired under agreement without a blocking claim, or dispute resolved per policy.
5. **No unresolved blocking issue:** no open dispute, material evidence inconsistency, policy violation, or payment/provider restriction.
6. **Settlement approved:** amount/recipient valid and eligible under applicable provider arrangement and internal controls.

### 4.4 Mapping from capture/void-style language (reconciliation)

Some prior/demo language describes outcomes as capture/void/partial-capture. Under this canonical (ledger + separate payout) model, interpret/map as:

| Prior phrasing (non-canonical for this flow) | Canonical meaning |
|---|---|
| `VERDICT_PASS → CAPTURED` / funds released on delivery | Evidence/inspection allow **`PAYOUT_AUTHORIZED` → `PAYOUT_COMPLETED`** from ledger-held funds (provider-confirmed). |
| `VOIDED` / buyer never charged (auth-capture framing) | **No seller payout**; apply policy outcome such as `REFUND_PENDING/COMPLETED` or ledger release/cancellation as appropriate; no payout to seller. |
| `PARTIALLY_CAPTURED` | **`PARTIAL_SETTLEMENT_PENDING/COMPLETED`** with agreed allocation, authorized amounts, and provider-confirmed refund/payout as applicable. |
| “Assert capture/void/refund via provider” | Assert **ledger state + provider payout/refund/transaction records** agree with machine state (idempotent, reconciled). |

### 4.5 Settlement operations and integrity
- Payout/refund operations **MUST be idempotent** (retries/webhooks must not create duplicate payouts or inconsistent ledger effects).
- Verify/authenticate provider events per current provider requirements.
- Reconcile internal transaction/settlement records with provider-confirmed events.

---

## 5. Simulated fulfillment (deterministic, labeled)

Simulation must behave like the real workflow (same requirements, checks, and state transitions) while clearly identifying all generated evidence and carrier events as **simulated/test data**.

### 5.1 Principles
- **Label simulation data:** fixtures, generated diagnostics/challenge composites, mock carrier events, and simulated signatures/PoD are test artifacts and must not be presented as genuine real-world proof.
- **Mock carrier provides facts; policy decides release:** carrier simulation feeds events/weights/PoD refs; it must not directly trigger payout.
- **Deterministic and auditable:** scenarios are replayable with consistent event histories/timestamps (scenario clock or controlled fixtures).
- **Sandbox configuration levers:** `mode: sandbox` routes plugins/verifiers to fixtures/mocks; `inspection_window` may be compressed for fast runs while **48-hour remains the policy default**.

### 5.2 Suggested fixture layout (illustrative)

```text
fixtures/
└── laptop/
    ├── product/        (front, back, sides, keyboard, screen, serial-number, etc.)
    ├── provenance/     (transaction-challenge/provenance image - simulated composite labeled as such)
    ├── specifications/ (system-info, hardware-report.json, battery-report.json)
    ├── packaging/      (laptop-inside-box, sealed-box, label views)
    ├── delivery/       (proof-of-delivery.json, delivery-signature ref/image)
    └── disputes/       (empty-box, different-serial, damaged-laptop, dead-laptop, etc.)
```

Use genuine sample images only where licensing permits; use fictional serials/IDs/diagnostics/carrier events.

### 5.3 Mock carrier (illustrative)

A simple mock service (e.g. FastAPI, Postman mock) can expose tracking by scenario key, e.g. `GET /tracking/SANDBOX-{scenario}` returning ordered events with timestamps, weights, and signature/PoD references as applicable. Example event progression: `LABEL_CREATED` (if modeled) → `PICKED_UP` → `IN_TRANSIT` → `OUT_FOR_DELIVERY` → `DELIVERED_SIGNED` or exception/timeout behavior per scenario. Event times should be consistent with the scenario clock/test data.

### 5.4 Deterministic scenarios

#### Required 7-scenario set

| Scenario | Simulated behavior (summary) | Expected policy/settlement outcome (canonical) |
|---|---|---|
| `happy_path` | All required seller/baseline evidence verified; carrier acceptance and delivery confirmed (signature/PoD as required); buyer accepts or inspection expires without blocking claim. | Requirements satisfied → **`PAYOUT_AUTHORIZED` → `PAYOUT_COMPLETED`**; ledger/provider records reconcile. |
| `specs_mismatch` | Submitted specs/diagnostics (e.g. RAM/CPU/storage/GPU/battery/other agreed attribute) differ materially from agreement. | Block progression/fulfillment approval or payout; `EVIDENCE_REJECTED`/remediation or `NEEDS_REVIEW` per policy; **no payout**. |
| `packing_photo_missing` | Required packaging evidence absent/unusable. | Fulfillment incomplete (`NOT_SUBMITTED`/`REJECTED`); remediation/notification required; **no payout**. |
| `weight_anomaly` | Carrier-reported weight differs materially from expected (configurable tolerance). | Flag for investigation/`NEEDS_REVIEW` (and/or `PAYOUT_SUSPENDED` if applicable); **weight alone not proof of fraud** and not sole basis for final adverse decision; **no automatic payout** while unresolved. |
| `never_delivers` | No confirmed delivery within policy (stays in transit, exception, or return) triggering timeout/exception path. | Apply agreement timeout/cancellation/refund/investigation process; **no seller payout**; `REFUND_*` or other terminal handling per policy and ledger/provider reconciliation. |
| `dispute_buyer_wins` | Credible buyer-supported material mismatch/undisclosed defect or nonconforming outcome per investigation/policy. | Suspend/deny seller payout (fully or partially as applicable); resolve via refund/adjustment/`PARTIAL_SETTLEMENT_*` per authorized policy; auditable resolution. |
| `dispute_seller_wins` | Evidence timeline and investigation support seller position; required conditions otherwise satisfied. | Dispute resolved for seller; proceed to payout **only if all other release conditions met** → `PAYOUT_AUTHORIZED/COMPLETED` as applicable. |

#### Minimum demo slice (4 scenarios)
For fast demos/hackathon validation, the minimum subset is: **`happy_path`, `never_delivers`, `dispute_seller_wins`, `dispute_buyer_wins`**. These should be pre-seedable/replayable (e.g. scenario runner or `/scenarios` replay) and, where feasible, paired with at least one live sandbox checkout flow.

### 5.5 Illustrative sandbox `verification_config` (electronics, non-normative example)

```json
{
  "category": "electronics",
  "verification_method": "TRACKING_CONFIRMATION",
  "mode": "sandbox",
  "scenario": "happy_path",
  "requires": {
    "serial_at_deal_creation": true,
    "provenance_photo": true,
    "packing_photo_serial_visible": true,
    "insurance_min_value": 500,
    "signature_required": true
  },
  "inspection_window_hours": 2,
  "auto_release_hours": 1,
  "revision_rounds": 0,
  "carrier": {
    "base_url": "https://mock-carrier.example",
    "tracking_format": "SANDBOX-{scenario}"
  }
}
```

**Note:** `inspection_window_hours` here demonstrates a **sandbox override** (compressed); the canonical policy default is 48 hours. `auto_release_hours` and any auto-actions must still respect inspection/dispute resolution and all payout authorization conditions.

---

## 6. Seller Fulfillment Workspace (requirements-oriented)

The workspace must make it obvious **what is required, what is submitted, what is verified, and what blocks payout** — organized around requirements, not unrestricted uploads.

### 6.1 Required views/sections
1. **Product identity:** serial number, serial-label evidence, manufacturer/model, provenance/challenge evidence, identity verification status/findings.
2. **Product condition:** multi-angle photos, specs/diagnostics, battery/lock-related evidence, condition & functionality declaration, statuses/findings.
3. **Packaging:** inside-box/accessories evidence, sealed-box/label evidence, insurance evidence (if required), continuity status.
4. **Shipping and delivery:** carrier, tracking, acceptance/pickup confirmation, weights (if available), delivery/PoD/signature status, exceptions.
5. **Verification and settlement:** per-requirement statuses, outstanding/remediation actions, buyer inspection status, dispute status, **payout eligibility and payout/settlement status** with clear explanation (e.g. “Buyer payment confirmed and held in ledger; payout not yet authorized because …”).

Each requirement should track its submissions, verification attempts/results, and remediation guidance. The Seller Agent may proactively notify sellers of missing/rejected/unclear evidence with specific next actions.

---

## 7. Backend architecture, data, and safeguards (normative)

### 7.1 Separation of concerns

```text
Seller Agent / Fulfillment Workspace
                -> Evidence API
                -> Evidence Service (metadata, object storage refs, hashes, audit history)
                -> Verification Engine (identity / product / fulfillment checks)
                -> Dispute Service (claims, evidence, decisions/resolution)
                -> Release Policy Engine (agreement, inspection, disputes, payout eligibility)
                -> Settlement Coordinator (provider payout/refund, webhook confirmation, reconciliation)
                -> Internal Ledger
```

**Responsibilities (illustrative):** `evidence_service` (ingest/store metadata/hash/history), validators (type/size/required fields/completeness), `identity_verifier`, `product_verifier`, `fulfillment_verifier`, `dispute_service`, `release_policy_engine`, `settlement_coordinator`. Long-running orchestration/retries/human-review checkpoints may use a workflow engine (e.g. LangGraph), but **state transitions, policy enforcement, and payout authorization remain deterministic backend responsibilities**.

### 7.2 Storage and data model
- **Artifacts:** store photos/videos/documents in object storage; store metadata, hashes, relationships, statuses, and references in the database (e.g. Neon PostgreSQL).
- **Per-submission records should retain:** evidence/submission ID, transaction/requirement/task IDs, actor (seller/buyer/reviewer), requirement type, object-storage reference, original filename/media type/size, cryptographic hash, submission timestamp, source and **simulation flag**, verification status/findings, reviewer identity/decision where applicable.
- **Suggested entities/tables (illustrative):** `fulfillment_tasks`, `fulfillment_requirements`, `evidence_submissions`, `evidence_verifications`, `product_identifiers`, `shipment_records`, `carrier_events`, `delivery_confirmations`, `inspection_records`, `disputes`, `settlement_records` (and ledger/transaction records as needed). Use constraints/transactions to prevent duplicate payout authorization.

### 7.3 Safeguards and operational requirements
- **Immutable, explainable trail:** preserve originals, hashes, timestamps, verification attempts, findings, and reviewer decisions.
- **Confidence and review:** treat OCR/CV/automated extraction as uncertain where appropriate; route ambiguous/high-impact results to `NEEDS_REVIEW`.
- **No overclaiming:** record what evidence proves/does not prove; do not infer contents/condition/liveness from insufficient signals.
- **Idempotency and correctness:** idempotent payout/refund/settlement handling; no duplicate disbursement on retries/webhooks.
- **Provider integration integrity:** authenticated/signed provider events per requirements; reconcile ledger with provider-confirmed outcomes.
- **Timeouts and exceptions:** explicit, policy-defined handling for missing scans, failed delivery, returns, expired inspections, and unresolved disputes.
- **Privacy:** collect/store only necessary delivery/recipient/personal information with appropriate access controls and retention.
- **Simulation hygiene:** all mock/fixture/generated artifacts clearly labeled; deterministic, replayable, auditable.

---

## 8. Recommended baseline policy (configurable)

Baseline examples (generate final set from agreement/policy):

| Evidence / check | Typical baseline | Notes |
|---|---|---|
| Serial number + label photo | Mandatory | OCR/record comparison; blocks on conflict/missing per policy. |
| Multi-angle condition photos + disclosure | Mandatory | Baseline for disputes; integrity/continuity limits apply. |
| Provenance/challenge photo | Mandatory (risk/policy-based) | Anti-reuse signal; not liveness proof. |
| Specs/diagnostics vs agreement | Mandatory | Prefer structured/trusted reports; record confidence/source. |
| Condition/functionality declaration (incl. locks/MDM/activation, accessories, repairs, warranty as relevant) | Mandatory | Assertion; schema-validated and corroborated where possible. |
| Battery report | When material/promised | Compare to declared/agreed threshold. |
| Packaging photos (identity/inside/sealed/label as required) | Mandatory for shipped flow | Continuity evidence; not carrier acceptance/contents proof. |
| Tracking + carrier acceptance (`PICKED_UP`) | Mandatory for shipped orders | `LABEL_CREATED` insufficient. |
| Pickup/delivery weight checks | Policy-dependent / optional | Anomaly signal only. |
| Shipping insurance evidence | Policy-dependent | Confirmed coverage state required when mandated. |
| Proof of delivery (and signature for high-value/risk when required) | Policy-dependent / often mandatory | Carrier fact; not contents/condition proof. |
| Buyer inspection resolution (when required) | Mandatory per agreement/policy | Acceptance/expiry-without-blocking-claim or dispute resolution. |

**Final requirement set must be agreement-driven** (e.g. promised GPU, battery threshold, warranty, accessories become explicit, verifiable requirements).

---

## 9. End-to-end payout decision (summary)

```text
Is laptop identity verified (and consistent)?
  -> No: block / remediate / NEEDS_REVIEW
  -> Yes: do specs & condition satisfy agreement (or approved adjustment)?
      -> No: block / dispute / adjust per policy
      -> Yes: are packaging & shipment (incl. carrier acceptance) requirements verified?
          -> No: fulfillment incomplete
          -> Yes: is delivery confirmed as required?
              -> No: wait / investigate / timeout-exception policy
              -> Yes: is buyer inspection resolved per policy?
                  -> No: payout pending
                  -> Yes: any unresolved dispute or blocking policy/provider restriction?
                      -> Yes: suspend/deny/adjust per policy
                      -> No: PAYOUT_AUTHORIZED -> provider-confirmed PAYOUT_COMPLETED (idempotent, reconciled)
```

This decision must be produced from a complete, auditable transaction record and reflected consistently in machine state, ledger, and provider-confirmed settlement outcomes.