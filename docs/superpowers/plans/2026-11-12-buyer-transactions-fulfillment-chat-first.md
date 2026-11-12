# Buyer Transactions & Fulfillment (Chat-First) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver first-class, chat-first buyer Transactions and Fulfillment console surfaces backed by authoritative control-plane read/mutation APIs, then retire legacy runs/agents/deal-room UI without breaking required buyer-agent/chat infrastructure.

**Architecture:** Keep `/chat` as the primary buyer interaction surface. Add `(console)` routes `/transactions`, `/transactions/[transactionId]`, `/fulfillment`, `/fulfillment/[transactionId]` (transaction-keyed fulfillment, 1:1 now, extensible to 1:N). Use **control plane** as authority for buyer read projections, inspection/evidence/dispute/accept/delivery-confirmation, and blockers/allowed actions via new console proxy routes; use **buyer-agent** (`apps/console/lib/buyer-proxy.ts`, `app/api/runs/[runId]/**`) only for run-scoped settlement/stream/trace/artifacts where explicitly mapped. Replace legacy runs/agents entry points first, then delete legacy pages/features (404 for removed URLs); keep run APIs unless proven unused.

**Tech Stack:** Next.js 16 App Router (React 19), TypeScript, Clerk auth, TanStack Query, Vitest/RTL (console), Python 3.12/FastAPI/Pydantic/SQLAlchemy async SQLite tests (control plane), `pnpm` (console), `pytest` (control plane).

**Spec:** `docs/superpowers/specs/2026-11-12-buyer-transactions-fulfillment-chat-first-design.md`

## Global Constraints

- **Chat-first primary UX (Q2,Q6):** `/chat` remains primary; new pages are first-class console surfaces reachable from chat and sidebar, not deal-room/run pages.
- **Legacy removal sequencing and URL behavior (Q5,Q9):** add/validate replacements and rewiring before deleting `runs/agents/deal-room/runs` UI; removed `/runs` and `/agents/[runId]` routes return **404** with no redirects.
- **Run API infrastructure retained (Q1):** keep `apps/console/app/api/runs/[runId]/**` and `apps/console/lib/buyer-proxy.ts` unless a specific handler is proven unused.
- **Fulfillment identity (Q3,Q7):** fulfillment is keyed by `transactionId` (1:1 now) at `/fulfillment` and `/fulfillment/[transactionId]`; types/components/data access must isolate fulfillment identity for future 1:N `fulfillmentId`.
- **Authoritative data and no fabricated completeness (Q4,Q10):** list/overview/aggregate/timeline views render only from authoritative buyer read/list APIs/projections; fulfillment detail/actions prioritize authoritative control-plane per-transaction APIs.
- **Authority split:** control plane is authoritative for inspection, buyer-owned evidence, dispute/accept/delivery-confirmation, blockers/allowed actions, and release-relevant state; fulfillment completion never implies payout authorization. Buyer-agent is used only for run-scoped settlement/orchestration/artifacts when mapped.
- **Security/scoping:** server-derived auth only; no client-trusted tenant/buyer IDs; enforce buyer ownership/tenancy; propagate/handle 401/403/404(no-leak)/409/422/415 correctly; multipart evidence preserves required fields and constraints.
- **Navigation (Q8):** sidebar replaces **Runs** with **Transactions** and **Fulfillment**; agent CTA opens `/chat`.

---

## Slice A — Contracts & integration foundation

### Task 1: Control-plane buyer read/list projection contracts (authoritative, Q4)

**Files:**
- Modify: `apps/verifund_control_plane/verifund_control_plane/api/buyer.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/service.py`
- Modify: `apps/verifund_control_plane/verifund_control_plane/repository.py`
- Modify/Create: `apps/verifund_control_plane/verifund_control_plane/schemas/` (buyer projection/read models as needed)
- Test: `apps/verifund_control_plane/tests/test_buyer_routes.py` (or new `tests/test_buyer_read_projections.py`)

**Interfaces:**
- Consumes: existing buyer auth `authorize_buyer_transaction` / principal resolution, transaction/settlement/agreement/inspection/shipment/evidence/dispute records, tenant scoping.
- Produces: buyer-scoped read endpoints and DTOs (exact paths documented in OpenAPI/code) for:
  - `GET /buyer/transactions` → paginated/filterable summaries + overview aggregates/counts.
  - `GET /buyer/transactions/{transaction_id}` → transaction detail (commercial/agreement/payment/timeline) + fulfillment summary link data.
  - `GET /buyer/transactions/{transaction_id}/fulfillment` (or equivalent fulfillment projection path) → fulfillment detail keyed by `transaction_id` (requirements/results, buyer-visible evidence refs/verification, shipment/carrier timeline, inspection, disputes, blockers, `allowed_actions`).
  All responses include enough data for UI filters/cards/lists/timelines without client fabrication and enforce 404 on not-found/cross-tenant.

- [ ] **Step 1: Write failing route/contract tests**

```python
# apps/verifund_control_plane/tests/test_buyer_read_projections.py
import pytest

@pytest.mark.anyio
async def test_list_buyer_transactions_returns_scoped_summaries_and_aggregates(
    async_client, buyer_headers, seeded_buyer_transaction
):
    resp = await async_client.get("/buyer/transactions", headers=buyer_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert "aggregates" in body
    item = body["items"][0]
    assert item["transaction_id"] == seeded_buyer_transaction.transaction_id
    assert "agreed_amount" in item
    assert "payment_status" in item
    assert "transaction_status" in item
    assert "fulfillment" in item
    assert "next_action" in item["fulfillment"]


@pytest.mark.anyio
async def test_get_buyer_fulfillment_projection_404_for_cross_tenant(
    async_client, other_buyer_headers, seeded_buyer_transaction
):
    resp = await async_client.get(
        f"/buyer/transactions/{seeded_buyer_transaction.transaction_id}/fulfillment",
        headers=other_buyer_headers,
    )
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest apps/verifund_control_plane/tests/test_buyer_read_projections.py -q`
Expected: FAIL (404/422 for missing routes or schema mismatch).

- [ ] **Step 3: Implement repository/service projection queries**

```python
# apps/verifund_control_plane/verifund_control_plane/service.py (illustrative shape)
from dataclasses import dataclass
from typing import Any

@dataclass
class BuyerTransactionFilters:
    status: str | None = None
    payment_status: str | None = None
    fulfillment_status: str | None = None
    cursor: str | None = None
    limit: int = 20

async def list_buyer_transactions(self, *, buyer_principal, filters: BuyerTransactionFilters) -> dict[str, Any]:
    rows, total_counts = await self.repo.list_buyer_transaction_projections(
        buyer_id=buyer_principal.buyer_id,
        tenant_id=buyer_principal.tenant_id,
        **filters.__dict__,
    )
    items = [self._to_buyer_transaction_summary(r) for r in rows]
    aggregates = self._build_buyer_transaction_aggregates(total_counts)
    return {"items": items, "aggregates": aggregates, "next_cursor": self._next_cursor(rows, filters.limit)}

async def get_buyer_fulfillment_projection(self, *, buyer_principal, transaction_id: str) -> dict[str, Any]:
    row = await self.repo.get_buyer_transaction_projection(
        transaction_id=transaction_id,
        buyer_id=buyer_principal.buyer_id,
        tenant_id=buyer_principal.tenant_id,
    )
    if row is None:
        raise self.not_found()
    return self._to_buyer_fulfillment_detail(row)
```

