# Buyer Transactions & Fulfillment (Chat-First) — Design Spec

**Date:** 2026-11-12  
**Status:** Draft for review (brainstormed/grilled; decisions locked in-session)  
**Scope:** `apps/console` (buyer workspace UX, routing, proxies, components) and required `apps/verifund_control_plane` buyer read/projection contracts that unblock buyer Transactions/Fulfillment surfaces.  
**Supersedes/adapts:** `docs/superpowers/specs/transactions-and-fulfillment-pages.md` (sample IA/intent), `docs/superpowers/plans/2026-11-12-buyer-transactions-fulfillment-console.md` (earlier console plan that assumed legacy run/deal-room integration).  
**Related:** `docs/superpowers/specs/2026-11-12-laptop-evidence-fulfillment-design.md`, control-plane buyer routes in `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`.

## 1. Goal

Add first-class buyer **Transactions** and **Fulfillment** workspaces in the console, integrated with the **chat-first** buyer experience (`/chat`), while retiring legacy `/runs`, `/agents`, and deal-room surfaces. Transactions present the commercial/financial/agreement record; Fulfillment presents operational progress (requirements, evidence, verification, shipment, inspection, disputes) and buyer fulfillment actions. Fulfillment completion must never be treated as payout authorization; release remains policy/blocker-gated by authoritative control-plane state.

## 2. Context and problem

- **Current state:** buyer settlement/fulfillment UI is embedded in legacy run/deal-room surfaces (`apps/console/app/(console)/runs/**`, `agents/[runId]`, `features/deal-room/**`, `features/runs/**`) and driven by run-scoped buyer-agent APIs (`/api/runs/[runId]/settlement*|stream|trace` via `apps/console/lib/buyer-proxy.ts`). `/chat` (`app/(console)/chat/page.tsx`, `features/chat/*`) is the replacement primary buyer interaction surface.
- **Available fulfillment authority:** control-plane exposes transaction-scoped buyer fulfillment routes at `/buyer/transactions/{transaction_id}/inspection|evidence|dispute|accept|delivery-confirmed` (plus seller/ops surfaces). Console currently has no control-plane buyer fulfillment proxies and no buyer transaction/fulfillment list pages.
- **Sample spec intent:** `transactions-and-fulfillment-pages.md` proposes separate `/transactions` and `/fulfillment` destinations, rich lists/details, cross-links, and a 1:N fulfillment model. This design adopts the separation/cross-link intent but adapts it to chat-first UX, current transaction-scoped fulfillment APIs, and the need for authoritative buyer read/list projections.

## 3. Locked decisions

| # | Decision |
|---|---|
| Q1 | Keep `apps/console/app/api/runs/[runId]/**` buyer-agent proxy route handlers as infrastructure for now; remove only specific handlers proven unused. |
| Q2 | Rewire all entry points that push to `/runs/...` or `/agents/...` (sidebar, CTA, public home, marketplace, etc.) to **`/chat`** as primary; do not keep run/deal-room pages as primary destinations. |
| Q3 | Buyer fulfillment is **1:1 per transaction now** (keyed by `transactionId`), with models/components/routes extensible to 1:N `fulfillmentId` later; do not invent a `fulfillmentId` resource now. |
| Q4 | Transactions/Fulfillment list and overview views are backed by **new authoritative buyer-facing read/list APIs and projections**; do not approximate from run history or partial client-side data. |
| Q5 | **Replace then remove:** add/validate new surfaces and rewired entry points before deleting legacy runs/agents/deal-room/runs-feature UI (then prune unused run APIs with evidence). |
| Q6 | `/transactions` and `/fulfillment` are **first-class `(console)` routes/navigation**, cross-linked and reachable from `/chat`, while `/chat` remains the primary interaction model. |
| Q7 | Fulfillment routes are top-level: `/fulfillment` and `/fulfillment/[transactionId]` (transaction-keyed now), with prominent cross-links to transactions. |
| Q8 | Replace sidebar **Runs** with **Transactions** and **Fulfillment**; rewire agent CTA to `/chat`. |
| Q9 | When removing `/runs` and `/agents/[runId]`, **return 404s** (no redirects/fallbacks). |
| Q10 | First pass is **dependency-ordered**: deliver/consume authoritative read projections for lists/aggregates/timelines in the same or immediately preceding slice; prioritize authoritative control-plane-backed fulfillment detail/actions (+ minimal transaction linking) and do not fake completeness. |

## 4. Non-goals (this spec)

