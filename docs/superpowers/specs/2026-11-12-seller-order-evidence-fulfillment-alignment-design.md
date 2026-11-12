# Seller-Order Evidence Fulfillment Alignment: Design Spec

**Status:** Draft (user-confirmed direction for spec/plan)  
**Date:** 2026-11-12  
**Inputs (analyzed):**
- `docs/superpowers/specs/verifund-product-structure.md`
- `docs/superpowers/specs/analysis-of-northwind-product-catalog.md`
- Current implementation baseline (esp. `docs/superpowers/specs/2026-11-12-laptop-evidence-fulfillment-design.md`, agreements/control-plane/commerce/seller-agent modules)

**Purpose:** Align this project to a model where seller-order evidence fulfillment is driven by canonical products, seller offers/claims, immutable transaction agreements, unit-specific fulfillment context, and policy-generated, agreement-bound requirements—while preserving Transaction Control Plane (TCP) authority and existing fulfillment/settlement invariants.

---

## 1. Problem statement

The project now has a strong transaction-time evidence/fulfillment core for laptop flows (category/terms-driven requirement projection, deterministic policy evaluation, declarations, provenance, carrier-authoritative shipment/delivery, inspections/disputes, blockers, release gating). However, the **commercial/object model** is not yet aligned with the target architecture:

- Canonical **Product**, seller **Product Offer**, and **Transaction Agreement** are not fully separated first-class domains.
- Seller claims lack an explicit, first-class provenance/verification-status model distinct from TCP verification outcomes.
- Fulfillment requirements are not yet generated as **transaction-specific, immutable artifacts** from category/condition templates + agreed claims/buyer requirements + negotiated terms + applicable policy version.
- Refurbished/unit-identified goods lack first-class **variant/physical-unit inventory** bound to evidence and reservations.
- `docs/templates/northwind.yaml` remains a conflated source (seller/profile/policy/mandate + product + offer + inventory/negotiation) with known normalization/conflict issues.

The result: evidence fulfillment is increasingly correct at the TCP/transaction layer, but not yet fully traceable from "what was listed/offered/agreed for which specific unit" to "what must be proven and was proven."

## 2. Goals and non-goals

### Goals
1. Separate and normalize **Product Catalog**, **Product Offers/Claims**, **Agreement snapshots**, **Fulfillment Policy templates**, and **Inventory (including physical units)** as first-class, auditable entities.
2. Make fulfillment requirements **generated, agreement-bound, and immutable** (policy template/version + agreed thresholds/claims/terms + unit context), not ad-hoc or mutable from catalog changes.
3. Bind refurbished/serialized laptop fulfillment to the **specific physical unit** (identity/condition/battery/serial/defects) across reservation, evidence, provenance, shipment, inspection, and dispute.
4. Provide a **repeatable, validated Northwind importer** that transforms `northwind.yaml` into normalized entities while preserving negotiation behavior intent.
5. Preserve TCP authority, deterministic/non-fakeable verification semantics, carrier/system authority rules, and money/ledger/payout safety properties.
6. Deliver as a single, coherent Phase 1 slice per confirmed scope (see Decisions), with explicit migration and compatibility handling.

### Non-goals (for this phase)
- New external integrations (OEM lookups, CV damage/similarity scoring, real malware scanning, S3/presigned storage, production broker/outbox) beyond existing adapter boundaries.
- Microservice extraction.
- Independent seller-agent runtime re-architecture beyond interfaces needed to consume/publish normalized catalog/offer/agreement/fulfillment data.
- UI redesign beyond surfaces required to expose the new authoritative data (detailed UX polish is a follow-on once contracts stabilize).

## 3. Confirmed decisions (grilling Q1–Q9 + follow-ups)

