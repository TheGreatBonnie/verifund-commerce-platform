# Seller-Order Evidence Fulfillment Alignment — Implementation Plan

**Companion spec:** `docs/superpowers/specs/2026-11-12-seller-order-evidence-fulfillment-alignment-design.md`  
**Status:** Draft plan (for review)  
**Date:** 2026-11-12  
**Scope mode:** Full Phase 1 (D-A6) — catalog/offers/claims, templates, generator, agreement snapshot/policy binding, end-to-end unit-bound fulfillment, and validated Northwind importer, with recompute-all migration (D-A7/D-A10) and all-categories/no-fallback coverage (D-A11).

> **Planning note:** This is an architectural, cross-domain change. Execute in small, verifiable increments behind stable interfaces; keep TCP/settlement invariants green throughout. Do not begin implementation until the spec and this plan are approved.

## 0. Preconditions and gating (must be satisfied before/within Phase 1)

| Gate | Requirement | Rationale |
|---|---|---|
| G1 In-scope category list | Produce definitive list of all categories that will be importable/transactable in Phase 1 (from Northwind + any existing flows). | D-A11: every in-scope category needs a complete template. |
| G2 Template completeness | Author and validate fulfillment policy templates for every category in G1 (condition variants as applicable, e.g. refurbished/new). No fallback. | D-A11. |
| G3 Migration dry-run spec | Define dry-run diff schema, storage/report location, and acceptance thresholds/signoff process. | D-A10 safeguards. |
| G4 Terminal-state recompute rules | Decide and document exact recompute behavior for `RELEASED/REFUNDED/CANCELED/FAILED` and dispute-resolved/terminal records (financial facts immutable; audit presentation defined). | D-A10, ledger/payout integrity. |
| G5 Backup/rollback runbook | Document and rehearse backup, restore, abort criteria, and idempotent rerun steps. | D-A10. |

**Exit if not met:** if G1/G2 cannot be completed, reduce Phase 1 in-scope categories explicitly (documented amendment) rather than introducing fallback behavior.

## 1. Workstreams and dependency order

1. **WS1 — Domain foundations:** taxonomy, catalog (product/spec/media/variant), offers/claims/pricing/fulfillment profile, policy templates storage/versioning.
2. **WS2 — Inventory units:** `inventory_item`, reservations, SKU coexistence, access controls.
3. **WS3 — Requirement generator & policy binding:** template resolution, deterministic generation from claims/terms/unit/category/condition, agreement snapshot integration.
4. **WS4 — Agreement/TCP integration:** snapshot extensions (product/offer/variant/unit, claim snapshot, policy version, generated requirements), immutability/versioning.
5. **WS5 — Fulfillment/evidence/verification binding:** unit-linked evidence/provenance/shipment/inspection/dispute; evaluation against generated snapshots.
6. **WS6 — Northwind importer:** validated, repeatable pipeline + conflict resolution/reporting.
7. **WS7 — Migration (recompute-all):** dry-run, diff, apply with safeguards, terminal-state handling.
8. **WS8 — Agent/API/console alignment:** contracts and surfaces for normalized entities and generated requirements.
9. **WS9 — Verification, hardening, rollout:** tests, observability, audit, performance/idempotency checks.

**Indicative sequencing:** (G1–G5, WS1, WS2) → WS3 → WS4 → WS5 → WS6 → WS7 → WS8 polish → WS9/rollout. Some parallelization possible (e.g. WS6 importer against WS1 models; template authoring in parallel with schema), but generator/snapshot/verification semantics must stabilize before migration apply.

## 2. Detailed tasks

### WS1 — Catalog, offers, claims, and policy templates (D-A3, D-A4, D-A8, D-A11)

**2.1 Taxonomy and catalog schema**
- Add normalized `product_categories` (hierarchy/slug/IDs) and seed canonical taxonomy for G1 categories.
- Add `products`, `product_specifications`, `product_media`, `product_variants` with tenancy/audit/timestamps and constraints.
- Define read/write repository/service interfaces in a dedicated catalog domain/module (shared boundary consumable by TCP/agreements and authorized seller APIs).

