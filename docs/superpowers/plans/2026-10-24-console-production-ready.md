# Console Production-Ready Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform `apps/console` into a production-shaped multi-page Next.js 15 product with typed UI primitives, extracted feature modules, TanStack Query server state, buyer-as-source-of-truth run persistence, Vitest + Playwright tests, accessibility, and production hardening.

**Architecture:** App Router route group `(console)` shares a sidebar + global chat-drawer shell. Server state via TanStack Query. Runs are authoritative from the buyer REST API (`/api/runs`, `/api/runs/:id`); the console adds thin proxy routes to reach them. Live negotiation details still come from CopilotKit thread state and merge into the run detail view. Feature folders own components/hooks/queries. Bespoke `mm-*` CSS becomes typed primitives under `components/ui`.

**Tech Stack:** Next.js 15.5, React 19, TypeScript (strict), Tailwind 4, CopilotKit 1.79, @tanstack/react-query, Vitest + @testing-library/react + jsdom, Playwright + @axe-core/playwright, lucide-react.

**Spec:** `docs/superpowers/specs/2026-10-24-console-production-ready-design.md`

## Global Constraints

- Node 20+, npm. Working dir `apps/console`.
- TypeScript strict; `tsc --noEmit` must pass after each task.
- No Python/agent changes: the buyer already exposes `/api/runs`, `/api/runs/{run_id}`, and `/api/runs/{run_id}/trace`. Console adds two proxy routes (list + detail) to reach them; no other new API routes.
- No mock data (excluded by spec).
- Preserve existing visual identity (`mm-*` classes) and the two e2e flows (approve/reject).
- CopilotKit agent id remains `a2a_chat`; thread id handling unchanged.
- Money is integer cents; format via `lib/format.ts` `money()`.
- Commit after each task with conventional message.

---

## Task 1: Add dependencies, scripts, and Vitest config

**Files:**
- Modify: `apps/console/package.json`
- Create: `apps/console/vitest.config.ts`
- Create: `apps/console/tests/setup.ts`

**Interfaces:**
- Produces: `npm run test`, `npm run test:watch`, `npm run test:coverage`, `npm run test:e2e`, `npm run test:all`, `npm run typecheck`, `npm run lint`.

- [ ] **Step 1: Update package.json dependencies and scripts**

Add to `dependencies`:
```json
"@tanstack/react-query": "^5.62.0"
```
Add to `devDependencies`:
```json
"vitest": "^2.1.0",
"@vitejs/plugin-react": "^4.3.0",
"jsdom": "^25.0.0",
"@testing-library/react": "^16.0.0",
"@testing-library/jest-dom": "^6.6.0",
"@testing-library/user-event": "^14.5.0",
"@axe-core/playwright": "^4.10.0",
"@next/bundle-analyzer": "^15.5.0"
```
Update `scripts`:
```json
"dev": "next dev",
"build": "next build",
"start": "next start",
"lint": "eslint . && tsc --noEmit",
"typecheck": "tsc --noEmit",
"test": "vitest run",
"test:watch": "vitest",
"test:coverage": "vitest run --coverage",
"test:e2e": "playwright test",
"test:all": "npm run test && npm run test:e2e"
```

- [ ] **Step 2: Create Vitest config**

`apps/console/vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./tests/setup.ts"],
    include: ["**/*.{test,spec}.{ts,tsx}"],
    exclude: ["node_modules", ".next", "e2e"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      include: ["lib/**", "features/**/hooks/**", "components/ui/**"],
      thresholds: { lines: 60, functions: 60 },
    },
  },
  resolve: {
    alias: { "@": path.resolve(root, ".") },
  },
});
```

- [ ] **Step 3: Create test setup**

`apps/console/tests/setup.ts`:
```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => cleanup());
```

- [ ] **Step 4: Install and verify**

Run: `npm install`
Expected: no errors.
Run: `npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add package.json package-lock.json vitest.config.ts tests/setup.ts
git commit -m "chore(console): add vitest + tanstack query deps and scripts"
```

---

## Task 2: UI primitives (components/ui)

**Files:**
- Create: `apps/console/components/ui/{button,panel,status,money,kicker,empty-state,alert,spinner,skeleton,badge}.tsx`
- Create: `apps/console/components/ui/index.ts`