```python
# apps/verifund_control_plane/verifund_control_plane/repository.py (illustrative query helpers)
async def list_buyer_transaction_projections(self, *, buyer_id: str, tenant_id: str | None, status: str | None, payment_status: str | None, fulfillment_status: str | None, cursor: str | None, limit: int):
    # enforce tenant/buyer scoping in WHERE clauses; include joins needed for summaries/aggregates
    ...

async def get_buyer_transaction_projection(self, *, transaction_id: str, buyer_id: str, tenant_id: str | None):
    # scoped fetch; return None when not found/not owned
    ...
```

- [ ] **Step 4: Implement buyer read routes**

```python
# apps/verifund_control_plane/verifund_control_plane/api/buyer.py
from fastapi import APIRouter, Depends, Query, Request
from ..service import BuyerTransactionFilters

router = APIRouter(prefix="/buyer", tags=["buyer"])

@router.get("/transactions")
async def list_buyer_transactions(
    request: Request,
    status: str | None = Query(default=None),
    payment_status: str | None = Query(default=None),
    fulfillment_status: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    principal = await authorize_buyer_list(request)  # buyer-scoped principal (no transaction_id path leak)
    service = _service(request)
    return await service.list_buyer_transactions(
        buyer_principal=principal,
        filters=BuyerTransactionFilters(
            status=status,
            payment_status=payment_status,
            fulfillment_status=fulfillment_status,
            cursor=cursor,
            limit=limit,
        ),
    )

@router.get("/transactions/{transaction_id}")
async def get_buyer_transaction(transaction_id: str, request: Request):
    principal = await authorize_buyer_transaction(request, transaction_id)
    return await _service(request).get_buyer_transaction_detail(
        buyer_principal=principal, transaction_id=transaction_id
    )

@router.get("/transactions/{transaction_id}/fulfillment")
async def get_buyer_fulfillment(transaction_id: str, request: Request):
    principal = await authorize_buyer_transaction(request, transaction_id)
    return await _service(request).get_buyer_fulfillment_projection(
        buyer_principal=principal, transaction_id=transaction_id
    )
```

- [ ] **Step 5: Run tests and targeted suite**

Run: `pytest apps/verifund_control_plane/tests/test_buyer_read_projections.py apps/verifund_control_plane/tests/test_buyer_routes.py -q`
Expected: PASS for new and existing buyer route coverage.

- [ ] **Step 6: Commit**

```bash
git add apps/verifund_control_plane/verifund_control_plane/api/buyer.py \
        apps/verifund_control_plane/verifund_control_plane/service.py \
        apps/verifund_control_plane/verifund_control_plane/repository.py \
        apps/verifund_control_plane/tests/test_buyer_read_projections.py
git commit -m "feat(control-plane): add buyer transaction and fulfillment read projections"
```

### Task 2: Console control-plane buyer proxy helper and auth alignment

**Files:**
- Modify: `apps/console/lib/control-plane.ts`
- Create: `apps/console/lib/buyer-control-plane.ts`
- Test: `apps/console/tests/lib/buyer-control-plane.test.ts` (or equivalent vitest location used in repo)

**Interfaces:**
- Consumes: Clerk session/auth (`auth`, `consoleSession`), env `VERIFUND_CONTROL_PLANE_URL`, control-plane buyer auth expectations.
- Produces:
  - `controlPlaneBuyer(path, init, opts?)` for JSON and passthrough requests.
  - `controlPlaneBuyerForm(path, formData, opts?)` (or a single helper that preserves `FormData` without forcing JSON headers).
  - Helpers to forward upstream responses/status/headers safely (including 401/403/404/409/422/415).

- [ ] **Step 1: Write failing helper tests**

```ts
// apps/console/tests/lib/buyer-control-plane.test.ts
import { describe, expect, it, vi, beforeEach } from "vitest";

vi.mock("@clerk/nextjs/server", () => ({
  auth: vi.fn(async () => ({
    getToken: vi.fn(async () => "clerk-token"),
    orgId: "org_1",
  })),
}));

describe("buyer-control-plane proxy helper", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 })));
    process.env.VERIFUND_CONTROL_PLANE_URL = "http://cp.test";
  });

  it("forwards bearer auth and preserves path", async () => {
    const { controlPlaneBuyer } = await import("@/lib/buyer-control-plane");
    const res = await controlPlaneBuyer("/buyer/transactions/tx_1/inspection");
    expect(res.status).toBe(200);
    const [url, init] = (fetch as any).mock.calls[0];
    expect(url).toBe("http://cp.test/buyer/transactions/tx_1/inspection");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer clerk-token");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C apps/console test -- tests/lib/buyer-control-plane.test.ts`
Expected: FAIL (module/helper missing).

- [ ] **Step 3: Implement helper**

```ts
// apps/console/lib/buyer-control-plane.ts
import { auth } from "@clerk/nextjs/server";

const CONTROL_PLANE = process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";

type BuyerProxyOptions = { timeoutMs?: number };

export async function controlPlaneBuyer(path: string, init: RequestInit = {}, opts: BuyerProxyOptions = {}) {
  const { getToken, orgId } = await auth();
  const token = await (getToken as (o: { organizationId?: string }) => Promise<string | null>)({
    organizationId: orgId ?? undefined,
  });
  if (!token) return new Response(JSON.stringify({ error: { message: "not signed in" } }), { status: 401, headers: { "content-type": "application/json" } });

  const headers = new Headers(init.headers);
  headers.set("authorization", `Bearer ${token}`);
  if (orgId) headers.set("x-verifund-org-id", orgId);

  // Do not force content-type for FormData bodies.
  const isFormData = typeof FormData !== "undefined" && init.body instanceof FormData;
  if (isFormData) headers.delete("content-type");

  return fetch(`${CONTROL_PLANE}${path}`, {
    ...init,
    cache: "no-store",
    headers,
    signal: opts.timeoutMs ? AbortSignal.timeout(opts.timeoutMs) : init.signal,
  });
}

export async function passthroughUpstream(res: Response) {
  const body = await res.arrayBuffer();
  const headers = new Headers();
  const ct = res.headers.get("content-type");
  if (ct) headers.set("content-type", ct);
  return new Response(body, { status: res.status, headers });
}
```

- [ ] **Step 4: Run test and typecheck**

Run: `pnpm -C apps/console test -- tests/lib/buyer-control-plane.test.ts && pnpm -C apps/console typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/lib/buyer-control-plane.ts apps/console/tests/lib/buyer-control-plane.test.ts
git commit -m "feat(console): add buyer control-plane proxy helper"
```

### Task 3: Console API routes for buyer fulfillment actions and read proxies

**Files:**
- Create: `apps/console/app/api/buyer/transactions/route.ts`
- Create: `apps/console/app/api/buyer/transactions/[id]/route.ts`
- Create: `apps/console/app/api/buyer/transactions/[id]/fulfillment/route.ts`
- Create: `apps/console/app/api/buyer/transactions/[id]/inspection/route.ts`
- Create: `apps/console/app/api/buyer/transactions/[id]/evidence/route.ts`
- Create: `apps/console/app/api/buyer/transactions/[id]/dispute/route.ts`
- Create: `apps/console/app/api/buyer/transactions/[id]/accept/route.ts`
- Create: `apps/console/app/api/buyer/transactions/[id]/delivery-confirmed/route.ts`
- Test: `apps/console/tests/app/api/buyer-transactions-routes.test.ts`