**2.2 Offers and claims**
- Add `product_offers`, `offer_pricing_policies`, `offer_fulfillment_profiles`, `offer_warranty_options`.
- Add `offer_claims` with `source`, `verification_status`, operator/value/unit, provenance refs; enforce seller cannot set independently verified status (service/permission guard).
- Model claim thresholds so generator can consume agreed values (e.g. battery health %, RAM/storage/GPU, charger/accessories, condition/defects).

**2.3 Fulfillment policy templates**
- Add `fulfillment_policy_templates` (category/condition scope, version, status, requirement definitions: owner/kind/source/stage/required/min_items/required_views/accepted_formats/check specs/parameter rules).
- **Seed templates from current laptop fulfillment** (D-A1): port existing requirement IDs/semantics where preserved (serial, provenance, product_photos/views, condition_declaration, hardware, battery, warranty, packaging, shipping, insurance conditionality, carrier_acceptance, delivery_confirmation, invoice) and checks/blocker logic into template form.
- Author complete templates for all other G1 categories (D-A11). Validate: required fields, resolvable checks, no invented/unverifiable assertions, deterministic parameterization.
- Implement template versioning/publishing and validation CLI/check.

**Deliverables:** migrations/schema (additive, idempotent style consistent with repo), domain models/services, template definitions/fixtures, validation tooling.

### WS2 — Inventory units and reservations (D-A2, D-A6)

**2.4 Physical units**
- Add `inventory_items` (offer/variant linkage, seller/org, serial_number with restricted access, condition type/grade, unit_attributes: battery health/cycles, cosmetic/known functional defects, accessories/inclusions, timestamps/status).
- Add `inventory_reservations` tied to transaction/agreement and inventory item (or SKU where allowed), with reserve/release/consume states.
- Preserve SKU-quantity inventory path for non-serialized/new goods; enforce unit-required path for in-scope refurbished/serialized categories.

**2.5 Binding rules**
- Define and enforce invariants: agreement for unit-required orders must reference specific `inventory_item` + reservation; evidence/provenance/inspection/dispute records link to unit where applicable.
- Implement access control for serial/unit-sensitive data.

**Deliverables:** schema/models/services, reservation lifecycle, policy checks, tests for unit-required vs SKU-only flows.

### WS3 — Requirement generator and threshold resolution (D-A1, D-A3, D-A11)

**2.6 Generator**
- Implement deterministic generator: inputs (category/condition, product/variant specs, unit attributes, offer/claim snapshot, buyer requirements, negotiated terms, template version) → immutable generated requirement catalog with concrete thresholds, applicability/conditional flags, stage/coverage metadata, and generation hash/audit payload.
- **Source thresholds from agreed claims/terms** (not hardcoded constants except explicit policy rules); compute conditional requirements (e.g. insurance) from agreement values.
- Ensure compatibility mapping for existing laptop requirement IDs/semantics so verification logic generalizes cleanly.

**2.7 Validation and failure behavior (no fallback)**
- Generator must fail explicitly with actionable errors when: template missing/incomplete for category/condition, required inputs missing, or claim/term cannot resolve a required threshold. No default template, no invented checks.
- Add template-coverage and generator contract tests across all G1 categories.

**Deliverables:** generator module/service, pure/deterministic test suite, golden fixtures per category/condition.

### WS4 — Agreement snapshots and TCP integration (D-A1, D-A6, D-A7, D-A8)

**2.8 Agreement model/snapshot extensions**
- Extend agreement/terms/version snapshot structures to include: `product_id`, `product_offer_id`, `variant_id`, `inventory_item_id`(s), reservation ref, offer/claim snapshot, negotiated terms, `fulfillment_policy_template_id/version`, generated requirement catalog, and generation metadata/hash.
- Ensure snapshots are immutable post-creation; catalog/offer/policy changes do not mutate existing agreements.
- Integrate generator invocation at agreement creation/acceptance (or defined snapshot point) within TCP/agreements authority boundary.

**2.9 Projection and compatibility surfaces**
- Update projections/read models to expose generated, agreement-bound requirements (and unit/policy metadata) to verification, console, and agents.
- Maintain stable requirement identifiers and status/action-owner semantics expected by existing verification/console where possible.

**Deliverables:** schema/model changes, snapshot/write path, read models/projections, agreement API updates.

### WS5 — Fulfillment, evidence, and verification binding (D-A1, D-A2, D-A6)