| ID | Decision | Implication |
|---|---|---|
| D-A1 | Use current laptop/category-catalog fulfillment as the initial `fulfillment_policy_template` + requirement-generator seed (refactor to agreement-bound generated requirements), not a parallel system. | Generalize existing requirement/check/rollup semantics; avoid dual truth. |
| D-A2 | Refurbished/used laptops (and similar serialized goods) require `inventory_item` (per-unit serial/condition/battery/defects) + reservation for evidence fulfillment; SKU-quantity inventory remains for non-serialized/new goods. | Unit linkage becomes mandatory in the target laptop fulfillment path. |
| D-A3 | `offer_claims` (source, verification_status, thresholds) are canonical inputs to transaction requirement thresholds; seller agents cannot mark claims independently verified. | Declarations ≠ verification; TCP/verification governs status transitions. |
| D-A4 | Keep `northwind.yaml` as import/fixture source transformed by a validated importer into normalized entities (not runtime catalog shape). | Import pipeline + validation/warnings/fixes required. |
| D-A5 | Next concrete deliverable is a written spec + phased implementation plan before code changes. | This document + companion plan. |
| D-A6 | **Phase 1 includes all:** catalog/offers/claims, templates, generator, agreement snapshot/policy-version binding, **end-to-end unit-bound fulfillment (inventory_item + reservation + unit-linked evidence/provenance/inspection)**, and validated Northwind importer. | Large, coherent slice; sequencing/risk controls critical. |
| D-A7 | **Migrate all** existing transactions to generated, policy-versioned requirements (not legacy-only for new agreements). | Requires migration framework and audit handling (see D-A10). |
| D-A8 | Canonical catalog, offers/claims, and fulfillment policy templates live in a dedicated catalog/policy domain (shared schema/service boundary) read by TCP/agreements for snapshotting; not embedded in seller-agent local store. | Clear ownership; seller-agent uses authorized APIs. |
| D-A9 | Northwind importer is a repeatable, validated pipeline (CLI/module) with reported fixes/warnings. | Auditable, rerunnable import. |
| D-A10 | Migration mode is **recompute now** (not behavior-preserving derivation) but **with safeguards**: pre-migration dry-run/report, backup/rollback plan, and explicit handling for terminal-state records (released/refunded/canceled/disputed). | Accepted risk of changed historical/in-flight statuses/thresholds/blockers/audit meaning, mitigated procedurally. |
| D-A11 | **All categories now, no fallback:** require template-backed generated requirements for every category in Phase 1 scope; no default/fallback template that invents unverifiable checks. | Phase 1 completion is gated on complete, validated category/condition templates for all in-scope categories (or explicit scope reduction before implementation). |

### Risk notes (accepted/constrained)
- **D-A10:** Recomputing all transactions can alter requirement outcomes and audit interpretation. Safeguards are mandatory; released/terminal records need special, documented treatment (e.g. snapshot-before/after, read-only historical audit preservation, or controlled recompute rules) defined in the migration spec.
- **D-A11:** "No fallback" means unmapped/incomplete categories block generation. This requires authoring/validating templates for every category that Phase 1 will import or allow to transact; otherwise Phase 1 cannot be declared complete without narrowing in-scope categories.

## 4. Current-state baseline (summary)

- **Commerce contracts/protocol:** `packages/commerce_core/commerce_core/contracts.py` (`Mandate/RFQ`, `Offer`, `CounterOffer/AcceptOffer`, `PurchaseOrderRequest`, `Order/Fulfillment`) — negotiation/offer-order oriented.
- **Seller catalog template:** `docs/templates/northwind.yaml` conflates seller profile, mandate, defaults, negotiation policy, and product listings/offers/inventory.
- **Seller store:** `apps/seller_agent/seller_agent/store.py` (SQLite) for inventory, offers, orders, settlement tokens, evidence outbox—operational, not normalized catalog.
- **Agreements:** `verifund_control_plane/agreements/*` provide agreement records/versions/decisions/snapshots and hash/version semantics; TCP owns transaction lifecycle.
- **Fulfillment/evidence (recent):** laptop category catalog in terms/policy, deterministic evaluation, declarations/provenance, carrier-authoritative shipment/delivery (system reference evidence), inspection/dispute handling, blockers/action ownership, reconciler sweeps—primarily terms/category-driven at runtime.
- **Known gap:** target entities (`product_offers`, `offer_claims`, `fulfillment_policy_templates`, `product_variants`, `inventory_items`) are described in docs/recommendations but not implemented as first-class runtime domains.

## 5. Target architecture