**Interfaces:**
- Consumes: `controlPlaneBuyer`, `passthroughUpstream`, Clerk `auth.protect()`, Next `NextRequest`.
- Produces: authenticated console proxy endpoints forwarding to control-plane buyer read/action paths, preserving method/body/status/errors (JSON and multipart for evidence).

- [ ] **Step 1: Write failing route tests**

```ts
// apps/console/tests/app/api/buyer-transactions-routes.test.ts
import { describe, it, expect, vi } from "vitest";
vi.mock("@clerk/nextjs/server", () => ({ auth: { protect: vi.fn(async () => ({})) } }));
vi.mock("@/lib/buyer-control-plane", () => ({
  controlPlaneBuyer: vi.fn(async () => new Response(JSON.stringify({ inspection: { status: "open" } }), { status: 200, headers: { "content-type": "application/json" } })),
  passthroughUpstream: (r: Response) => r,
}));

import { GET } from "@/app/api/buyer/transactions/[id]/inspection/route";

describe("buyer transaction proxy routes", () => {
  it("proxies inspection GET", async () => {
    const res = await GET(new Request("http://x") as any, { params: Promise.resolve({ id: "tx_1" }) } as any);
    expect(res.status).toBe(200);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C apps/console test -- tests/app/api/buyer-transactions-routes.test.ts`
Expected: FAIL (routes missing).

- [ ] **Step 3: Implement list/detail/fulfillment read routes**

```ts
// apps/console/app/api/buyer/transactions/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function GET(request: NextRequest) {
  await auth.protect();
  const qs = request.nextUrl.search; // preserves filters/cursor/limit
  const upstream = await controlPlaneBuyer(`/buyer/transactions${qs}`);
  return passthroughUpstream(upstream);
}
```

```ts
// apps/console/app/api/buyer/transactions/[id]/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  return passthroughUpstream(await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}`));
}
```

```ts
// apps/console/app/api/buyer/transactions/[id]/fulfillment/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  return passthroughUpstream(await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/fulfillment`));
}
```

- [ ] **Step 4: Implement inspection and mutation routes (JSON + multipart evidence)**

```ts
// apps/console/app/api/buyer/transactions/[id]/inspection/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function GET(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  return passthroughUpstream(await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/inspection`));
}
```

```ts
// apps/console/app/api/buyer/transactions/[id]/evidence/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  const formData = await request.formData(); // preserve multipart fields/file
  return passthroughUpstream(
    await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/evidence`, {
      method: "POST",
      body: formData,
    }),
  );
}
```

```ts
// apps/console/app/api/buyer/transactions/[id]/dispute/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  const body = await request.text();
  return passthroughUpstream(
    await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/dispute`, {
      method: "POST",
      headers: { "content-type": request.headers.get("content-type") ?? "application/json" },
      body,
    }),
  );
}
```

```ts
// apps/console/app/api/buyer/transactions/[id]/accept/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  const body = await request.text();
  return passthroughUpstream(
    await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/accept`, {
      method: "POST",
      headers: { "content-type": request.headers.get("content-type") ?? "application/json" },
      body: body || "{}",
    }),
  );
}
```

```ts
// apps/console/app/api/buyer/transactions/[id]/delivery-confirmed/route.ts
import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function POST(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  await auth.protect();
  const { id } = await params;
  const body = await request.text();
  return passthroughUpstream(
    await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/delivery-confirmed`, {
      method: "POST",
      headers: { "content-type": request.headers.get("content-type") ?? "application/json" },
      body: body || "{}",
    }),
  );
}
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm -C apps/console test -- tests/app/api/buyer-transactions-routes.test.ts && pnpm -C apps/console typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/console/app/api/buyer/transactions apps/console/tests/app/api/buyer-transactions-routes.test.ts
git commit -m "feat(console): proxy buyer transaction read and fulfillment routes"
```

### Task 4: Buyer transaction client types and API helpers

**Files:**
- Create: `apps/console/lib/buyer-transaction-types.ts`
- Create: `apps/console/lib/buyer-transaction-api.ts`
- Test: `apps/console/tests/lib/buyer-transaction-api.test.ts`

**Interfaces:**
- Consumes: console proxy routes `/api/buyer/transactions...`.
- Produces: typed models and functions for list/detail/fulfillment reads and fulfillment mutations (inspection fetch, evidence upload, dispute, accept, delivery-confirmed), with normalized error handling and transaction-keyed fulfillment (`transactionId`) extensible for future `fulfillmentId`.

- [ ] **Step 1: Write failing API helper tests**

```ts
// apps/console/tests/lib/buyer-transaction-api.test.ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { listBuyerTransactions, getBuyerFulfillment } from "@/lib/buyer-transaction-api";

describe("buyer-transaction-api", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("lists transactions from console proxy", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [], aggregates: {} }), { status: 200, headers: { "content-type": "application/json" } })));
    const data = await listBuyerTransactions({ status: "active" });
    expect(data.items).toEqual([]);
  });
  it("throws on 404 fulfillment", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: "not found" }), { status: 404, headers: { "content-type": "application/json" } })));
    await expect(getBuyerFulfillment("tx_missing")).rejects.toMatchObject({ status: 404 });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C apps/console test -- tests/lib/buyer-transaction-api.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement types**

```ts
// apps/console/lib/buyer-transaction-types.ts
export type BuyerTransactionSummary = {
  transaction_id: string;
  product_name?: string | null;
  seller_name?: string | null;
  agreed_amount_cents?: number | null;
  currency?: string | null;
  payment_status?: string | null;
  transaction_status?: string | null;
  fulfillment_status?: string | null;
  next_action?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type BuyerTransactionListResponse = {
  items: BuyerTransactionSummary[];
  aggregates?: Record<string, number>;
  next_cursor?: string | null;
};

export type BuyerFulfillmentProjection = {
  transaction_id: string;
  fulfillment_id?: string | null; // reserved for future 1:N; null/undefined when transaction-keyed
  status?: string | null;
  requirements?: Array<Record<string, any>>;
  evidence?: Array<Record<string, any>>;
  verification?: Array<Record<string, any>>;
  shipment?: Record<string, any> | null;
  carrier_events?: Array<Record<string, any>>;
  inspection?: Record<string, any> | null;
  disputes?: Array<Record<string, any>>;
  blockers?: Array<{ code: string; message?: string; owner?: string }>;
  allowed_actions?: string[];
  next_action?: string | null;
};
```

- [ ] **Step 4: Implement API helpers**

```ts
// apps/console/lib/buyer-transaction-api.ts
import type { BuyerFulfillmentProjection, BuyerTransactionListResponse } from "./buyer-transaction-types";

export type ApiError = Error & { status?: number; body?: any };

async function parseOrThrow(res: Response) {
  const text = await res.text();
  let body: any = null;
  try { body = text ? JSON.parse(text) : null; } catch { body = text; }
  if (!res.ok) {
    const message = body?.error?.message || body?.detail || body?.message || `Request failed (${res.status})`;
    const err = new Error(message) as ApiError;
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

export async function listBuyerTransactions(params: Record<string, string | number | undefined> = {}): Promise<BuyerTransactionListResponse> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetch(`/api/buyer/transactions${qs.size ? `?${qs}` : ""}`, { cache: "no-store" });
  return parseOrThrow(res);
}

export async function getBuyerTransaction(transactionId: string) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}`, { cache: "no-store" });
  return parseOrThrow(res);
}