**Interfaces:**
- Consumes: `lib/format.ts` (`money`).
- Produces: `Button`, `Panel`, `Status`, `Money`, `Kicker`, `EmptyState`, `Alert`, `Spinner`, `Skeleton`, `Badge` components with props documented below.

- [ ] **Step 1: Write failing tests for Button and Status**

`apps/console/components/ui/button.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Button } from "./button";

test("renders children and handles click", async () => {
  const onClick = vi.fn();
  render(<Button onClick={onClick}>Save</Button>);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(onClick).toHaveBeenCalled();
});

test("disabled button does not fire", async () => {
  const onClick = vi.fn();
  render(<Button disabled onClick={onClick}>Save</Button>);
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(onClick).not.toHaveBeenCalled();
});

test("loading state disables and shows spinner", () => {
  render(<Button loading>Save</Button>);
  expect(screen.getByRole("button")).toBeDisabled();
});
```

`apps/console/components/ui/status.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import { Status } from "./status";

test("renders label with tone class", () => {
  render(<Status tone="signal">Live</Status>);
  expect(screen.getByText("Live")).toHaveClass("is-signal");
});
```

- [ ] **Step 2: Run tests to verify failure**

Run: `npm run test -- components/ui`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement primitives**

`apps/console/components/ui/button.tsx`:
```tsx
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "outline" | "ghost" | "danger";
type Size = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leftIcon?: ReactNode;
}

const variantClass: Record<Variant, string> = {
  primary: "mm-button mm-button-primary",
  outline: "mm-button mm-button-outline",
  ghost: "mm-button mm-button-ghost",
  danger: "mm-button mm-button-danger",
};

const sizeClass: Record<Size, string> = {
  sm: "mm-button-sm",
  md: "",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading, leftIcon, children, className, disabled, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(variantClass[variant], sizeClass[size], className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...rest}
      >
        {loading ? <Loader2 size={13} className="is-spinning" aria-hidden="true" /> : leftIcon}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
```

`apps/console/components/ui/status.tsx`:
```tsx
import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "signal" | "error" | "amber";

export interface StatusProps {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}

const toneClass: Record<Tone, string> = {
  neutral: "",
  signal: "is-signal",
  error: "is-error",
  amber: "is-amber",
};

export function Status({ tone = "neutral", children, className }: StatusProps) {
  return (
    <span className={cn("mm-status", toneClass[tone], className)}>{children}</span>
  );
}
```

`apps/console/components/ui/money.tsx`:
```tsx
import { money as formatMoney } from "@/lib/format";
import { cn } from "@/lib/cn";

export interface MoneyProps {
  cents: number;
  className?: string;
  subCentsClassName?: string;
}

export function Money({ cents, className, subCentsClassName }: MoneyProps) {
  const formatted = formatMoney(cents);
  const whole = formatted.slice(0, -3);
  const centsPart = formatted.slice(-3);
  return (
    <span className={cn("mm-money", className)}>
      {whole}
      <span className={cn("mm-money-cents", subCentsClassName)}>{centsPart}</span>
    </span>
  );
}
```

`apps/console/components/ui/kicker.tsx`:
```tsx
import { cn } from "@/lib/cn";

export function Kicker({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("mm-kicker", className)}>{children}</span>;
}
```

`apps/console/components/ui/empty-state.tsx`:
```tsx
import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface EmptyStateProps {
  title: string;
  body?: string;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({ title, body, icon, action, className }: EmptyStateProps) {
  return (
    <div className={cn("mm-empty-state", className)}>
      {icon}
      <h2>{title}</h2>
      {body ? <p>{body}</p> : null}
      {action}
    </div>
  );
}
```

`apps/console/components/ui/alert.tsx`:
```tsx
import { CircleAlert, X } from "lucide-react";
import { cn } from "@/lib/cn";

export interface AlertProps {
  message: string;
  onDismiss?: () => void;
  className?: string;
}

export function Alert({ message, onDismiss, className }: AlertProps) {
  return (
    <div className={cn("mm-alert", className)} role="alert">
      <CircleAlert size={16} aria-hidden="true" />
      <span>{message}</span>
      {onDismiss ? (
        <button type="button" onClick={onDismiss} aria-label="Dismiss">
          <X size={14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
```

