# MarketMesh Console — Production-Ready Frontend Design

**Date:** 2026-10-24
**Status:** Approved design, pending spec review
**Scope:** `apps/console/` (frontend) plus thin console proxy routes to the existing buyer
REST API. No Python/agent changes: the buyer already exposes `GET /api/runs`,
`GET /api/runs/{run_id}`, and `GET /api/runs/{run_id}/trace`. This work consumes them
(Option A: buyer as source of truth).
**Path chosen:** Architectural (multi-page product).

## 1. Purpose

Make the Next.js 15 + CopilotKit console a complete, production-shaped multi-page
product: clean routing, a shared shell, typed UI primitives, extracted feature
modules, server-state caching, tests, accessibility, and production hardening —
while preserving the distinctive visual identity and the existing demo flow.

This is a frontend-only effort. The buyer/registry/seller agents keep their
current APIs. Runs are derived on the client from CopilotKit threads + the
existing trace endpoint.

## 2. Non-goals (inherited from README)

- No multi-tenant authentication, no real payments/fulfillment, no hosted
  registry, no push webhooks.
- No mock data (explicitly excluded by product owner). If revisited later, drop
  fixtures under `features/*/fixtures/` gated by `NEXT_PUBLIC_USE_MOCKS`.
- No new backend endpoints.

## 3. Decisions

| Decision | Choice |
|---|---|
| Scope | B. Multi-page product |
| Run persistence | A. Buyer REST API as source of truth (buyer SQLite `runs` table; console proxies + consumes) |
| Mock data | Excluded |
| App shell | A. Persistent sidebar + global chat drawer |
| Data fetching | A. TanStack Query |
| Component strategy | A. Keep custom design system, refactor into typed primitives |
| Testing | A. Vitest + Testing Library + Playwright |
| Backend dependency | A. Console consumes existing buyer endpoints (`/api/runs`, `/api/runs/:id`); no Python changes |

## 4. Information architecture & routes

Route group `(console)` shares one layout (sidebar + chat drawer). CopilotKit
provider stays at root.

| Route | Purpose | Data source |
|---|---|---|
| `/` (home) | Overview, "Run sample brief" CTA, last 3 runs, registry health | threads (recent), registry API |
| `/runs` | Runs history list with status badge/stage/time | CopilotKit threads + cached snapshots |
| `/runs/[runId]` | Run detail (deal room) | trace API, thread state |
| `/sellers` | Sellers directory (RegistryPanel promoted to a page) | registry API |
| `/settings` | Env display, reset local state | public config |
| `/help` | Static docs/glossary | static |

Layout notes:
- Sidebar (left, collapses <900px) with wordmark, nav, health dot, model badge,
  "New run".
- Chat drawer (right, 320px) is global, rendered by `(console)` layout.
- Home's "Run sample brief" starts a run and navigates to `/runs/[runId]`.
- In-progress runs live at `/runs/[runId]` so URLs are shareable.

## 5. Folder & file structure

```
apps/console/
├── app/
│   ├── layout.tsx
│   ├── (console)/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── runs/{page.tsx,[runId]/page.tsx,loading.tsx,error.tsx}
│   │   ├── sellers/page.tsx
│   │   ├── settings/page.tsx
│   │   └── help/page.tsx
│   ├── api/
│   │   ├── copilotkit/[[...slug]]/route.ts  (unchanged)
│   │   ├── registry/sellers/route.ts          (unchanged)
│   │   ├── runs/route.ts                     (NEW: list proxy)
│   │   ├── runs/[runId]/route.ts             (NEW: detail proxy)
│   │   └── runs/[runId]/trace/route.ts       (unchanged)
│   └── globals.css
├── components/ui/       (typed primitives)
├── components/layout/   (shell pieces)
├── features/
│   ├── deal-room/{components,hooks,queries}/
│   ├── runs/
│   ├── sellers/
│   ├── chat/
│   └── settings/
├── lib/{api,format,types,query-client,runs,config}.ts
├── providers/{query-provider,copilot-provider}.tsx
├── tests/ (Vitest)
├── e2e/ (Playwright)
└── vitest.config.ts
```

Key moves: split `console-shell.tsx` (548 lines) into `features/deal-room`; move
`mm-*` styling into `components/ui` primitives; extract hooks.

## 6. State management & data flow

Providers (root layout): CopilotKit → QueryClientProvider → RunContext.

- Home: `useQuery(['registry'])`; recent runs via `useRuns()` (buyer); startRun →
  navigate.