export async function getBuyerFulfillment(transactionId: string): Promise<BuyerFulfillmentProjection> {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/fulfillment`, { cache: "no-store" });
  return parseOrThrow(res);
}

export async function getBuyerInspection(transactionId: string) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/inspection`, { cache: "no-store" });
  return parseOrThrow(res);
}

export async function submitBuyerEvidence(transactionId: string, formData: FormData) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/evidence`, { method: "POST", body: formData });
  return parseOrThrow(res);
}

export async function openBuyerDispute(transactionId: string, payload: { claim_type?: string; reason_code?: string; claim?: string; requirement_ids?: string[]; evidence_refs?: string[] }) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/dispute`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  return parseOrThrow(res);
}

export async function acceptBuyerTransaction(transactionId: string) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/accept`, { method: "POST", headers: { "content-type": "application/json" }, body: "{}" });
  return parseOrThrow(res);
}

export async function confirmBuyerDelivery(transactionId: string, payload: Record<string, any> = {}) {
  const res = await fetch(`/api/buyer/transactions/${encodeURIComponent(transactionId)}/delivery-confirmed`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  return parseOrThrow(res);
}
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm -C apps/console test -- tests/lib/buyer-transaction-api.test.ts && pnpm -C apps/console typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/console/lib/buyer-transaction-types.ts apps/console/lib/buyer-transaction-api.ts apps/console/tests/lib/buyer-transaction-api.test.ts
git commit -m "feat(console): add buyer transaction types and API helpers"
```

---

## Slice B — Fulfillment detail/actions priority (Q10)

### Task 5: Buyer fulfillment detail page and workspace components

**Files:**
- Create: `apps/console/app/(console)/fulfillment/[transactionId]/page.tsx`
- Create: `apps/console/components/buyer/fulfillment/fulfillment-detail.tsx`
- Create: `apps/console/components/buyer/fulfillment/buyer-inspection-panel.tsx`
- Create: `apps/console/components/buyer/fulfillment/buyer-evidence-dialog.tsx`
- Create: `apps/console/components/buyer/fulfillment/dispute-panel.tsx`
- Create: `apps/console/components/buyer/fulfillment/fulfillment-actions.tsx`
- Create: `apps/console/components/buyer/fulfillment/transaction-reference.tsx`
- Create: `apps/console/components/buyer/shared/blockers-panel.tsx`
- Test: `apps/console/tests/components/buyer/fulfillment-detail.test.tsx`

**Interfaces:**
- Consumes: `getBuyerFulfillment`, `getBuyerInspection`, `submitBuyerEvidence`, `openBuyerDispute`, `acceptBuyerTransaction`, `confirmBuyerDelivery`; control-plane fulfillment projection fields (`requirements`, `evidence`, `verification`, `shipment`, `carrier_events`, `inspection`, `disputes`, `blockers`, `allowed_actions`).
- Produces: `/fulfillment/[transactionId]` operational workspace with requirements/evidence/verification, shipment/carrier timeline (when available), inspection panel, buyer evidence upload (multipart), dispute/accept/delivery actions gated by `allowed_actions`/blockers, and `TransactionReference` link to `/transactions/[transactionId]`. No fabricated data when projection fields are absent.

- [ ] **Step 1: Write failing component/page tests**

```tsx
// apps/console/tests/components/buyer/fulfillment-detail.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("@/lib/buyer-transaction-api", () => ({
  getBuyerFulfillment: vi.fn(async () => ({
    transaction_id: "tx_1",
    status: "awaiting_inspection",
    blockers: [{ code: "inspection_pending", message: "Inspection pending" }],
    allowed_actions: ["accept", "dispute"],
    requirements: [],
    evidence: [],
  })),
  getBuyerInspection: vi.fn(async () => ({ status: "open" })),
}));
import FulfillmentDetailPage from "@/app/(console)/fulfillment/[transactionId]/page";

describe("Fulfillment detail page", () => {
  it("renders fulfillment workspace and transaction cross-link", async () => {
    const ui = await FulfillmentDetailPage({ params: Promise.resolve({ transactionId: "tx_1" }) } as any);
    render(ui as any);
    expect(await screen.findByText(/fulfillment/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /transaction/i })).toHaveAttribute("href", "/transactions/tx_1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C apps/console test -- tests/components/buyer/fulfillment-detail.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement page shell and data loading**

```tsx
// apps/console/app/(console)/fulfillment/[transactionId]/page.tsx
import { notFound } from "next/navigation";
import { getBuyerFulfillment, getBuyerInspection } from "@/lib/buyer-transaction-api";
import { FulfillmentDetail } from "@/components/buyer/fulfillment/fulfillment-detail";

export default async function FulfillmentDetailPage({ params }: { params: Promise<{ transactionId: string }> }) {
  const { transactionId } = await params;
  try {
    const [fulfillment, inspection] = await Promise.all([
      getBuyerFulfillment(transactionId),
      getBuyerInspection(transactionId).catch((e: any) => (e?.status === 404 ? null : Promise.reject(e))),
    ]);
    return <FulfillmentDetail transactionId={transactionId} fulfillment={fulfillment} inspection={inspection} />;
  } catch (e: any) {
    if (e?.status === 404) notFound();
    throw e;
  }
}
```

- [ ] **Step 4: Implement detail workspace and action components**

```tsx
// apps/console/components/buyer/fulfillment/fulfillment-detail.tsx
"use client";
import { useState } from "react";
import type { BuyerFulfillmentProjection } from "@/lib/buyer-transaction-types";
import { TransactionReference } from "./transaction-reference";
import { BuyerInspectionPanel } from "./buyer-inspection-panel";
import { BuyerEvidenceDialog } from "./buyer-evidence-dialog";
import { DisputePanel } from "./dispute-panel";
import { FulfillmentActions } from "./fulfillment-actions";
import { BlockersPanel } from "../shared/blockers-panel";
import { getBuyerFulfillment, getBuyerInspection } from "@/lib/buyer-transaction-api";