- Redesigning or replacing `/chat`’s conversational/orchestration model beyond adding deep-links, transaction context, and fulfillment-relevant tool/card integration points.
- Modeling 1:N fulfillment records/`fulfillmentId` as a first-class resource now (Q3); only extensibility is required.
- Exposing seller-only workspace data or controls in buyer surfaces.
- Making the console a source of truth for money movement/release authorization; authoritative policy/blocker evaluation remains in control plane.
- Removing `app/api/runs/**` infrastructure wholesale (Q1) or changing buyer-agent contracts except as needed for verified integration.

## 5. Information architecture and routes

### 5.1 Buyer console routes (new)
| Route | Purpose | Key contents |
|---|---|---|
| `/transactions` | Commercial/financial list and overview | Overview cards/aggregates, filters, transaction list/table, link to detail |
| `/transactions/[transactionId]` | Authoritative commercial record | Header/summary, agreement snapshot & terms, buyer/seller, product & price breakdown, payment, status/timeline, `FulfillmentSummary` with link to `/fulfillment/[transactionId]` |
| `/fulfillment` | Operational list and overview | Overview cards/aggregates, filters, fulfillment list/table with next action, link to detail |
| `/fulfillment/[transactionId]` | Operational fulfillment workspace (1:1 per transaction) | `TransactionReference` link, status/progress, requirements/results, evidence checklist/gallery, verification results, shipment/carrier timeline, inspection panel/actions, buyer evidence upload, dispute/accept/delivery actions, blockers/allowed actions |

All routes live under `apps/console/app/(console)/` and render in the main console shell/navigation (except any existing chat-only shell behavior remains specific to `/chat`). Routes are reachable from sidebar and from `/chat`.

### 5.2 Cross-links (required)
- Transaction detail includes a compact **FulfillmentSummary** (state, blockers/next action, inspection/shipment highlights as available) linking to `/fulfillment/[transactionId]`.
- Fulfillment detail includes a **TransactionReference** (transaction id, agreed amount/status/payment summary as available) linking to `/transactions/[transactionId]`.
- Both surfaces reflect the same authoritative backend state/events; they must not maintain conflicting status.

### 5.3 Legacy routes (removed with 404, Q9)
- `/(console)/runs`, `/(console)/runs/[runId]`, `/(console)/agents/[runId]` are deleted after replacements are validated; requests return 404 with no redirect/fallback.

## 6. Data, authority, and integration

### 6.1 Source-of-truth split
| Domain | Authoritative source | Console integration |
|---|---|---|
| Transaction/fulfillment list summaries, overview aggregates, filters, timelines (buyer projections) | **Control-plane buyer read APIs** (new/extended, Q4) | Console server/client fetch via authenticated control-plane proxies/helpers |
| Inspection, buyer-owned evidence submission, buyer dispute/accept/delivery-confirmation, fulfillment blockers and release-relevant state | **Control-plane** (`/buyer/transactions/{id}/...`) | New console proxies `app/api/buyer/transactions/[id]/*` → control-plane `/buyer/transactions/{id}/*` |
| Run-scoped settlement projection/receipt/artifacts, stream/trace, agent-owned settlement actions (where still used) | **Buyer agent** (`BUYER_API_URL`) | Existing `apps/console/lib/buyer-proxy.ts` and `app/api/runs/[runId]/**` (kept per Q1; use only when run context is known/mapped) |
| Conversational flow and tool orchestration | **`/chat` + buyer/seller agent integrations** | Deep-links to `/transactions`/`/fulfillment`; no dependency on deal-room |

`transaction_id` is the canonical key for new buyer pages and control-plane fulfillment actions. Any `runId ↔ transaction_id` mapping must be explicit and derived from authoritative data when used.

### 6.2 Required buyer read/list contracts (backend dependency, Q4/Q10)
Control plane must provide buyer-scoped, tenancy-enforced read projections sufficient for:
- **Transactions list/overview:** paginated/filterable items with `transaction_id`, product/seller summary, agreed amount/currency, payment status, transaction/settlement status, fulfillment/next-action summary, created/updated dates; aggregate counts for overview cards/filters.
- **Transaction detail:** commercial record including agreement snapshot/terms (or stable reference), parties, line items/price breakdown, payment summary, status/timeline/history, and linked fulfillment summary.
- **Fulfillment list/overview:** paginated/filterable items keyed by `transaction_id` (1:1 now) with operational status, next action, shipment/inspection/issue indicators, and aggregate counts.
- **Fulfillment detail:** requirements and evaluation/results, evidence submissions/verification (buyer-visible), shipment/carrier events/timeline, inspection record/deadline/outcome, disputes, blockers, and `allowed_actions` (or equivalent) for buyer UI gating.