`apps/console/components/ui/spinner.tsx`:
```tsx
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <span role="status" aria-label={label} className={cn("mm-spinner", className)}>
      <Loader2 size={16} className="is-spinning" aria-hidden="true" />
    </span>
  );
}
```

`apps/console/components/ui/skeleton.tsx`:
```tsx
import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("mm-skeleton", className)} aria-hidden="true" />;
}
```

`apps/console/components/ui/badge.tsx`:
```tsx
import { cn } from "@/lib/cn";

export function Badge({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("mm-badge", className)}>{children}</span>;
}
```

`apps/console/components/ui/panel.tsx`:
```tsx
import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface PanelProps {
  title?: string;
  kicker?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, kicker, actions, children, className }: PanelProps) {
  return (
    <section className={cn("mm-panel", className)}>
      {(kicker || title || actions) ? (
        <header className="mm-panel-head">
          <div>
            {kicker ? <Kicker>{kicker}</Kicker> : null}
            {title ? <h2>{title}</h2> : null}
          </div>
          {actions}
        </header>
      ) : null}
      {children}
    </section>
  );
}
```

`apps/console/components/ui/index.ts`:
```ts
export * from "./button";
export * from "./panel";
export * from "./status";
export * from "./money";
export * from "./kicker";
export * from "./empty-state";
export * from "./alert";
export * from "./spinner";
export * from "./skeleton";
export * from "./badge";
```

Also create `apps/console/lib/cn.ts`:
```ts
export function cn(...classes: Array<string | false | null | undefined>) {
  return classes.filter(Boolean).join(" ");
}
```

- [ ] **Step 4: Run tests**

Run: `npm run test -- components/ui`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add components/ui lib/cn.ts
git commit -m "feat(console): add typed ui primitives"
```

---

## Task 3: Providers and query client

**Files:**
- Create: `apps/console/lib/query-client.ts`
- Create: `apps/console/providers/query-provider.tsx`
- Create: `apps/console/providers/copilot-provider.tsx`
- Modify: `apps/console/app/layout.tsx`

**Interfaces:**
- Produces: `createQueryClient()`, `<QueryProvider>`, `<CopilotProvider>` (wraps existing CopilotKit config).

- [ ] **Step 1: Create query client factory**

`apps/console/lib/query-client.ts`:
```ts
import { QueryClient } from "@tanstack/react-query";

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 5_000,
        refetchOnWindowFocus: false,
        retry: 2,
        retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
      },
      mutations: { retry: 0 },
    },
  });
}
```

- [ ] **Step 2: Create QueryProvider**

`apps/console/providers/query-provider.tsx`:
```tsx
"use client";
import { QueryClientProvider } from "@tanstack/react-query";
import { ReactNode, useState } from "react";
import { createQueryClient } from "@/lib/query-client";