**2.10 Unit-linked fulfillment flow**
- Thread `inventory_item_id`/reservation context through evidence submissions, declarations, provenance challenges/verifications, shipment/delivery records, inspection records, and disputes where applicable.
- Enforce unit-specific checks (e.g. serial match to reserved unit, unit condition/battery attributes vs agreed thresholds) in deterministic evaluation.
- Keep carrier/system authority, reference-evidence semantics, corroboration-only buyer delivery, timeout/review rules, and blocker/action-owner derivation intact.

**2.11 Evaluation against generated snapshots**
- Refactor policy evaluation to consume **agreement-snapshotted generated requirements** (with template version) as the source of truth; preserve scan/provenance/coverage/rollup behavior.
- Ensure idempotency, CAS/state-machine, and audit logging remain correct with new linkages.

**Deliverables:** service/policy/repository/API updates, updated scenarios/fixtures including unit-bound laptop cases, regression coverage.

### WS6 — Northwind importer (D-A4, D-A6, D-A9, D-A11)

**2.12 Importer pipeline**
- Implement repeatable CLI/module: parse `northwind.yaml` → validate/normalize → emit normalized entities (seller, mandate, commercial/pricing/warranty/return/delivery policies, categories, products/variants/spec placeholders, offers/claims/pricing/fulfillment/inventory including unit stubs where required) → load/upsert with report.
- **Conflict handling (explicit, no silent coercion):** reconcile mandate vs 36‑mo add-ons per defined rule; normalize taxonomy; convert `reviews` to int; transform `sustainability_certified` to claim+provenance; classify duplicates; flag missing specs/condition/unit attrs and suspect stock.
- Idempotent/rerunnable; produce structured report (counts, warnings, errors, resolutions).

**2.13 Fixtures and parity**
- Generate/update dev/test fixtures from importer output; verify negotiation-relevant fields (floors/ladders/mandate bounds) preserve intended behavior.
- Validate imported catalog satisfies G1/G2 template coverage for in-scope categories.

**Deliverables:** importer code, mapping spec (inline/docs), validation rules, sample reports, updated templates/fixtures.

### WS7 — Migration: recompute all with safeguards (D-A7, D-A10)

**2.14 Dry-run and diff**
- Build migration tool to enumerate all transactions/agreements, resolve applicable templates/inputs, generate proposed snapshots/requirements, recompute verification projections, and produce diff report (per-transaction and aggregate): requirement/threshold/status/rollup/blocker changes, errors/unresolvable cases.
- Store/report diffs for review; define signoff gate.

**2.15 Apply, safeguards, and terminal-state handling**
- Implement backup/restore hooks or documented procedure integration; enforce abort criteria on diff/error thresholds.
- Apply recompute in controlled, idempotent batches respecting CAS/state and in-flight operation safety (scans, reconciler, payouts, webhooks).
- Record migration audit events/markers and linkage to policy versions/generation hashes.
- **Terminal-state rules (must implement as specified in G4):** preserve ledger/payout/financial outcomes and immutable audit facts; apply documented recompute/audit-presentation policy for released/refunded/canceled/failed/dispute-terminal records.

**2.16 Post-migration verification**
- Re-run dry-run comparison on migrated state (expect convergence per rules), validate integrity constraints, and spot-check sampled transactions per state/category.

**Deliverables:** migration CLI/jobs, diff report artifacts, runbook, audit records, verification results.

### WS8 — Agent, API, and console alignment (D-A8 and target UX boundaries)

**2.17 Seller/buyer/ops APIs**
- Expose catalog/offer/claim/unit and policy/template metadata via authorized APIs; ensure claim verification status is read-only to sellers.
- Update negotiation/acceptance and fulfillment endpoints to carry unit selection/reservation refs and agreement-bound requirement IDs/metadata.
- Align seller-agent evidence outbox and settlement/fulfillment flows to normalized, unit/requirement-aware contracts.

**2.18 Console**
- Update seller (and relevant ops/buyer) views to show: product/offer/claims with provenance & verification status, unit-bound context, generated requirements with agreed thresholds/policy version, and existing blockers/action ownership.
- Keep catalog media distinct from fulfillment evidence; do not present declared claims as verified.

**Deliverables:** API schema/handler updates, TypeScript/contract types, minimal UI changes to surface authoritative data.

### WS9 — Testing, observability, and rollout