Contracts must be stable, typed, and consistent across list/detail views; pagination, sorting, and filter semantics must be documented. Exact endpoint paths/shapes are defined in the implementation plan and control-plane API changes, but must satisfy these needs without client-side fabrication.

### 6.3 Console proxy routes (new)
| Console route | Method | Upstream (control plane) | Notes |
|---|---|---|---|
| `/api/buyer/transactions/[id]/inspection` | GET | `/buyer/transactions/{id}/inspection` | Inspection record/state |
| `/api/buyer/transactions/[id]/evidence` | POST | `/buyer/transactions/{id}/evidence` | `multipart/form-data` (buyer-owned requirements: `requirement_id`, `view_label`, `agreement_version`, file/reference fields) |
| `/api/buyer/transactions/[id]/dispute` | POST | `/buyer/transactions/{id}/dispute` | JSON claim payload |
| `/api/buyer/transactions/[id]/accept` | POST | `/buyer/transactions/{id}/accept` | Accept/resolve per control-plane contract |
| `/api/buyer/transactions/[id]/delivery-confirmed` | POST | `/buyer/transactions/{id}/delivery-confirmed` | Delivery confirmation per control-plane contract |
| `/api/buyer/transactions` and `/api/buyer/transactions/[id]` (and any list/count subroutes required by the read contract) | GET | buyer read/list/detail projection endpoints defined in the control-plane contract for this feature | Required for list/overview/detail projections (Q4); exact upstream paths must be documented alongside the projection schema |

All proxies: `auth.protect()`/server-derived identity, no client-trusted tenant/buyer IDs, forward only permitted auth/headers, preserve upstream status/errors, no-store, and safe handling for 401/403/404/409/422/415 and network failures.

### 6.4 Error/state semantics
- **404:** not found or not owned/cross-tenant (no existence leak).
- **409:** invalid state/version/hash/idempotency conflict — show actionable conflict/stale-state UI and refetch.
- **422/415/400:** validation/media/view/agreement-version errors — surface field-level/actionable messages.
- **401/403:** unauthenticated/unauthorized.
- Mutations must trigger refetch of authoritative detail/projection (and any dependent list aggregates) so blockers/allowed actions/status stay consistent.

## 7. UI and component architecture

### 7.1 Placement and navigation
- `(console)` layout/sidebar (`components/layout/console-layout.tsx`, `components/layout/sidebar.tsx`) exposes **Transactions** and **Fulfillment** as first-class nav items, replacing **Runs** (Q8). Agent CTA opens `/chat`.
- `/chat` remains the primary interaction surface and provides links/entry points into transaction and fulfillment records when context is available.
- No new buyer fulfillment UX is built in `features/deal-room` or run/agent pages.

### 7.2 Component modules (proposed)
**Shared (`components/buyer/shared/*` or equivalent):** status/state badges, money/date formatting, filter controls, overview stat cards, list/table primitives, empty/loading/error/notice states, blocker & allowed-action presenters, cross-link cards.

**Transactions (`components/buyer/transactions/*`):** `TransactionOverviewCards`, `TransactionFilters`, `TransactionList`, `TransactionHeader`, `TransactionSummary`, `AgreementSummary`, `ProductSummary`, `SellerInformation`, `PriceBreakdown`, `PaymentSummary`, `TransactionTimeline`, `FulfillmentSummary`.

**Fulfillment (`components/buyer/fulfillment/*`):** `FulfillmentOverviewCards`, `FulfillmentFilters`, `FulfillmentList`, `FulfillmentHeader`, `TransactionReference`, `FulfillmentStatus`, `FulfillmentProgress`, `FulfillmentRequirements`, `EvidenceChecklist`, `EvidenceGallery`, `VerificationResults`, `ShipmentTracking`, `CarrierTimeline`, `BuyerInspectionPanel`, `BuyerEvidenceUploadDialog`, `DisputePanel`, `AcceptDeliveryActions`, `FulfillmentActions`.

**Client/data helpers:** `lib/buyer-transaction-api.ts` (or equivalent), typed models in `lib/buyer-transaction-types.ts`/`lib/types.ts`, and control-plane proxy helper(s) in `lib/control-plane.ts` or `lib/buyer-control-plane.ts`.