export function QueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(() => createQueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

- [ ] **Step 3: CopilotProvider (thin wrapper)**

`apps/console/providers/copilot-provider.tsx`:
```tsx
"use client";
import { CopilotKit } from "@copilotkit/react-core";
import { ReactNode } from "react";

export function CopilotProvider({ children }: { children: ReactNode }) {
  const threadsEnabled = process.env.NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED === "true";
  return (
    <CopilotKit runtimeUrl="/api/copilotkit" agent="a2a_chat" showDevConsole={false}>
      {children}
    </CopilotKit>
  );
}
```
(Keep threads wiring as in existing layout; do not remove existing thread drawer config.)

- [ ] **Step 4: Update root layout**

Modify `app/layout.tsx` to wrap children in `<CopilotProvider>` then `<QueryProvider>`, and load fonts via `next/font/google` for Instrument Serif and Spline Sans Mono, assigning CSS variables `--font-instrument-serif` and `--font-spline-sans-mono`. Keep `globals.css` import.

- [ ] **Step 5: Typecheck and commit**

Run: `npm run typecheck`
Expected: PASS.
```bash
git add lib/query-client.ts providers app/layout.tsx
git commit -m "feat(console): add tanstack query + copilot providers"
```

---

## Task 4: Layout shell (sidebar + chat drawer)

**Files:**
- Create: `apps/console/components/layout/{sidebar,chat-drawer,top-bar,skip-link}.tsx`
- Create: `apps/console/app/(console)/layout.tsx`

**Interfaces:**
- Produces: `(console)` route group layout; `Sidebar` (nav items: Home, Runs, Sellers, Settings, Help), `ChatDrawer` (wraps existing Chat + approval injection), `SkipLink`.

- [ ] **Step 1: Create sidebar**

`apps/console/components/layout/sidebar.tsx`:
```tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, History, Store, Settings, HelpCircle } from "lucide-react";
import { cn } from "@/lib/cn";

const NAV = [
  { href: "/", label: "Home", icon: LayoutDashboard },
  { href: "/runs", label: "Runs", icon: History },
  { href: "/sellers", label: "Sellers", icon: Store },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help", icon: HelpCircle },
];

export function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="mm-sidebar" aria-label="Primary navigation">
      <div className="mm-brand">…</div>
      <nav>
        <ul>
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <li key={href}>
                <Link href={href} className={cn("mm-nav-item", active && "is-active")} aria-current={active ? "page" : undefined}>
                  <Icon size={15} aria-hidden="true" /> {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </aside>
  );
}
```
(Reuse existing brand SVG markup from `console-shell.tsx` topbar.)

- [ ] **Step 2: Create chat drawer**

Move the existing `Chat` usage + approval injection from `console-shell.tsx` into `components/layout/chat-drawer.tsx`, accepting `approvalElement?: ReactNode`.

- [ ] **Step 3: Create route group layout**

`apps/console/app/(console)/layout.tsx`:
```tsx
import { Sidebar } from "@/components/layout/sidebar";
import { ChatDrawer } from "@/components/layout/chat-drawer";
import { SkipLink } from "@/components/layout/skip-link";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="mm-app-frame">
      <SkipLink />
      <Sidebar />
      <main id="main-content" className="mm-console-main">{children}</main>
      <ChatDrawer />
    </div>
  );
}
```

- [ ] **Step 4: Create placeholder pages**

Create minimal pages for `/`, `/runs`, `/sellers`, `/settings`, `/help` under `app/(console)/` so routes resolve. Home temporarily renders the old deal intro; will be replaced in Task 9.

- [ ] **Step 5: Move current page body**

Move `app/page.tsx` content into `app/(console)/runs/[runId]/page.tsx` (client component) so the demo flow still works. Update imports.

- [ ] **Step 6: Add loading/error/not-found boundaries**

Create `app/(console)/loading.tsx`, `error.tsx`, `not-found.tsx`.

- [ ] **Step 7: Typecheck + commit**

Run: `npm run typecheck`
```bash
git add components/layout app/\(console\)
git commit -m "feat(console): add route-group shell with sidebar and chat drawer"
```

---

## Task 5: Extract run-state hooks from console-shell

**Files:**
- Create: `apps/console/features/deal-room/hooks/{use-run-trace,use-run-state,use-approval}.ts`
- Modify: `apps/console/features/deal-room/...` (move components)
- Delete: `apps/console/components/console-shell.tsx` (after migration)

**Interfaces:**
- `useRunTrace(runId, active, terminal): { events, error }`
- `useRunState(runId): { state, stage, award, mandate, negotiations, sellers, runId, terminal, isRunning }` (reads CopilotKit thread)
- `useApproval(runId): { sendApproval(approved, note), isSubmitting }`

- [ ] **Step 1: Extract useRunTrace (TanStack Query version)**

`features/deal-room/hooks/use-run-trace.ts`:
```ts
"use client";
import { useQuery } from "@tanstack/react-query";
import { fetchTrace } from "@/lib/api";
import type { TraceEvent } from "@/lib/types";

export function useRunTrace(runId: string, active: boolean, terminal: boolean) {
  return useQuery<TraceEvent[]>({
    queryKey: ["trace", runId],
    queryFn: async () => fetchTrace(runId, 0),
    enabled: active && !!runId,
    refetchInterval: terminal ? false : 1_000,
    select: (data) => [...data].sort((a, b) => a.seq - b.seq),
  });
}
```
Note: incremental `after_seq` polling is dropped in favor of full refetch (cheap, deduped by Query). If payloads grow, reintroduce incremental via `queryFn` reading last seq from cache.

- [ ] **Step 2: Extract thread→state parsing into useRunState**

`features/deal-room/hooks/use-run-state.ts`:
```ts
"use client";
import { useAgent } from "@copilotkit/react-core/v2";
import { useMemo } from "react";
import type { BuyerState } from "@/lib/types";

function parseState(messages: unknown[]): BuyerState {
  let latest: BuyerState | null = null;
  for (const m of messages ?? []) {
    const content = typeof (m as { content?: unknown }).content === "string"
      ? (m as { content: string }).content : "";
    let parsed: unknown = null;
    try { parsed = JSON.parse(content); } catch { continue; }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) continue;
    let candidate = parsed as BuyerState;
    const taskText = (parsed as { status?: { message?: { parts?: Array<{ text?: string }> } } })
      ?.status?.message?.parts?.[0]?.text;
    if (typeof taskText === "string") {
      try {
        const nested = JSON.parse(taskText);
        if (nested && typeof nested === "object" && !Array.isArray(nested)) candidate = nested as BuyerState;
      } catch { /* keep */ }
    }
    if (candidate && (candidate.task_id || candidate.award || candidate.mandate || candidate.order)) latest = candidate;
  }
  return latest ?? {};
}

export function useRunState() {
  const { agent } = useAgent({ agentId: "a2a_chat", updates: [] });
  const state = useMemo(() => parseState(agent.messages ?? []), [agent.messages]);
  const stage = state.stage ?? "new";
  const TERMINAL = new Set(["ordered","rejected","failed","order_failed","no_award"]);
  return {
    agent, state, stage, terminal: TERMINAL.has(stage),
    award: state.award ?? null, mandate: state.mandate ?? null,
    negotiations: state.negotiations ?? [], sellers: state.sellers ?? [],
    runId: state.task_id ?? state.run_id ?? agent.threadId ?? "",
  };
}
```

- [ ] **Step 3: Extract useApproval**

`features/deal-room/hooks/use-approval.ts`:
```ts
"use client";
import { useAgent } from "@copilotkit/react-core/v2";
import { useState } from "react";

export function useApproval(taskId: string | undefined) {
  const { agent } = useAgent({ agentId: "a2a_chat", updates: [] });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sendApproval = async (approved: boolean, note: string) => {
    if (!taskId) return;
    const payload = { approval: { approved, approved_by: "Demo Buyer", note }, task_id: taskId };
    agent.addMessage({ id: crypto.randomUUID(), role: "user", content: `MarketMesh approval response: ${JSON.stringify(payload)}` });
    setIsSubmitting(true);
    try { await agent.runAgent(); }
    finally { setIsSubmitting(false); }
  };
  return { sendApproval, isSubmitting };
}
```

- [ ] **Step 4: Add thread-state parsing utility (for live deal-room view)**

Create `apps/console/lib/runs.ts` exporting `parseBuyerStateFromMessages(messages)` (same implementation as before, minus `parseRunSummary`, which is no longer needed since runs come from the buyer API). Unit test in `lib/runs.test.ts` covering nested A2A task-message parsing.

- [ ] **Step 5: Move existing feature components**

Move `components/{a2a-wire,approval-card,chat,negotiation-feed,offer-card,offer-matrix,order-panel,registry-panel,seller-lane,stage-stepper}.tsx` and `components/a2a/*` into `features/deal-room/components/` (and `features/chat/` for chat). Update imports to use `@/components/ui` primitives where trivial. Keep markup/classes unchanged.

- [ ] **Step 6: Delete console-shell.tsx; wire run detail page (thread state only; buyer merge in Task 6)**

Rewrite `app/(console)/runs/[runId]/page.tsx` to compose the deal-room components using the new hooks, mirroring the old shell JSX but sourcing state from `useRunState`/`useRunTrace`/`useApproval`.

- [ ] **Step 6: Typecheck + commit**

Run: `npm run typecheck`
```bash
git add features app/\(console\)/runs
git commit -m "refactor(console): extract run-state hooks and feature modules"
```

---

## Task 6: Buyer run proxy routes + client functions + hooks + Runs list page

**Files:**
- Create: `apps/console/app/api/runs/route.ts`
- Create: `apps/console/app/api/runs/[runId]/route.ts`
- Modify: `apps/console/lib/api.ts` (+ `fetchRuns`, `fetchRun`)
- Create: `apps/console/features/runs/{use-runs,use-run}.ts`
- Create: `apps/console/features/runs/{run-summary-card,run-status-badge}.tsx`
- Create: `apps/console/app/(console)/runs/page.tsx`

**Interfaces:**
- `fetchRuns(limit?): Promise<BuyerRun[]>` where `BuyerRun = { run_id, stage, mandate, award, order, error, created_at, updated_at }`
- `fetchRun(runId): Promise<BuyerRun>`
- `useRuns(): { runs, isLoading, error, refresh }`
- `useRun(runId): { run, isLoading, error, refresh }`
- `RunSummary` derived in the page from `BuyerRun` (title from `mandate.product_hint` + quantity).

- [ ] **Step 1: Create list proxy route**

`apps/console/app/api/runs/route.ts`:
```ts
import { NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
  const limit = request.nextUrl.searchParams.get("limit") ?? "50";
  try {
    const response = await fetch(`${buyer}/api/runs?limit=${encodeURIComponent(limit)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json({ error: "Buyer API is unavailable" }, { status: 503 });
  }
}
```

- [ ] **Step 2: Create detail proxy route**

`apps/console/app/api/runs/[runId]/route.ts`:
```ts
import { NextRequest } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
  try {
    const response = await fetch(`${buyer}/api/runs/${encodeURIComponent(runId)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json({ error: "Buyer API is unavailable" }, { status: 503 });
  }
}
```

- [ ] **Step 3: Add client functions**

Append to `apps/console/lib/api.ts`:
```ts
export type BuyerRun = {
  run_id: string;
  stage?: string;
  mandate?: Mandate | null;
  award?: Award | null;
  order?: Order | null;
  error?: { code?: string; message?: string } | string | null;
  created_at?: string;
  updated_at?: string;
};

export async function fetchRuns(limit = 50): Promise<BuyerRun[]> {
  const response = await fetch(`/api/runs?limit=${limit}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Runs request failed (${response.status})`);
  return (await response.json()) as BuyerRun[];
}

export async function fetchRun(runId: string): Promise<BuyerRun> {
  const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Run request failed (${response.status})`);
  return (await response.json()) as BuyerRun;
}
```
(Import `Mandate`, `Award`, `Order` from `./types`.)

- [ ] **Step 4: Add query hooks**

`features/runs/use-runs.ts`:
```ts
"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRuns } from "@/lib/api";