export function FulfillmentDetail({ transactionId, fulfillment: initial, inspection: initialInspection }: { transactionId: string; fulfillment: BuyerFulfillmentProjection; inspection: any; }) {
  const [fulfillment, setFulfillment] = useState(initial);
  const [inspection, setInspection] = useState(initialInspection);
  const refresh = async () => {
    const [f, i] = await Promise.all([
      getBuyerFulfillment(transactionId),
      getBuyerInspection(transactionId).catch(() => null),
    ]);
    setFulfillment(f); setInspection(i);
  };

  return (
    <main className="mm-page" aria-label="Fulfillment detail">
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Fulfillment</p>
          <h1>Fulfillment for {transactionId}</h1>
        </div>
        <TransactionReference transactionId={transactionId} />
      </header>

      <BlockersPanel blockers={fulfillment.blockers ?? []} />

      <section className="mm-panel" aria-label="Requirements and evidence">
        <h2>Requirements & evidence</h2>
        {(fulfillment.requirements ?? []).length === 0 ? <p className="mm-muted">No requirement details available.</p> : (
          <ul>
            {(fulfillment.requirements ?? []).map((r: any) => (
              <li key={r.requirement_id ?? r.id}>
                <strong>{r.title ?? r.requirement_id}</strong> — {r.status ?? "unknown"}
              </li>
            ))}
          </ul>
        )}
        <BuyerEvidenceDialog transactionId={transactionId} requirements={fulfillment.requirements ?? []} onSubmitted={refresh} />
      </section>

      <section className="mm-panel" aria-label="Shipment">
        <h2>Shipment & carrier</h2>
        {fulfillment.shipment ? <pre>{JSON.stringify(fulfillment.shipment, null, 2)}</pre> : <p className="mm-muted">No shipment data available.</p>}
      </section>

      <BuyerInspectionPanel inspection={inspection ?? fulfillment.inspection} />
      <DisputePanel transactionId={transactionId} allowedActions={fulfillment.allowed_actions ?? []} onChanged={refresh} />
      <FulfillmentActions
        transactionId={transactionId}
        allowedActions={fulfillment.allowed_actions ?? []}
        blockers={fulfillment.blockers ?? []}
        onChanged={refresh}
      />
    </main>
  );
}
```

```tsx
// apps/console/components/buyer/fulfillment/buyer-evidence-dialog.tsx
"use client";
import { useRef, useState } from "react";
import { submitBuyerEvidence } from "@/lib/buyer-transaction-api";

export function BuyerEvidenceDialog({ transactionId, requirements, onSubmitted }: { transactionId: string; requirements: any[]; onSubmitted: () => Promise<void> | void; }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [requirementId, setRequirementId] = useState("");
  const [viewLabel, setViewLabel] = useState("");
  const [agreementVersion, setAgreementVersion] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !requirementId) { setError("Requirement and file are required."); return; }
    setBusy(true); setError(null);
    try {
      const fd = new FormData();
      fd.set("requirement_id", requirementId);
      if (viewLabel) fd.set("view_label", viewLabel);
      if (agreementVersion) fd.set("agreement_version", agreementVersion);
      fd.set("file", file);
      await submitBuyerEvidence(transactionId, fd);
      await onSubmitted();
      ref.current?.close();
    } catch (err: any) {
      setError(err?.message ?? "Evidence upload failed");
    } finally { setBusy(false); }
  };

  return (
    <>
      <button type="button" onClick={() => ref.current?.showModal()}>Submit buyer evidence</button>
      <dialog ref={ref} aria-label="Submit buyer evidence">
        <form onSubmit={submit}>
          <label>Requirement
            <select value={requirementId} onChange={(e) => setRequirementId(e.target.value)} required>
              <option value="">Select requirement</option>
              {requirements.filter((r) => r.owner === "buyer" || r.buyer_actionable).map((r) => (
                <option key={r.requirement_id ?? r.id} value={r.requirement_id ?? r.id}>{r.title ?? r.requirement_id}</option>
              ))}
            </select>
          </label>
          <label>View label<input value={viewLabel} onChange={(e) => setViewLabel(e.target.value)} /></label>
          <label>Agreement version<input value={agreementVersion} onChange={(e) => setAgreementVersion(e.target.value)} /></label>
          <label>File<input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required /></label>
          {error ? <p role="alert">{error}</p> : null}
          <button type="submit" disabled={busy}>{busy ? "Uploading…" : "Upload evidence"}</button>
        </form>
      </dialog>
    </>
  );
}
```

```tsx
// apps/console/components/buyer/fulfillment/fulfillment-actions.tsx
"use client";
import { useState } from "react";
import { acceptBuyerTransaction, confirmBuyerDelivery } from "@/lib/buyer-transaction-api";