### 7.3 Behavior rules
- Gate actions by authoritative `allowed_actions`/state/blockers; never infer payout eligibility client-side.
- Evidence upload uses multipart and respects buyer-owned requirement/view/agreement-version constraints.
- Components are transaction-keyed now and structured so a future `fulfillmentId` can be introduced without rewriting domain boundaries.
- Reuse/extract presentation logic from legacy deal-room components only as chat/workspace-agnostic code; do not import `features/deal-room`.

## 8. Legacy removal

### 8.1 Remove after replacement/validation (Q5)
- Pages: `app/(console)/runs/page.tsx`, `app/(console)/runs/[runId]/page.tsx`, `app/(console)/agents/[runId]/page.tsx`.
- Features/tests: `features/deal-room/**`, `features/runs/**`, `tests/features/deal-room/**` and run/deal-room-only tests.
- Rewired references: sidebar, CTA, public home, marketplace, mode/layout assumptions, and all in-app links to `/runs`/`/agents`.

### 8.2 Keep/prune conditionally (Q1)
- Keep `app/api/runs/**` and buyer-agent proxy infrastructure required by chat or remaining flows; remove only handlers proven unused. Shared settlement/run types remain only while consumers exist.

### 8.3 URL handling (Q9)
- Deleted legacy routes return **404** (no redirects). No primary navigation or in-app link may target removed routes.

## 9. Delivery sequencing (Q10)

1. **Slice A — Contracts & integration foundation:** define/implement buyer read/list/detail projection APIs (Q4) and console control-plane buyer proxy routes/helpers/auth wiring; confirm `transactionId`-keyed fulfillment model.
2. **Slice B — Fulfillment detail/actions (priority):** `/fulfillment/[transactionId]` with inspection, buyer evidence upload, dispute/accept/delivery-confirmation, requirements/evidence/verification/shipment visibility as available, blockers/allowed actions, and minimal `/transactions/[transactionId]` + cross-links.
3. **Slice C — Lists/aggregates/timelines:** `/transactions` and `/fulfillment` list/overview pages and richer detail timelines/cards powered by authoritative read/list APIs (no fabricated completeness).
4. **Slice D — Chat-first rewiring & legacy removal:** chat deep-links/entry points, sidebar/nav/CTA rewiring (Q2/Q8), validation, then delete legacy pages/features/tests (Q5/Q9) and prune unused run APIs (Q1).

Slices may overlap only where dependencies are satisfied; UI must not claim completeness absent authoritative projections.

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Buyer read/list APIs not ready | Treat as blocking for list/aggregate/rich timeline scope (Q4/Q10); deliver/consume in same or preceding slice, ship fulfillment detail/actions first where possible |
| `/chat` or other flows depend on run APIs/deal-room assumptions | Keep `api/runs/**`/shared types until proven unused; map `runId ↔ transaction_id` explicitly; avoid importing deal-room |
| Auth mismatch for control-plane buyer proxies | Align console proxy helper with control-plane buyer auth/tenancy resolution; test 401/403/404 cross-tenant cases |
| Spec vs backend cardinality drift (1:N later) | Keep transaction-keyed interfaces but isolate fulfillment record identity in types/components/data access |
| 404 removal breaks bookmarks/history | Accepted per Q9; mitigate by completing chat-first/navigation rewiring before deletion so in-product paths no longer lead there |

## 11. Verification and acceptance

- **Routes/nav:** `/transactions`, `/transactions/[transactionId]`, `/fulfillment`, `/fulfillment/[transactionId]` exist as first-class console routes, linked from sidebar and reachable from `/chat`, with working cross-links; sidebar shows Transactions/Fulfillment (no Runs); `/runs` and `/agents/[runId]` return 404 after cleanup.
- **Authority and behavior:** fulfillment detail/actions use control-plane buyer proxies and authoritative blockers/allowed actions; mutations refetch and reflect state; fulfillment completion is not presented as payout authorization.
- **Data integrity:** list/overview/aggregate/timeline views render from authoritative buyer read/list APIs (no fabricated completeness); run-scoped buyer-agent data used only when mapped/appropriate.
- **Security/scoping:** server-derived auth, no client-trusted tenant IDs, correct 401/403/404(no-leak)/409/422/415 handling, multipart evidence constraints enforced.
- **Legacy cleanup:** deal-room/runs UI and dead entry points removed per sequence; only proven-unused `api/runs/**` handlers removed.
- **Quality:** console typecheck/lint/build/tests pass for touched areas; targeted integration/manual validation of fulfillment detail actions and page navigation.
