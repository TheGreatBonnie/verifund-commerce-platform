# Seller Fulfillment Workspace

The seller-facing `/seller/*` workspace drives the seller leg of the
requirement-driven evidence flow (design spec
`docs/superpowers/specs/2026-11-04-verifund-seller-evidence-target-design.md`
§3.9–§3.10, plan `docs/superpowers/plans/2026-11-04-verifund-seller-evidence-target-implementation.md`
Tasks 23–27). No mock data: every screen reads a scoped control-plane
endpoint with the seller's bearer token.

## Access (invitation exchange)

1. Ops issues a single-use invitation:
   `POST /ops/transactions/{id}/issue-invitation` (Ops-authenticated).
2. The seller opens `/fulfillment/access/{token}`. The page renders a
   server-side exchange form; confirming calls
   `POST /fulfillment/access/{token}`, which validates expiry, seller
   ownership, and transaction match on the server, burns the invitation,
   and returns a seller bearer token (`txn:read` + `evidence:write`).
3. The console stores the token **server-side** in the HttpOnly cookie
   `verifund_seller_sessions` (a per-transaction token map) and redirects
   to `/seller/fulfillment/{transaction_id}`. The bearer token never
   reaches the browser; server components and route handlers attach it.

Without a valid session, `/seller/*` renders an access gate that points the
seller back to their invitation link.

## Routes (all under `/seller`, auth-gated layout)

| Route | Contract source | What it shows |
| --- | --- | --- |
| `/seller/dashboard` | `GET /seller/transactions` | 4 stat cards, priority tasks (open seller actions) |
| `/seller/orders` | `GET /seller/transactions?state=` | order table with lifecycle status |
| `/seller/fulfillment` | `GET /seller/transactions` | task table: next action, evidence progress, status |
| `/seller/fulfillment/{id}` | `GET /seller/transactions/{id}` + `GET /seller/agreements/{id}` | overview: product, agreement version, payment state, order value, deadline, verified count, requirement list, read-only agreement summary, dispute claim |
| `/seller/fulfillment/{id}/evidence` | same + `GET /seller/transactions/{id}/evidence` | evidence checklist: requirement cards with submission attempts |
| `/seller/fulfillment/{id}/activity` | `GET /seller/transactions/{id}/events` | chronological event timeline |
| `/seller/evidence` | `GET /seller/evidence` | cross-transaction library (filterable by `requirement_id`) |
| `/seller/payouts` | `GET /seller/payouts` | pending/paid/failed payout totals and per-transaction states |

`/seller/settings` is intentionally absent (non-normative, no contract).
Buyer identity is deliberately not shown (privacy decision, spec §3.10.6).

## Order evidence (upload)

- Addressed by **`requirement_id`** (legacy `kind` is rejected with 422).
  The upload modal prefills the selected requirement and renders formats
  from its `accepted_formats` (`image/jpeg`, `image/png`, `image/webp`,
  video `mp4`/`quicktime`/`webm`, `text/csv`, `text/plain`,
  `application/pdf`, `application/json`).
- **`source=reference`** requirements (e.g. shipping) get a tracking/URL
  input (`reference` + `reference_type=tracking|url`), not a file picker.
  Reference artifacts are first-class submissions (`artifact_type=reference`).
- The form collects **`captured_at`** (optional) and a description
  (`note`). The server returns a submission receipt
  (`submission_id`, `evidence_id`, `receipt_id`, `attempt`,
  `scan_status`); the UI never invents an id.
- Only seller-owned requirements are uploadable; system-owned
  `delivery_confirmation` is buyer-attested/carrier-corroborated.
- Uploads are allowed in `FUNDED`, `FULFILLMENT_PENDING`,
  `VERIFICATION_PENDING`, and `REMEDIATION_REQUIRED`.
  `DISPUTE_OPEN` accepts dispute counter-evidence only
  (`POST /seller/transactions/{id}/dispute-evidence`, file-only,
  `purpose=dispute`, ignored by verification/rollup).

Console proxies (Bearer attached server-side):

- `POST /api/seller/transactions/[id]/evidence`
- `POST /api/seller/transactions/[id]/dispute-evidence`
- `GET /api/seller/transactions/[id]/evidence/[evidenceId]` (download stream)

## Status vocabulary (single map, spec §3.9.4)

`apps/console/lib/seller-status.ts` is the only badge map. Transaction
state → seller label; requirement status → badge; **no `REJECTED`
evidence badge** (failed requirement = "Action required").

| Backend state | Seller badge |
| --- | --- |
| `FUNDED` | Fulfillment required |
| `FULFILLMENT_PENDING` | Evidence required |
| `VERIFICATION_PENDING` | In progress |
| `REMEDIATION_REQUIRED` | Action required |
| `REVIEW_REQUIRED` | Under review |
| `DISPUTE_OPEN` | Dispute open |
| `RELEASE_PERMITTED` | Fulfillment verified |
| `PAYOUT_PENDING` | Payment processing |
| `RELEASED` | Paid |
| `REFUNDED` | Refunded |

Requirement statuses: `not_submitted` → Required, `pending_scan` →
Processing, `review` → Under review, `pass` → Verified, `fail` →
Action required. "Payment processed" reflects capture at/after `FUNDED`;
it never says escrow, and payout states stay distinct from capture.

## Backend contract surface consumed

- `SellerProjection` now carries `agreement_id`, `requirements[]`
  (from `project_requirements(terms)`), `dispute`, and `payout`.
- `GET /seller/agreements/{id}` returns the agreement view + terms
  (including `totals`, `items`, `delivery`, `warranty`, `requirements`)
  for the read-only summary card and "View agreement" anchor.
- List counts (`counts_by_state`) are computed over **all** of the
  seller's transactions, not the returned page.
- Seller-scoped list endpoints reject a `seller_id` query parameter
  (the token's `seller_id` is the only scope key).

## Current limits

- No console "Declare" button — declarations are backend endpoints
  (`POST .../requirements/{id}/declare`); the console surfaces
  `declared_at`/`declared_by` passively.
- Evidence library verification is transaction-level; per-item status
  arrives with per-requirement rollup (submitted/exists patterns only).
- Settings, messaging, and cross-transaction search are out of scope.