### 5.1 Domain separation and authority
| Domain | Responsibility | Authority/notes |
|---|---|---|
| **Product Catalog** | Canonical products, categories/taxonomy, specifications, media, variants | Source of "what the item/model/config is"; no txn/settlement state |
| **Marketplace / Offers** | Seller product offers, pricing/negotiation policy refs, condition/grade, warranty/returns, fulfillment profile, availability, **offer claims** | Seller-declared claims are unverified by default; seller cannot self-verify |
| **Inventory** | SKU stock and **physical inventory units** + reservations | Unit is required for refurbished/serialized fulfillment binding |
| **Fulfillment Policy** | Category/condition (and context) policy templates, versioned | Reusable definitions; no per-transaction mutable truth |
| **Agreement Management** | Negotiated/accepted agreements, immutable snapshots (offer/claims/unit/terms + policy version + generated requirements) | TCP/agreements create authoritative snapshots |
| **Evidence & Verification** | Evidence intake, declarations, provenance, validation/verification, findings | TCP evaluates against agreement-snapshotted requirements |
| **Transaction Control Plane** | Lifecycle, shipment/delivery/inspection/dispute states, release eligibility, settlement coordination | Sole authority for verification outcomes, eligibility, and execution gating |

### 5.2 End-to-end flow (target)
1. **Catalog & offer:** Product/variant defined; seller publishes offer with claims (unverified), pricing/fulfillment terms, and inventory (SKU and/or unit).
2. **Discovery/negotiation:** Buyer/seller agents discover/compare/negotiate; claims/thresholds and fulfillment conditions become agreed terms.
3. **Agreement creation/acceptance:** TCP snapshots accepted offer/claims/terms, selected unit/reservation (when required), and **fulfillment policy template version(s)**; **requirement generator** produces immutable, transaction-specific requirements with agreed thresholds.
4. **Funding:** Payment confirmed/funds held per existing flow.
5. **Fulfillment:** Seller (and system/carrier) submit evidence/references/declarations/provenance bound to agreement + requirement + unit where applicable.
6. **Verification:** Deterministic checks + adapter extraction + provenance comparison + carrier/system facts produce requirement results, blockers/action owners, rollup.
7. **Delivery/inspection/dispute:** Carrier-authoritative delivery facts; inspection window; disputes/cases as applicable.
8. **Release/settlement:** Release eligibility evaluated against blockers/policy; payout executed via existing settlement path.

## 6. Data model changes (logical)

> Exact table/column names and SQL DDL are specified in the implementation plan; this section defines required entities, relationships, and invariants.

### 6.1 Product Catalog
- `product_categories`: id, name, slug, parent_id, metadata; normalized taxonomy.
- `products`: id, name, brand, model, category_id, description, product_type, intended_use, status, timestamps/tenancy/audit.
- `product_specifications`: id, product_id (or variant_id), key, value, unit/type, source.
- `product_media`: id, product_id, media_type, uri/storage_key, is_primary, source (catalog/manufacturer/seller), hash/metadata.
- `product_variants`: id, product_id, sku/config attributes (CPU/RAM/storage/color/etc.), status.

**Invariant:** no transaction/fulfillment/settlement state on catalog records.

### 6.2 Offers, claims, and policies
- `product_offers`: id, product_id (+variant), seller_id/org, seller_sku, status/version, condition type/grade/disclosure, pricing summary refs, warranty/returns terms, availability, timestamps.
- `offer_pricing_policies`: list/original/initial/floor, currency, concession ladder, validity.
- `offer_fulfillment_profiles`: handling time, shipping method, tracking/insurance required, delivery estimates.
- `offer_warranty_options`: duration, additional price, constraints.
- `offer_claims`: id, offer_id, key, operator, value, unit, source, verification_status (`unverified|verified|disputed|inconclusive`), provenance/evidence refs, timestamps.

**Invariant:** seller actions may create/update claims as declared; only TCP/verification workflows may set verified/disputed outcomes.

### 6.3 Inventory and physical units
- `inventory_items` (physical units): id, offer_id/variant_id, seller/org, serial_number (restricted), condition type/grade, unit_attributes (battery_health_pct, battery_cycle_count, cosmetic_defects, known_functional_defects, included accessories), availability_status, timestamps.
- `inventory_reservations`: id, inventory_item_id (or SKU reservation), transaction/agreement ref, status, reserved_at/released_at.
- SKU-level stock may remain (e.g. existing seller inventory) for non-serialized goods; unit records are mandatory when D-A2 applies.

**Invariant:** for in-scope refurbished/serialized laptop orders, the agreement and fulfillment context must reference a specific `inventory_item` (and reservation) that evidence/verification binds to.