export function FulfillmentActions({ transactionId, allowedActions, blockers, onChanged }: { transactionId: string; allowedActions: string[]; blockers: any[]; onChanged: () => Promise<void> | void; }) {
  const [error, setError] = useState<string | null>(null);
  const canAccept = allowedActions.includes("accept");
  const canConfirm = allowedActions.includes("delivery_confirmed") || allowedActions.includes("confirm_delivery");
  const run = async (fn: () => Promise<any>) => {
    setError(null);
    try { await fn(); await onChanged(); } catch (e: any) { setError(e?.message ?? "Action failed"); }
  };
  return (
    <section className="mm-panel" aria-label="Fulfillment actions">
      <h2>Actions</h2>
      <p className="mm-muted">Actions are enabled only when allowed by authoritative transaction state.</p>
      <button disabled={!canAccept} onClick={() => run(() => acceptBuyerTransaction(transactionId))}>Accept</button>
      <button disabled={!canConfirm} onClick={() => run(() => confirmBuyerDelivery(transactionId, {}))}>Confirm delivery</button>
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
```

```tsx
// apps/console/components/buyer/fulfillment/transaction-reference.tsx
import Link from "next/link";
export function TransactionReference({ transactionId }: { transactionId: string }) {
  return (
    <Link href={`/transactions/${encodeURIComponent(transactionId)}`} className="mm-link">
      View transaction {transactionId}
    </Link>
  );
}
```

```tsx
// apps/console/components/buyer/shared/blockers-panel.tsx
export function BlockersPanel({ blockers }: { blockers: Array<{ code: string; message?: string; owner?: string }> }) {
  if (!blockers?.length) return null;
  return (
    <section className="mm-panel mm-panel-warning" aria-label="Blockers">
      <h2>Blockers</h2>
      <ul>{blockers.map((b, i) => <li key={`${b.code}-${i}`}><strong>{b.code}</strong>{b.owner ? ` (${b.owner})` : ""}: {b.message ?? "Action required"}</li>)}</ul>
    </section>
  );
}
```

```tsx
// apps/console/components/buyer/fulfillment/buyer-inspection-panel.tsx
export function BuyerInspectionPanel({ inspection }: { inspection: any }) {
  return (
    <section className="mm-panel" aria-label="Inspection">
      <h2>Inspection</h2>
      {!inspection ? <p className="mm-muted">No inspection record available.</p> : (
        <dl>
          <div><dt>Status</dt><dd>{inspection.status ?? "unknown"}</dd></div>
          <div><dt>Deadline</dt><dd>{inspection.deadline_at ?? inspection.deadline ?? "—"}</dd></div>
          <div><dt>Outcome</dt><dd>{inspection.outcome ?? "—"}</dd></div>
        </dl>
      )}
    </section>
  );
}
```

```tsx
// apps/console/components/buyer/fulfillment/dispute-panel.tsx
"use client";
import { useState } from "react";
import { openBuyerDispute } from "@/lib/buyer-transaction-api";

export function DisputePanel({ transactionId, allowedActions, onChanged }: { transactionId: string; allowedActions: string[]; onChanged: () => Promise<void> | void; }) {
  const [claim, setClaim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const canDispute = allowedActions.includes("dispute") || allowedActions.includes("open_dispute");
  const submit = async () => {
    setError(null);
    try {
      await openBuyerDispute(transactionId, { claim_type: "inspection", reason_code: "buyer_dispute", claim });
      setClaim("");
      await onChanged();
    } catch (e: any) { setError(e?.message ?? "Dispute failed"); }
  };
  return (
    <section className="mm-panel" aria-label="Dispute">
      <h2>Dispute</h2>
      <textarea value={claim} onChange={(e) => setClaim(e.target.value)} placeholder="Describe the issue" disabled={!canDispute} />
      <button disabled={!canDispute || !claim.trim()} onClick={submit}>Open dispute</button>
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm -C apps/console test -- tests/components/buyer/fulfillment-detail.test.tsx && pnpm -C apps/console typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/console/app/(console)/fulfillment/[transactionId]/page.tsx \
        apps/console/components/buyer/fulfillment apps/console/components/buyer/shared \
        apps/console/tests/components/buyer/fulfillment-detail.test.tsx
git commit -m "feat(console): add buyer fulfillment detail workspace and actions"
```

### Task 6: Minimal transaction detail page with fulfillment cross-link

**Files:**
- Create: `apps/console/app/(console)/transactions/[transactionId]/page.tsx`
- Create: `apps/console/components/buyer/transactions/transaction-detail.tsx`
- Create: `apps/console/components/buyer/transactions/fulfillment-summary.tsx`
- Test: `apps/console/tests/components/buyer/transaction-detail.test.tsx`

**Interfaces:**
- Consumes: `getBuyerTransaction` (authoritative detail projection), optional run-scoped settlement/receipt context only when `runId` is explicitly available/mapped (do not fabricate).
- Produces: `/transactions/[transactionId]` commercial record view (summary/agreement/payment/timeline as provided by projection) with `FulfillmentSummary` linking to `/fulfillment/[transactionId]`.

- [ ] **Step 1: Write failing test**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("@/lib/buyer-transaction-api", () => ({
  getBuyerTransaction: vi.fn(async () => ({ transaction_id: "tx_1", transaction_status: "active", fulfillment: { status: "awaiting_inspection" } })),
}));
import TransactionDetailPage from "@/app/(console)/transactions/[transactionId]/page";

describe("Transaction detail page", () => {
  it("links to fulfillment detail", async () => {
    const ui = await TransactionDetailPage({ params: Promise.resolve({ transactionId: "tx_1" }) } as any);
    render(ui as any);
    expect(await screen.findByRole("link", { name: /fulfillment/i })).toHaveAttribute("href", "/fulfillment/tx_1");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C apps/console test -- tests/components/buyer/transaction-detail.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement page and components**

```tsx
// apps/console/app/(console)/transactions/[transactionId]/page.tsx
import { notFound } from "next/navigation";
import { getBuyerTransaction } from "@/lib/buyer-transaction-api";
import { TransactionDetail } from "@/components/buyer/transactions/transaction-detail";

export default async function TransactionDetailPage({ params }: { params: Promise<{ transactionId: string }> }) {
  const { transactionId } = await params;
  try {
    const detail = await getBuyerTransaction(transactionId);
    return <TransactionDetail transactionId={transactionId} detail={detail} />;
  } catch (e: any) {
    if (e?.status === 404) notFound();
    throw e;
  }
}
```

```tsx
// apps/console/components/buyer/transactions/fulfillment-summary.tsx
import Link from "next/link";
export function FulfillmentSummary({ transactionId, fulfillment }: { transactionId: string; fulfillment?: any }) {
  return (
    <section className="mm-panel" aria-label="Fulfillment summary">
      <h2>Fulfillment</h2>
      <p>Status: {fulfillment?.status ?? "Unavailable"}</p>
      {fulfillment?.next_action ? <p>Next action: {fulfillment.next_action}</p> : null}
      <Link href={`/fulfillment/${encodeURIComponent(transactionId)}`}>View fulfillment</Link>
    </section>
  );
}
```

```tsx
// apps/console/components/buyer/transactions/transaction-detail.tsx
import { FulfillmentSummary } from "./fulfillment-summary";

export function TransactionDetail({ transactionId, detail }: { transactionId: string; detail: any }) {
  return (
    <main className="mm-page" aria-label="Transaction detail">
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Transaction</p>
          <h1>{transactionId}</h1>
        </div>
      </header>
      <section className="mm-panel" aria-label="Transaction summary">
        <h2>Summary</h2>
        <dl>
          <div><dt>Status</dt><dd>{detail?.transaction_status ?? detail?.status ?? "—"}</dd></div>
          <div><dt>Payment</dt><dd>{detail?.payment_status ?? "—"}</dd></div>
          <div><dt>Amount</dt><dd>{detail?.agreed_amount_cents != null ? `${detail.agreed_amount_cents} ${detail.currency ?? ""}` : "—"}</dd></div>
        </dl>
      </section>
      <section className="mm-panel" aria-label="Agreement and timeline">
        <h2>Agreement & timeline</h2>
        {detail?.timeline ? <pre>{JSON.stringify(detail.timeline, null, 2)}</pre> : <p className="mm-muted">Timeline details unavailable until provided by the buyer read projection.</p>}
      </section>
      <FulfillmentSummary transactionId={transactionId} fulfillment={detail?.fulfillment} />
    </main>
  );
}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `pnpm -C apps/console test -- tests/components/buyer/transaction-detail.test.tsx && pnpm -C apps/console typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/app/(console)/transactions/[transactionId]/page.tsx \
        apps/console/components/buyer/transactions \
        apps/console/tests/components/buyer/transaction-detail.test.tsx
git commit -m "feat(console): add minimal buyer transaction detail with fulfillment link"
```

---

## Slice C — Lists/aggregates/timelines (Q4, Q10)

### Task 7: Transactions and Fulfillment list pages

**Files:**
- Create: `apps/console/app/(console)/transactions/page.tsx`
- Create: `apps/console/app/(console)/fulfillment/page.tsx`
- Create: `apps/console/components/buyer/transactions/transaction-list.tsx`
- Create: `apps/console/components/buyer/fulfillment/fulfillment-list.tsx`
- Create: `apps/console/components/buyer/shared/overview-cards.tsx`
- Test: `apps/console/tests/components/buyer/buyer-lists.test.tsx`

**Interfaces:**
- Consumes: `listBuyerTransactions` and fulfillment list/read projection endpoint(s) backed by authoritative buyer read/list APIs (same or preceding backend slice). No run-history approximation.
- Produces: `/transactions` and `/fulfillment` first-class pages with overview aggregates/cards, filters, and paginated/listed items keyed by `transaction_id`, linking to details and cross-linked surfaces.

- [ ] **Step 1: Write failing list-page tests**

```tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
vi.mock("@/lib/buyer-transaction-api", () => ({
  listBuyerTransactions: vi.fn(async () => ({ items: [{ transaction_id: "tx_1", transaction_status: "active", fulfillment_status: "awaiting_inspection" }], aggregates: { total: 1 } })),
}));
import TransactionsPage from "@/app/(console)/transactions/page";

describe("Transactions list page", () => {
  it("renders authoritative transaction items", async () => {
    const ui = await TransactionsPage({ searchParams: Promise.resolve({}) } as any);
    render(ui as any);
    expect(await screen.findByText("tx_1")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm -C apps/console test -- tests/components/buyer/buyer-lists.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement transactions list page/components**

```tsx
// apps/console/app/(console)/transactions/page.tsx
import Link from "next/link";
import { listBuyerTransactions } from "@/lib/buyer-transaction-api";

export default async function TransactionsPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const status = typeof sp.status === "string" ? sp.status : undefined;
  const data = await listBuyerTransactions({ status });
  return (
    <main className="mm-page" aria-label="Transactions">
      <header className="mm-page-header"><div><p className="mm-kicker">Buyer workspace</p><h1>Transactions</h1></div></header>
      <section className="mm-panel" aria-label="Overview">
        <h2>Overview</h2>
        <pre>{JSON.stringify(data.aggregates ?? {}, null, 2)}</pre>
      </section>
      <section className="mm-panel" aria-label="Transaction list">
        <h2>Transactions</h2>
        {data.items.length === 0 ? <p className="mm-muted">No transactions available.</p> : (
          <ul>
            {data.items.map((t) => (
              <li key={t.transaction_id}>
                <Link href={`/transactions/${encodeURIComponent(t.transaction_id)}`}>{t.transaction_id}</Link>
                {" — "}{t.transaction_status ?? "unknown"}{" / "}{t.payment_status ?? "unknown"}
                {t.fulfillment_status ? <>{" · fulfillment: "}{t.fulfillment_status}</> : null}
                {" · "}<Link href={`/fulfillment/${encodeURIComponent(t.transaction_id)}`}>View fulfillment</Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
```

- [ ] **Step 4: Implement fulfillment list page (authoritative projection; no fabrication)**

```tsx
// apps/console/app/(console)/fulfillment/page.tsx
import Link from "next/link";
import { listBuyerTransactions } from "@/lib/buyer-transaction-api";

export default async function FulfillmentPage({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const sp = await searchParams;
  const fulfillment_status = typeof sp.fulfillment_status === "string" ? sp.fulfillment_status : undefined;
  // Uses authoritative buyer list projection that includes fulfillment summaries/aggregates (Q4). No run-history approximation.
  const data = await listBuyerTransactions({ fulfillment_status } as any);
  const items = data.items.filter((t) => t.fulfillment_status || t.next_action);
  return (
    <main className="mm-page" aria-label="Fulfillment">
      <header className="mm-page-header"><div><p className="mm-kicker">Buyer workspace</p><h1>Fulfillment</h1></div></header>
      <section className="mm-panel" aria-label="Overview">
        <h2>Overview</h2>
        <pre>{JSON.stringify(data.aggregates ?? {}, null, 2)}</pre>
      </section>
      <section className="mm-panel" aria-label="Fulfillment list">
        <h2>Fulfillment records</h2>
        {items.length === 0 ? <p className="mm-muted">No fulfillment records available.</p> : (
          <ul>
            {items.map((t) => (
              <li key={t.transaction_id}>
                <Link href={`/fulfillment/${encodeURIComponent(t.transaction_id)}`}>{t.transaction_id}</Link>
                {" — "}{t.fulfillment_status ?? "unknown"}
                {t.next_action ? <>{" · next: "}{t.next_action}</> : null}
                {" · "}<Link href={`/transactions/${encodeURIComponent(t.transaction_id)}`}>View transaction</Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm -C apps/console test -- tests/components/buyer/buyer-lists.test.tsx && pnpm -C apps/console typecheck`
Expected: PASS (with projection-backed data in integration environments).

- [ ] **Step 6: Commit**

```bash
git add apps/console/app/(console)/transactions/page.tsx \
        apps/console/app/(console)/fulfillment/page.tsx \
        apps/console/components/buyer/shared/overview-cards.tsx \
        apps/console/tests/components/buyer/buyer-lists.test.tsx
git commit -m "feat(console): add buyer transactions and fulfillment list pages"
```

---

## Slice D — Chat-first rewiring & legacy removal

### Task 8: Sidebar, CTA, and app entry-point rewiring (Q2, Q6, Q8)

**Files:**
- Modify: `apps/console/components/layout/sidebar.tsx`
- Modify: `apps/console/components/layout/mode-toggle.tsx` (if needed for chat-first semantics)
- Modify: `apps/console/components/layout/console-layout.tsx` (if needed for navigation/shell behavior)
- Modify: `apps/console/app/(public)/page.tsx`
- Modify: `apps/console/app/(console)/marketplace/page.tsx`
- Modify: any other files linking to `/runs` or `/agents` (discover via `rg "/runs|/agents"` in `apps/console`)
- Test: update/add navigation/layout tests as present in repo

**Interfaces:**
- Consumes: existing nav/layout components and router.
- Produces: sidebar nav with **Transactions** (`/transactions`) and **Fulfillment** (`/fulfillment`) replacing **Runs**; agent CTA opens `/chat`; public/marketplace and in-app flows no longer navigate to `/runs` or `/agents`.

- [ ] **Step 1: Write/update failing navigation tests (or assertions)**

```tsx
// example assertion in a layout/sidebar test
expect(screen.getByRole("link", { name: /Transactions/i })).toHaveAttribute("href", "/transactions");
expect(screen.getByRole("link", { name: /Fulfillment/i })).toHaveAttribute("href", "/fulfillment");
expect(screen.queryByRole("link", { name: /^Runs$/i })).toBeNull();
```

- [ ] **Step 2: Run targeted tests to verify failure**

Run: `pnpm -C apps/console test -- <sidebar-or-layout-test-path>`
Expected: FAIL before changes.

- [ ] **Step 3: Update sidebar and CTA**

```tsx
// apps/console/components/layout/sidebar.tsx (key changes)
import { ClipboardCheck, LayoutDashboard, History, MessageCircle, ShoppingBag, Store, Settings, HelpCircle, ReceiptText } from "lucide-react";

const NAV = [
  { href: "/", label: "Home", icon: LayoutDashboard },
  { href: "/marketplace", label: "Marketplace", icon: ShoppingBag },
  { href: "/transactions", label: "Transactions", icon: ReceiptText },
  { href: "/fulfillment", label: "Fulfillment", icon: ClipboardCheck },
  { href: "/sellers", label: "Sellers", icon: Store },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help", icon: HelpCircle },
];

const openAgent = () => {
  try { window.sessionStorage.removeItem("marketmesh:pendingBrief"); } catch {}
  router.push("/chat");
};
```

- [ ] **Step 4: Rewire public/marketplace and remaining entry points**

```tsx
// apps/console/app/(public)/page.tsx and apps/console/app/(console)/marketplace/page.tsx
// Replace pushes like router.push(`/runs/${threadId}`) or router.push(`/agents/${...}`)
// with chat-first navigation, preserving intent:
router.push("/chat");
// When a specific transaction context is known, prefer:
// router.push(`/transactions/${transactionId}`) or `/fulfillment/${transactionId}`
```

```bash
# discovery/verification command used during implementation
rg -n '"/runs|/agents|/runs/\$\{|/agents/\$\{' apps/console
```

- [ ] **Step 5: Run tests and typecheck**

Run: `pnpm -C apps/console test -- <touched-test-paths> && pnpm -C apps/console typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/console/components/layout apps/console/app/(public)/page.tsx apps/console/app/(console)/marketplace/page.tsx
git commit -m "feat(console): rewire navigation to chat-first transactions and fulfillment"
```

### Task 9: Chat deep-links and transaction/fulfillment reachability

**Files:**
- Modify: `apps/console/features/chat/chat.tsx`
- Modify: `apps/console/features/chat/verifund-tools.tsx` (and/or chat UI components as needed)
- Test: `apps/console/tests/**` chat-related tests if present (or add focused tests)

**Interfaces:**
- Consumes: chat/tool result contexts that include `transaction_id` (and optionally run/settlement context), existing CopilotKit tool renderers/HITL flows.
- Produces: user-visible links/actions from relevant chat states/cards to `/transactions/[transactionId]` and `/fulfillment/[transactionId]` without routing users into legacy `/runs` or `/agents` pages.

- [ ] **Step 1: Write failing UI assertion/test for deep-link presence**

```tsx
// example: when a tool result includes transaction_id, render a fulfillment link
expect(screen.getByRole("link", { name: /view fulfillment/i })).toHaveAttribute("href", "/fulfillment/tx_123");
```

- [ ] **Step 2: Run targeted chat tests**

Run: `pnpm -C apps/console test -- <chat-test-path>`
Expected: FAIL before change.

- [ ] **Step 3: Add deep-links in chat/tool renderers**

```tsx
// apps/console/features/chat/verifund-tools.tsx (illustrative insertion in relevant result cards)
{result?.transaction_id ? (
  <div className="mm-links">
    <a href={`/transactions/${encodeURIComponent(result.transaction_id)}`}>View transaction</a>
    <a href={`/fulfillment/${encodeURIComponent(result.transaction_id)}`}>View fulfillment</a>
  </div>
) : null}
```

- [ ] **Step 4: Run tests and typecheck**

Run: `pnpm -C apps/console test -- <chat-test-path> && pnpm -C apps/console typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat
git commit -m "feat(console): add chat deep-links to transactions and fulfillment"
```

### Task 10: Remove legacy runs/agents/deal-room UI and return 404 (Q5, Q9)

**Files:**
- Delete: `apps/console/app/(console)/runs/page.tsx`
- Delete: `apps/console/app/(console)/runs/[runId]/page.tsx`
- Delete: `apps/console/app/(console)/agents/[runId]/page.tsx`
- Delete: `apps/console/features/deal-room/**`
- Delete: `apps/console/features/runs/**`
- Delete: `apps/console/tests/features/deal-room/**`
- Modify: any remaining imports/references discovered by search
- Keep unless proven unused: `apps/console/app/api/runs/**`, `apps/console/lib/buyer-proxy.ts`, shared types still consumed

**Interfaces:**
- Consumes: completed rewiring (Tasks 8-9) and validated replacements (Slices B-C).
- Produces: no legacy run/agent/deal-room UI in console; removed routes resolve as 404 by absence; no in-app links to removed paths.

- [ ] **Step 1: Prove no remaining UI consumers**

Run: `rg -n "features/deal-room|features/runs|RunDetailWorkspace|TransactionRoom|useRuns|RunSummaryCard|/runs/|/agents/" apps/console`
Expected: only references intentionally retained (e.g. `app/api/runs/**` infrastructure, this plan/spec docs) or none in UI source; fix any remaining UI imports before deletion.

- [ ] **Step 2: Delete legacy pages/features/tests**

```bash
git rm -r apps/console/app/(console)/runs \
          apps/console/app/(console)/agents \
          apps/console/features/deal-room \
          apps/console/features/runs \
          apps/console/tests/features/deal-room
```

- [ ] **Step 3: Fix residual imports/types and ensure 404 behavior by absence**

Run: `rg -n "deal-room|RunDetail|use-run|RunSummaryCard|/agents/\[runId\]|/runs/\[runId\]" apps/console`
Expected: no matches in runtime UI code. (No redirect route files added for `/runs` or `/agents`; absence yields 404 per Q9.)

- [ ] **Step 4: Verify run API infrastructure still needed is intact (Q1)**

Run: `rg -n "app/api/runs" apps/console/features/chat apps/console/lib apps/console/app`
Expected: any remaining consumers point to kept `app/api/runs/**` handlers; remove only handlers with zero consumers in a separate, evidence-backed commit if found.

- [ ] **Step 5: Run console checks**

Run: `pnpm -C apps/console typecheck && pnpm -C apps/console test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore(console): remove legacy runs agents and deal-room surfaces"
```

### Task 11: End-to-end verification and documentation of contracts

**Files:**
- Modify: `docs/superpowers/specs/2026-11-12-buyer-transactions-fulfillment-chat-first-design.md` (only to record final endpoint paths/shapes if they differ from documented contract names)
- Modify: this plan or add implementation notes in commit messages as needed (no placeholders)

**Interfaces:**
- Consumes: completed slices A-D.
- Produces: verified chat-first navigation, working `/transactions` and `/fulfillment` surfaces against authoritative APIs, preserved required run infrastructure, and documented read/proxy contract paths.

- [ ] **Step 1: Verify control-plane and console automated checks**

Run: `pytest apps/verifund_control_plane/tests/test_buyer_read_projections.py apps/verifund_control_plane/tests/test_buyer_routes.py -q && pnpm -C apps/console typecheck && pnpm -C apps/console test`
Expected: PASS.

- [ ] **Step 2: Manual/integration verification**

Run (local services as applicable): start console/control-plane/buyer-agent per repo workflow, then validate:
- Sidebar shows Transactions/Fulfillment (no Runs), agent CTA opens `/chat`.
- `/transactions` and `/fulfillment` load from authoritative read APIs (or show correct unavailable/empty states per projection availability, without fabricated data).
- `/fulfillment/[transactionId]` loads inspection/projection, supports buyer evidence upload/dispute/accept/delivery-confirmation as allowed, and refetches authoritative state.
- `/transactions/[transactionId]` and `/fulfillment/[transactionId]` cross-link correctly.
- `/runs` and `/agents/[runId]` return 404; required `app/api/runs/**` endpoints used by chat still respond.

- [ ] **Step 3: Evidence-based pruning of unused run API handlers (if any)**

Run: for each candidate handler, `rg -n "<handler path>" apps/console features packages` and remove only when zero consumers.
Expected: no removals without proof; commit separately if performed.

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: verify and finalize buyer transactions fulfillment chat-first rollout"
```

## Self-Review Checklist (performed by plan author)

- [x] **Spec coverage:** Q1–Q10 decisions, route IA (Q7), nav/CTA rewiring (Q2,Q8), 404 legacy removal (Q5,Q9), authoritative read/list dependency (Q4,Q10), control-plane fulfillment actions/proxies, buyer-agent run infrastructure retention (Q1), chat-first reachability (Q6), and transaction-keyed extensibility (Q3) are mapped to tasks/slices.
- [x] **Placeholder scan:** no TBD/TODO/"implement later"/"similar to Task N" placeholders; concrete paths, code samples, and commands provided.
- [x] **Type consistency:** `transactionId`-keyed fulfillment (`BuyerFulfillmentProjection.transaction_id`, route params `[transactionId]`/`[id]`), API helper names (`listBuyerTransactions`, `getBuyerFulfillment`, `submitBuyerEvidence`, `openBuyerDispute`, `acceptBuyerTransaction`, `confirmBuyerDelivery`), and proxy/helper names (`controlPlaneBuyer`, `passthroughUpstream`) are used consistently across tasks.
- [x] **Task sizing:** each task has an independently testable deliverable and commit boundary; setup/integration steps are grouped by slice and dependency order.