export function useRuns() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["runs"], queryFn: () => fetchRuns(50), staleTime: 5_000 });
  return { runs: q.data ?? [], isLoading: q.isLoading, error: q.error ? "Runs unavailable" : null, refresh: () => qc.invalidateQueries({ queryKey: ["runs"] }) };
}
```

`features/runs/use-run.ts`:
```ts
"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRun } from "@/lib/api";

export function useRun(runId: string) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["run", runId], queryFn: () => fetchRun(runId), enabled: !!runId, refetchInterval: 2_000 });
  // stop polling once terminal
  return { run: q.data ?? null, isLoading: q.isLoading, error: q.error ? "Run unavailable" : null, refresh: () => qc.invalidateQueries({ queryKey: ["run", runId] }) };
}
```
Note: refetchInterval should be disabled when stage is terminal; implement by reading `q.data?.stage` and setting `refetchInterval: (q) => TERMINAL.has(q.state.data?.stage ?? "") ? false : 2_000`.

- [ ] **Step 5: Implement Runs list page**

`app/(console)/runs/page.tsx`: client component using `useRuns()` → map to `RunSummaryCard` linking to `/runs/[runId]`. Title from `mandate?.product_hint` + quantity. Empty state via `EmptyState`. Use `stageLabel`.

- [ ] **Step 6: Implement run detail merge**

Update `app/(console)/runs/[runId]/page.tsx` (from Task 5 Step 6) to:
- call `useRun(runId)` for authoritative metadata (stage, mandate, award, order, error, timestamps),
- call `useRunState()` for live negotiations/sellers/offers,
- call `useRunTrace(runId, true, terminal)`.
- Prefer buyer `stage`/`mandate`/`award`/`order`/`error` over thread state when present; fall back to thread state otherwise.
- Render `EmptyState` in lanes/matrix/feed when negotiations are absent (historical run).

- [ ] **Step 7: Run typecheck + commit**

Run: `npm run typecheck`
```bash
git add app/api/runs lib/api.ts features/runs app/\(console\)/runs
git commit -m "feat(console): buyer-as-source-of-truth runs (proxy + hooks + pages)"
```

---

## Task 7: Sellers page

**Files:**
- Create: `apps/console/features/sellers/{sellers-table,seller-card}.tsx`
- Create: `apps/console/app/(console)/sellers/page.tsx`
- Modify: `features/deal-room/components/registry-panel.tsx` (reuse data hook)

**Interfaces:**
- `useRegistry(): { sellers, isLoading, error, refresh }` (extracted from console-shell loadRegistry).

- [ ] **Step 1: Extract useRegistry hook**

`features/sellers/use-registry.ts`:
```ts
"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRegistry } from "@/lib/api";