### 6.4 Fulfillment policy templates and generation
- `fulfillment_policy_templates`: id, category_id (+optional condition/product-type scope), version, status, requirement definitions (id, title, owner, kind, source, stage, required, min_items, required_views, accepted_formats, check specs/parameterization rules).
- **Generator input:** category/condition, product/variant specs, selected unit attributes, offer claims, buyer requirements, negotiated/agreed terms, policy template version.
- **Generator output (immutable per agreement):** resolved requirement catalog with concrete thresholds/expected values, applicability/conditionality, and policy version metadata.

**Invariant (D-A11):** every in-scope category must resolve to a complete, validated template-backed requirement set; no invented checks and no fallback template.

### 6.5 Agreements and snapshots (extensions)
- Extend agreement/terms snapshot to capture: accepted `product_id`, `product_offer_id`, `variant_id`, `inventory_item_id`(s)/reservation, offer/claim snapshot, negotiated terms, `fulfillment_policy_template_id`(s)+`version`, and **generated requirement catalog** (+ generation inputs/hash for audit).
- Preserve immutability: catalog/offer/policy edits do not mutate existing agreement snapshots.

### 6.6 Evidence/verification binding (extensions)
- Evidence submissions/declarations/provenance records carry linkage to `agreement_version/hash`, requirement, and `inventory_item_id` where applicable; maintain existing idempotency/dedup semantics.
- Verification results store evaluation against the **agreement-snapshotted generated requirements** (and recompute/migration writes updated snapshots per D-A7/D-A10 rules).

## 7. Requirement generation and verification semantics

1. **Seed from current laptop fulfillment:** port existing laptop requirement definitions/checks (including provenance, declarations, multi-view coverage, carrier/system-owned requirements, blocker/action-owner semantics) into versioned policy templates and a deterministic generator (D-A1).
2. **Threshold sourcing:** resolve check thresholds/expected values from agreed claims/terms (e.g. battery %, RAM/storage/GPU, warranty/returns/insurance, tracking/carrier match) rather than fixed catalog constants, except where explicitly policy-defined (D-A3).
3. **Conditionality:** requirement applicability (e.g. insurance) computed from agreement/declared values at generation/snapshot time and recorded immutably.
4. **Evaluation:** retain deterministic comparison logic, scan/provenance handling, reference/system evidence authority, coverage rules (`min_items`, `required_views`), and rollup/blocker derivation; extend matching to unit-bound attributes.
5. **All-categories coverage:** author and validate templates for all in-scope categories imported/transactable in Phase 1; generation must fail with explicit validation errors for missing/incomplete template coverage (no silent gaps).

## 8. Northwind import (repeatable, validated)

### 8.1 Pipeline behavior
- Input: `docs/templates/northwind.yaml` (and future seller YAMLs of same shape).
- Output: normalized records for seller profile, categories/taxonomy mapping, seller mandate + commercial/pricing/warranty/return/delivery policies, products/variants/spec placeholders, offers/claims/pricing/fulfillment options, and inventory (SKU and/or unit stubs as applicable).
- Mode: CLI/module, idempotent where possible, with machine-readable report (created/updated/skipped, warnings, validation errors).

### 8.2 Required validations/normalizations
- Normalize categories to canonical IDs (resolve case/name inconsistencies, e.g. `Laptop`/`laptop`/`MacBook`).
- **Reconcile conflicts:** mandate max warranty (24 mo in template) vs 36‑mo add-ons—produce explicit resolution (constrain options, adjust mandate, or reject with actionable error) per recorded policy; never import contradictory authority silently.
- Convert `reviews` to integer; convert `sustainability_certified` boolean to claim with provenance/verification_status.
- Preserve negotiation behavior inputs (floor/initial/concession ladder) as pricing policy; do not embed as product identity.
- Detect repeated names/SKUs and classify (variant, distinct offer, or duplicate) via deterministic rules + flagged ambiguity.
- Do not infer missing specs/condition/unit attributes; represent unknowns explicitly (null/unset) and surface as import warnings.
- Treat uniform demo stock/incoming values as flagged unless confirmed.

## 9. Migration strategy (D-A7, D-A10)