- Runs list: `useRuns()` (buyer API) → `RunSummary[]`. No thread parsing.
- Run detail: merge three sources — `useRun(runId)` (buyer, authoritative for
  stage/mandate/award/order/error/timestamps), `useRunState()` (thread, for live
  negotiations/sellers/offers when available), and `useRunTrace(runId)` (wire).
  Rich deal-room views degrade to EmptyState when thread data is absent
  (historical runs).
- Sellers: `useQuery(['registry'])` with 15s refetch.
- Settings: reads `NEXT_PUBLIC_*`; reset clears threads + query cache (confirm).
- Approval: `useApproval(runId)` hook shared by chat drawer card and run detail
  card — single resume path.

Error handling: query errors → page `ErrorBoundary` + retry; trace errors → inline;
agent errors → top alert; `error.tsx`/`loading.tsx`/`not-found.tsx` per group.

**Buyer-as-source-of-truth nuance (Option A)**
- The buyer `runs` table persists `stage, mandate, award, order, error, created_at,
  updated_at` (see `TraceStore.upsert_run`). It does **not** persist `negotiations`
  or offers.
- Therefore `/runs` (list) and `/runs/[runId]` header (stage, mandate, award, order,
  error, timestamps) are authoritative from the buyer API.
- Rich deal-room views (seller lanes, offer matrix, negotiation feed) still come
  from the CopilotKit thread state when available (live run). For historical runs
  whose thread is gone, those views degrade to an `EmptyState`; the award banner and
  order desk still render from persisted data.

## 7. Component & UI primitive layer

Primitives under `components/ui/`: Button, Panel/Card, Status, Money, Kicker,
EmptyState, Alert, Spinner, Skeleton, Badge, Tabs, Dialog, Tooltip, DropdownMenu,
PageHeader, Breadcrumbs. Visual identity unchanged; typed, accessible APIs.

Accessibility pass: focus rings, `aria-live` on status/trace counts/approval
prompt, keyboard approval (Enter approves, Esc does not), focus trap in dialogs,
skip-to-content link, contrast check on small muted text.

Responsive: sidebar collapses to top nav <900px (extends existing chat-rail
behavior).

## 8. Testing plan

- Vitest + Testing Library: `lib/format`, `lib/runs`, hooks, primitives, feature
  components with fixture props.
- Playwright: keep two existing flows (update routes), add smoke tests for all
  pages, a11y via `@axe-core/playwright`, mobile viewport run.
- Gates: `npm run test` (vitest), `npm run test:e2e` (playwright),
  `npm run test:all`; `make lint` (tsc + eslint).

## 9. Implementation milestones

1. Foundation: deps + primitives + providers; no behavior change.
2. Route shell: layout + placeholder pages; move deal room to `/runs/[runId]`.
3. State extraction: hooks from console-shell; delete shell.
4. Runs list + thread adapter.
5. Sellers page.
6. Settings + Help.
7. Home page.
8. A11y + responsive polish.
9. Docs update.

Each milestone independently shippable.

## 10. Production hardening checklist

Security: CSP + security headers in `next.config.ts`; no secrets in client bundle;
A2A frames sanitized; keep API proxying.

Performance: code-split deal room; Query dedup; next/font for Instrument Serif /
Spline Sans Mono; bundle analyzer script.

Resilience: error/loading/not-found boundaries; retry buttons; disable run CTA
when agent offline.

Observability: pluggable error sink (Sentry gated by env); Web Vitals reporting.

DX: eslint config, prettier + tailwind plugin optional, husky optional.

## 11. File inventory

New folders: `app/(console)/`, `components/ui/`, `components/layout/`,
`features/{deal-room,runs,sellers,chat,settings}/`, `providers/`, `tests/`.

New files (representative): providers, `lib/query-client.ts`, `lib/runs.ts`,
`lib/config.ts`, ui primitives, layout pieces, deal-room hooks/queries, runs/
sellers/settings/chat components, route pages + boundaries, `vitest.config.ts`,
`tests/setup.ts`, plus console proxy routes `app/api/runs/route.ts` and
`app/api/runs/[runId]/route.ts`.

Changed: `app/layout.tsx`, `app/page.tsx` (moved), delete `console-shell.tsx`,
`lib/api.ts` (+fetchRuns/fetchRun), `package.json`, `next.config.ts`,
`e2e/console.spec.ts`.

Unchanged: `app/api/copilotkit/**`, `app/api/registry/**`,
`app/api/runs/[runId]/trace/**`, `lib/format.ts`, `lib/types.ts`, `globals.css`.

## 12. Open questions resolved

- In-progress runs live at `/runs/[runId]` (shareable).
- No mock data.
- Frontend-only; no backend changes.
- Component strategy keeps bespoke look via typed primitives.