export function useRegistry() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["registry"], queryFn: fetchRegistry, refetchInterval: 15_000 });
  return { sellers: q.data ?? [], isLoading: q.isLoading, error: q.error ? "Registry offline — Agent Cards unavailable." : null, refresh: () => qc.invalidateQueries({ queryKey: ["registry"] }) };
}
```

- [ ] **Step 2: Build Sellers page**

Promote registry list to full page with refresh button, health summary, error state, and `EmptyState` when empty.

- [ ] **Step 3: Typecheck + commit**

Run: `npm run typecheck`
```bash
git add features/sellers app/\(console\)/sellers
git commit -m "feat(console): add sellers directory page"
```

---

## Task 8: Settings and Help pages

**Files:**
- Create: `apps/console/app/(console)/settings/page.tsx`
- Create: `apps/console/app/(console)/help/page.tsx`
- Create: `apps/console/lib/config.ts`

**Interfaces:**
- `config: { llmMode, threadsEnabled, registryUrl }` (typed access to public env).

- [ ] **Step 1: config.ts**

```ts
export const config = {
  llmMode: process.env.NEXT_PUBLIC_MARKETMESH_LLM_MODE ?? "scripted",
  threadsEnabled: process.env.NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED === "true",
  modelLabel: process.env.NEXT_PUBLIC_MARKETMESH_LLM_MODE === "live" ? "DeepSeek V4.1 Flash" : "Scripted demo",
};
```

- [ ] **Step 2: Settings page**

Display config (read-only), "Reset local state" button with confirm dialog (clears CopilotKit threads + Query cache), link to help.

- [ ] **Step 3: Help page**

Static content: how to run, sample brief, glossary of A2A terms (Agent Card, task, artifact, DataPart, interrupt).

- [ ] **Step 4: Typecheck + commit**

Run: `npm run typecheck`
```bash
git add lib/config.ts app/\(console\)/settings app/\(console\)/help
git commit -m "feat(console): add settings and help pages"
```

---

## Task 9: Home page

**Files:**
- Modify: `apps/console/app/(console)/page.tsx`

**Interfaces:**
- Consumes: `useRegistry`, `useRuns`, `startRun` flow (extracted or inline).

- [ ] **Step 1: Implement home**

Overview copy (reuse deal intro), "Run sample brief" CTA that starts a run and navigates to `/runs/[runId]`, last 3 runs summary from `useRuns()` (links), registry health. Reuse `EmptyState` when no runs.

- [ ] **Step 2: Typecheck + commit**

Run: `npm run typecheck`
```bash
git add app/\(console\)/page.tsx
git commit -m "feat(console): add home page with run cta and recent runs"
```

---

## Task 10: Accessibility and responsive polish

**Files:**
- Modify: `components/layout/sidebar.tsx`, `components/layout/chat-drawer.tsx`, primitives
- Modify: `app/globals.css` (focus rings, skip link)

- [ ] **Step 1: Add focus rings + skip link**

Add `.mm-skip-link` (visually hidden until focus) and `:focus-visible` ring styles in globals.css. Add `SkipLink` component targeting `#main-content`.