### 9.1 Recompute-all with safeguards
- **Pre-migration dry-run:** generate proposed policy-versioned requirements/snapshots and recomputed verification projections for all transactions; produce diff report (by transaction/state/category: requirement set changes, threshold changes, status/rollup/blocker changes).
- **Backup/rollback:** documented DB/artifact backup and restore procedure; migration runnable in a controlled window with abort criteria.
- **Execution:** recompute and persist updated agreement/requirement snapshots and verification results per defined rules; record migration event/audit markers (source, policy versions, timestamp/actor, diff summary ref).
- **Terminal-state handling:** explicitly define recompute behavior for `RELEASED`, `REFUNDED`, `CANCELED`, `FAILED`, and `DISPUTE_*`/resolved states to protect financial/audit integrity (e.g. preserve immutable financial outcomes and historical audit trail while attaching recomputed analytical view, or other explicitly chosen rule documented in plan). No silent mutation of ledger/payout facts.

### 9.2 Compatibility
- Despite "migrate all", implementation must include guards to ensure in-flight operations (uploads, scans, reconciler, release, payout webhooks/idempotency) remain consistent during/after migration (locking/order, idempotent steps, state/CAS respect).

## 10. API, agent, and boundary implications

- **Catalog/Offers/Policies:** read APIs for discovery/comparison (buyer/console/agents); authorized write APIs for seller-managed products/offers/claims/inventory (scoped/tenant-safe). Claims writes cannot set independent verification.
- **Agreements:** TCP issues authoritative snapshots and generated requirements; negotiation/acceptance flows supply agreed terms/claims/unit selection.
- **Fulfillment:** evidence/provenance/shipment/inspection/dispute APIs accept unit linkage and agreement-bound requirement IDs; seller agent/outbox aligned to requirement IDs and unit context.
- **Access control:** serial numbers and unit-sensitive attributes subject to least-privilege access.

## 11. Observability, audit, and integrity

- Audit events for: catalog/offer/claim changes, policy template versioning, requirement generation inputs/outputs/hash, agreement snapshot creation, migration dry-run/apply, recompute diffs, and verification/release decisions.
- Metrics/logs for generation failures (especially template-coverage failures per D-A11), import validation errors, migration anomalies, and unit-binding violations.
- Idempotency and CAS semantics preserved for all mutating fulfillment/settlement operations.

## 12. Testing and verification strategy (spec-level)

- **Unit/contract:** requirement generator determinism and threshold sourcing from claims/terms; template validation (all in-scope categories complete); claim verification-status guards; unit-binding constraints.
- **Integration:** end-to-end laptop refurbished flow from normalized/imported offer+unit → negotiated agreement snapshot → unit-bound evidence/provenance/shipment/delivery/inspection/dispute → verification/release eligibility.
- **Migration:** dry-run diff generation, recompute correctness per defined rules, safeguards for terminal states, rollback exercise.
- **Import:** Northwind transform correctness, conflict resolutions, warning/error reporting, repeatability/idempotency.
- **Regression:** existing money/ledger/idempotency/webhook/CAS/payout semantics and carrier-authority/timeout rules unchanged.

## 13. Acceptance criteria

1. First-class catalog/offer/claim, policy template, and inventory-unit entities exist and are used by agreement snapshotting and fulfillment.
2. New agreements contain immutable, policy-versioned, generated requirements with thresholds derived from agreed claims/terms and (where required) unit context.
3. Refurbished/serialized laptop fulfillment is unit-bound end-to-end (reservation, evidence/provenance, inspection/dispute linkage).
4. Northwind data can be imported via repeatable validated pipeline into normalized entities with documented conflict handling/warnings.
5. All in-scope categories have complete template-backed generation (no fallback, no invented checks); generation fails explicitly on missing coverage.
6. All existing transactions are recomputed to policy-versioned requirements with completed dry-run report, safeguards applied, and documented terminal-state handling.
7. TCP authority boundaries and existing fulfillment/settlement safety invariants hold; regression and new-scenario tests pass per plan.

## 14. Open implementation details (to resolve in plan)

- Concrete storage layout and module/package boundaries for the catalog/policy domain within this monorepo (while respecting D-A8 ownership).
- Canonical category taxonomy and the definitive in-scope category list for Phase 1 (required by D-A11).
- Exact recompute rules for terminal financial states and audit presentation (D-A10).
- Seller-agent API/contract changes for publishing offers/claims and consuming agreement-bound requirements.
- Console contract/API updates for product/offer/claim/unit and generated-requirement views.

---
*Self-review notes: decisions D-A1–D-A11 recorded; recompute and no-fallback risks explicitly constrained; invariants and TCP authority stated; implementation-detail items enumerated rather than assumed.*  