**2.19 Test plan**
- **Unit:** generator determinism/threshold sourcing, template validation for all G1 categories, claim-status guards, unit-binding/reservation rules, importer normalization.
- **Integration:** end-to-end unit-bound refurbished laptop flow (imported/normalized data → offer/claims → negotiation/acceptance → agreement snapshot with generated requirements → evidence/provenance/shipment/delivery/inspection/dispute → verification/release), plus representative flows for other G1 categories.
- **Migration:** dry-run diffs, apply/idempotency, terminal-state handling, rollback rehearsal (in test env).
- **Regression:** existing fulfillment scenarios (7 laptop scenarios where applicable), ledger/idempotency/webhook/CAS/payout, carrier authority/timeouts, agreement immutability.

**2.20 Observability and audit**
- Structured logs/metrics for generation/template-coverage failures, import validation, migration progress/diffs/errors, unit-binding violations.
- Audit events for claim changes, template versions, generation snapshots, migration actions, and verification/release decisions.

**2.21 Rollout**
- Staged rollout: schema + read paths → dual-write/shadow generation (if useful) → snapshot cutover for new agreements → importer load → migration dry-run/signoff → migration apply → cleanup/monitoring.
- Feature flags or configuration gates where needed to control generator/snapshot source during transition (internal), while honoring "no fallback" completion criteria.

## 3. Category/template checklist (to be completed under G1/G2)

Create and track a table in-repo (or as a companion artifact) listing for each in-scope category:
- category_id/taxonomy mapping, condition variants, template_id/version, owner/reviewer, validation status, sample/golden case, known gaps.

**Plan requirement:** all rows must be `validated/complete` before Phase 1 completion; unresolved rows require scope reduction decision.

## 4. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Recompute-all alters historical meaning (D-A10) | Audit/trust confusion, state/rollup changes | Mandatory dry-run diff + signoff, backup/rollback, explicit terminal-state rules, migration audit markers |
| All-categories/no-fallback (D-A11) blocks progress | Incomplete Phase 1 | Early G1/G2 gating, template authoring track, explicit scope-reduction path (no silent fallback) |
| Large Phase 1 slice (D-A6) | Integration/regression risk | Incremental workstreams, deterministic generator tests, preserve existing scenarios/invariants, staged rollout |
| Unit binding complexity in refurbished flows | Data/linkage errors | Strong invariants/constraints, reservation lifecycle, targeted end-to-end tests |
| Northwind conflicts/ambiguity | Bad normalized data | Repeatable importer with warnings/errors and explicit resolution rules; no silent inference |
| Seller-agent/console contract drift | Broken workflows | Contract-first updates, compatibility shims where needed, integration tests |

## 5. Definition of done (Phase 1)

- [ ] G1–G5 satisfied and documented.
- [ ] Catalog/offer/claim, variant/unit/reservation, and policy template domains implemented and validated.
- [ ] Deterministic generator produces agreement-bound, policy-versioned requirements from claims/terms/unit/context for all in-scope categories; no fallback/invented checks.
- [ ] Agreement snapshots immutable and include product/offer/unit/claim/policy-version/generated requirements.
- [ ] Unit-bound fulfillment/evidence/verification operational for in-scope refurbished/serialized flows.
- [ ] Northwind importer repeatable/validated with conflict handling and reports; normalized data loaded.
- [ ] All existing transactions recomputed with dry-run, safeguards, and terminal-state handling per G4; audit trail complete.
- [ ] Agent/API/console aligned to authoritative entities and generated requirements.
- [ ] Tests (unit/integration/migration/regression) pass; observability/audit in place; rollout completed per runbook.

## 6. Suggested first execution sequence (post-approval)

1. Finalize G1 (in-scope categories) and G4 (terminal-state recompute rules) in a short decision addendum.
2. Land WS1/WS2 schemas + models (additive) and WS1.3 laptop template seed derived from current implementation.
3. Implement WS3 generator with laptop golden cases; wire WS4 snapshot generation for new agreements.
4. Bind WS5 verification/evidence to generated snapshots and unit context (laptop path), keeping regressions green.
5. Complete remaining G2 templates + WS6 importer for G1 categories.
6. Execute WS7 dry-run → signoff → apply with safeguards; complete WS8/WS9 hardening and rollout verification.  