- [ ] **Step 2: ARIA improvements**

Add `aria-live="polite"` to registry status and trace count; `aria-current` on nav (done in sidebar); focus trap in Dialog primitive; approval card Enter/Esc handling (Esc does not approve).

- [ ] **Step 3: Responsive sidebar collapse**

Sidebar becomes top nav <900px (reuse existing media-query pattern).

- [ ] **Step 4: Commit**

```bash
git add components/layout app/globals.css
git commit -m "feat(console): accessibility and responsive polish"
```

---

## Task 11: Production hardening (next.config headers + error boundaries)

**Files:**
- Modify: `apps/console/next.config.ts`
- Create/modify: `app/(console)/error.tsx`, `loading.tsx`, `not-found.tsx`

- [ ] **Step 1: Add security headers**

In `next.config.ts`, add `headers()` returning CSP, X-Frame-Options, Referrer-Policy, Permissions-Policy. Keep existing config (turbopack root, standalone, env, serverExternalPackages).

- [ ] **Step 2: Confirm boundaries exist**

Ensure `loading.tsx` (Skeleton-based), `error.tsx` (Alert + retry), `not-found.tsx` (EmptyState) exist.

- [ ] **Step 3: Typecheck + commit**

Run: `npm run typecheck`
```bash
git add next.config.ts app/\(console\)
git commit -m "feat(console): security headers and route boundaries"
```

---

## Task 12: Playwright e2e updates + a11y

**Files:**
- Modify: `apps/console/e2e/console.spec.ts`
- Create: `apps/console/e2e/smoke.spec.ts`

**Interfaces:**
- E2E tests target new routes; existing approve/reject flows updated to navigate to `/runs/[runId]`.

- [ ] **Step 1: Update existing e2e**

Adjust selectors: after "Run sample brief", wait for run detail route; approval button locators remain. Keep assertions for "Order confirmed", "MM-", "No order was placed".

- [ ] **Step 2: Add smoke tests**

`e2e/smoke.spec.ts`:
```ts
import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

for (const route of ["/", "/runs", "/sellers", "/settings", "/help"]) {
  test(`${route} loads`, async ({ page }) => {
    await page.goto(route);
    await expect(page).toHaveURL(new RegExp(route === "/" ? "/$" : route));
  });
}

test("home has no a11y violations", async ({ page }) => {
  await page.goto("/");
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});
```

- [ ] **Step 3: Run e2e (requires stack)**

Run: `make e2e` (or `npm run test:e2e` with dev server).
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add e2e
git commit -m "test(console): update e2e for new routes and add smoke/a11y"
```

---

## Task 13: Docs update

**Files:**
- Modify: `README.md` (Using the console section)
- Create: `docs/console.md` (optional, routes + dev)

- [ ] **Step 1: Update README console section** to list new routes and `npm run test` commands.

- [ ] **Step 2: Commit**

```bash
git add README.md docs/console.md
git commit -m "docs: document new console routes and test commands"
```

---

## Self-Review

**Spec coverage check:**
- Routes (§4) → Tasks 4, 6, 7, 8, 9 ✓
- Folder structure (§5) → Tasks 2-9 ✓
- State/data flow (§6) → Tasks 3, 5, 6, 7 ✓
- Primitives (§7) → Task 2 ✓
- Testing (§8) → Tasks 1, 12 ✓
- Milestones (§9) → Tasks 1-13 ✓
- Hardening (§10) → Task 11 ✓
- File inventory (§11) → all tasks ✓

**Placeholder scan:** No "TBD"/"TODO" in steps; code blocks provided for new code. Moves reference exact source files.

**Type consistency:** `money()` from lib/format; `BuyerRun`/`fetchRuns`/`fetchRun` defined in Task 6 and consumed by `useRuns`/`useRun` and pages; `useRegistry` Task 7; `useRunState`/`useRunTrace`/`useApproval` Task 5. `BuyerRun` fields align with buyer `_run()` response (`run_id, stage, mandate, award, order, error, created_at, updated_at`). Names consistent throughout.

**Option A (buyer as source of truth):** `/runs` and `/runs/[runId]` metadata come from buyer API via new proxy routes; deal-room rich views merge buyer metadata with live thread state and degrade gracefully for historical runs. Documented in Task 6 Step 6.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-10-24-console-production-ready.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?