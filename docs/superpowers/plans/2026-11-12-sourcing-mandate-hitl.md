# Sourcing Mandate HITL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a required, blocking CopilotKit Human-in-the-Loop pause that collects and confirms a structured sourcing mandate (quantity, firm budget/target, delivery deadline, warranty/returns, must-have attributes) before the orchestrator hands off to the MarketMesh Buyer, while showing locked product/offer context read-only and stopping with no sourcing/order on cancel.

**Architecture:** Implement a frontend `useHumanInTheLoop` tool (`request_sourcing_mandate`) in the CopilotKit v2 chat (`apps/console/features/chat/chat.tsx`) that renders a mandate card/form, normalizes/validates user input with pure helpers, and returns a structured `respond(...)` payload (`confirmed: true|false` with mandate or cancel reason). Update the orchestrator instructions in `apps/console/app/api/copilotkit/[[...slug]]/route.ts` to require this tool at the mandate pause, proceed to `send_message_to_a2a_agent` for `MarketMesh Buyer` only on confirmed results, and stop on cancel without contacting the Buyer or placing orders.

**Tech Stack:** Next.js (App Router), React 19, TypeScript, `@copilotkit/react-core@1.79.0` / `@copilotkit/runtime@1.79.0` (v2 APIs: `useHumanInTheLoop`, `CopilotChat`), Zod, Vitest + React Testing Library + jsdom, existing `mm-*` console styles.

**Spec:** No separate spec file. Implements user-confirmed decisions from this session: **required HITL form (blocks until submit/cancel)**, **mandate fields only (locked product/offer context read-only)**, **cancel stops handoff (no sourcing/negotiation, no order placed)**. Behavioral context: agent pause response for `EX-MACBOOK-AIR` requiring quantity, budget ceiling/target, delivery deadline, warranty/returns, must-have attributes before MarketMesh Buyer handoff.

## Global Constraints

- Use CopilotKit v2 patterns already used in `apps/console/features/chat/chat.tsx` (`useHumanInTheLoop` with `render({ args, status, respond, result })`, statuses `inProgress`/`executing`/`complete`).
- **Required HITL gate:** the agent must not hand off to MarketMesh Buyer without a `confirmed: true` tool result containing a complete, structured mandate.
- **Mandate-only edits:** product/offer context passed in tool args is displayed read-only; no UI control may change SKU/offers/selection in this step.
- **Cancel stops handoff:** `confirmed: false`/`reason: "user_cancelled"` means report “not confirmed, no sourcing/no order placed” and do not call the Buyer or place any order.
- Never place an order from this flow; preserve and echo `task_id`/correlation identifiers unchanged when provided.
- Keep budget semantics explicit in the contract/result (numeric value, currency, and `basis: "per_unit" | "total"`); prefer cents (`budget_ceiling_cents`) for machine use.
- Follow existing console conventions (`mm-*` classes, Vitest/RTL test style, colocated feature files under `apps/console/features/chat/`).

---

## File Structure

- Create: `apps/console/features/chat/sourcing-mandate.ts` — pure contract/helpers: Zod args schema, result types, normalization/validation (prefill resolution, budget parsing to cents, mandate completeness), and `formatMandateSummary` for complete-state receipt. One responsibility: mandate data contract.
- Create: `apps/console/features/chat/sourcing-mandate-card.tsx` — presentational/interactive form component: renders locked product/offer context read-only, collects mandate fields, validates via helpers, calls `onSubmit(normalizedMandate)` or `onCancel()`. One responsibility: mandate collection UI.
- Modify: `apps/console/features/chat/chat.tsx` — register `request_sourcing_mandate` `useHumanInTheLoop` (args schema, render states, `respond` payloads, complete message) and wire `SourcingMandateCard`.
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts` — update orchestrator `instructions` to require the HITL tool at the pause and define confirmed/cancel handling.
- Test: `apps/console/tests/features/chat/sourcing-mandate.test.ts` — unit tests for schema/helpers/normalization.
- Test: `apps/console/tests/features/chat/sourcing-mandate-card.test.tsx` — component behavior (read-only context, prefill, validation, submit/cancel payloads).
- Test: `apps/console/tests/features/chat/chat.test.tsx` — registration and render-state behavior for `request_sourcing_mandate` (extend existing file).

### Task 1: Mandate contract and normalization helpers

**Files:**
- Create: `apps/console/features/chat/sourcing-mandate.ts`
- Test: `apps/console/tests/features/chat/sourcing-mandate.test.ts`

**Interfaces:**
- Produces: `sourcingMandateArgsSchema` (Zod) for HITL `parameters`.
- Produces types: `SourcingMandateArgs`, `SourcingMandate`, `SourcingMandateResult`.
- Produces: `defaultMandateDraft(args: SourcingMandateArgs): MandateDraft` (prefills quantity=1, budget hint from `defaults.budget_ceiling_cents`).
- Produces: `normalizeMandateDraft(draft: MandateDraft): { ok: true; mandate: SourcingMandate } | { ok: false; errors: string[] }` enforcing required fields and explicit budget semantics (`ceiling_cents` integer > 0, `currency`, `basis`).
- Produces: `formatMandateReceipt(result: unknown): string` returning a stable human summary for complete state (`confirmed` vs `cancelled/no sourcing/no order`).

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from "vitest";
import {
  defaultMandateDraft,
  formatMandateReceipt,
  normalizeMandateDraft,
  sourcingMandateArgsSchema,
} from "@/features/chat/sourcing-mandate";

const baseArgs = {
  task_id: "task-1",
  product: {
    sku: "EX-MACBOOK-AIR",
    name: "MacBook Air (M1)",
    offers: [
      { seller_name: "CircuitForge", unit_price_cents: 107999, currency: "USD", in_stock: true },
    ],
  },
  defaults: { quantity: 1, budget_ceiling_cents: 150000, currency: "USD" },
};

describe("sourcing mandate contract", () => {
  it("parses HITL args with locked product context and defaults", () => {
    const parsed = sourcingMandateArgsSchema.parse(baseArgs);
    expect(parsed.product.sku).toBe("EX-MACBOOK-AIR");
    expect(parsed.defaults?.budget_ceiling_cents).toBe(150000);
  });

  it("builds a draft prefilled from defaults", () => {
    const draft = defaultMandateDraft(sourcingMandateArgsSchema.parse(baseArgs));
    expect(draft.quantity).toBe(1);
    expect(draft.budgetAmount).toBe("1500.00");
    expect(draft.budgetCurrency).toBe("USD");
    expect(draft.budgetBasis).toBe("per_unit");
  });

  it("normalizes a complete draft into a structured mandate", () => {
    const result = normalizeMandateDraft({
      quantity: 2,
      budgetAmount: "1500",
      budgetCurrency: "USD",
      budgetBasis: "per_unit",
      deliveryDeadline: "2026-12-01",
      warrantyReturns: ">=1 year warranty, 30-day returns",
      mustHaveAttributes: "8GB RAM, 256GB SSD",
    });
    expect(result).toEqual({
      ok: true,
      mandate: {
        quantity: 2,
        budget: { ceiling_cents: 150000, currency: "USD", basis: "per_unit" },
        delivery_deadline: "2026-12-01",
        warranty_returns: ">=1 year warranty, 30-day returns",
        must_have_attributes: ["8GB RAM", "256GB SSD"],
      },
    });
  });

  it("rejects incomplete drafts with explicit errors", () => {
    const result = normalizeMandateDraft({
      quantity: 1,
      budgetAmount: "",
      budgetCurrency: "USD",
      budgetBasis: "per_unit",
      deliveryDeadline: "",
      warrantyReturns: "",
      mustHaveAttributes: "",
    });
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.errors.join(" ")).toMatch(/budget/i);
      expect(result.errors.join(" ")).toMatch(/delivery/i);
    }
  });

  it("formats confirmed and cancelled receipts", () => {
    expect(formatMandateReceipt({ confirmed: true, mandate: { quantity: 1 } })).toMatch(/confirmed/i);
    expect(formatMandateReceipt({ confirmed: false, reason: "user_cancelled" })).toMatch(/no sourcing/i);
    expect(formatMandateReceipt({ confirmed: false, reason: "user_cancelled" })).toMatch(/no order/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/console && npx vitest run tests/features/chat/sourcing-mandate.test.ts`
Expected: FAIL because `@/features/chat/sourcing-mandate` (and its exports) does not exist.

- [ ] **Step 3: Write minimal implementation**

```ts
import { z } from "zod";

export const sourcingMandateArgsSchema = z.object({
  task_id: z.string().optional(),
  message: z.string().optional(),
  product: z.object({
    sku: z.string(),
    name: z.string(),
    offers: z
      .array(
        z.object({
          seller_name: z.string(),
          unit_price_cents: z.number(),
          currency: z.string().default("USD"),
          in_stock: z.boolean().optional(),
        }),
      )
      .optional()
      .default([]),
  }),
  defaults: z
    .object({
      quantity: z.number().int().positive().default(1),
      budget_ceiling_cents: z.number().int().positive().optional(),
      currency: z.string().default("USD"),
    })
    .optional(),
});

export type SourcingMandateArgs = z.infer<typeof sourcingMandateArgsSchema>;

export type MandateDraft = {
  quantity: number;
  budgetAmount: string; // major units, e.g. "1500.00"
  budgetCurrency: string;
  budgetBasis: "per_unit" | "total";
  deliveryDeadline: string; // YYYY-MM-DD or ""
  warrantyReturns: string;
  mustHaveAttributes: string; // comma/newline separated input
};

export type SourcingMandate = {
  quantity: number;
  budget: { ceiling_cents: number; currency: string; basis: "per_unit" | "total" };
  delivery_deadline: string;
  warranty_returns: string;
  must_have_attributes: string[];
};

export type SourcingMandateResult =
  | { confirmed: true; task_id?: string; product: SourcingMandateArgs["product"]; mandate: SourcingMandate }
  | { confirmed: false; task_id?: string; reason: "user_cancelled" };

export function defaultMandateDraft(args: SourcingMandateArgs): MandateDraft {
  const cents = args.defaults?.budget_ceiling_cents;
  return {
    quantity: args.defaults?.quantity ?? 1,
    budgetAmount: typeof cents === "number" ? (cents / 100).toFixed(2) : "",
    budgetCurrency: args.defaults?.currency ?? "USD",
    budgetBasis: "per_unit",
    deliveryDeadline: "",
    warrantyReturns: "",
    mustHaveAttributes: "",
  };
}

function splitAttributes(value: string): string[] {
  return value
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function normalizeMandateDraft(
  draft: MandateDraft,
): { ok: true; mandate: SourcingMandate } | { ok: false; errors: string[] } {
  const errors: string[] = [];
  const quantity = Number(draft.quantity);
  if (!Number.isInteger(quantity) || quantity < 1) errors.push("Quantity must be at least 1.");

  const amount = Number(String(draft.budgetAmount).replace(/[^0-9.]/g, ""));
  if (!Number.isFinite(amount) || amount <= 0) errors.push("A firm budget ceiling/target is required.");
  const ceiling_cents = Math.round(amount * 100);

  if (!draft.deliveryDeadline) errors.push("A delivery deadline is required.");
  if (!draft.warrantyReturns.trim()) errors.push("Warranty and returns requirements are required.");
  const must_have_attributes = splitAttributes(draft.mustHaveAttributes);
  if (must_have_attributes.length === 0) errors.push("At least one must-have attribute is required.");

  if (errors.length) return { ok: false, errors };
  return {
    ok: true,
    mandate: {
      quantity,
      budget: { ceiling_cents, currency: draft.budgetCurrency || "USD", basis: draft.budgetBasis },
      delivery_deadline: draft.deliveryDeadline,
      warranty_returns: draft.warrantyReturns.trim(),
      must_have_attributes,
    },
  };
}

export function formatMandateReceipt(result: unknown): string {
  const r = result as { confirmed?: boolean; reason?: string } | null;
  if (r?.confirmed) return "Mandate confirmed. Handing off to MarketMesh Buyer for sourcing/negotiation.";
  if (r?.confirmed === false)
    return "Mandate not confirmed. No sourcing started and no order will be placed.";
  return "Mandate decision recorded.";
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/console && npx vitest run tests/features/chat/sourcing-mandate.test.ts`
Expected: PASS (all tests in this file).

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/sourcing-mandate.ts apps/console/tests/features/chat/sourcing-mandate.test.ts
git commit -m "feat(chat): add sourcing mandate contract and normalization helpers"
```

### Task 2: Sourcing mandate card UI (read-only context + form)

**Files:**
- Create: `apps/console/features/chat/sourcing-mandate-card.tsx`
- Test: `apps/console/tests/features/chat/sourcing-mandate-card.test.tsx`

**Interfaces:**
- Consumes: `sourcingMandateArgsSchema`/`SourcingMandateArgs`, `defaultMandateDraft`, `normalizeMandateDraft`, `SourcingMandate` from `apps/console/features/chat/sourcing-mandate.ts`.
- Produces: `SourcingMandateCard` component with props `{ args: SourcingMandateArgs; onSubmit: (mandate: SourcingMandate) => void | Promise<void>; onCancel: () => void | Promise<void> }`.
- Behavior: renders locked `args.product` (SKU/name) and `args.product.offers` read-only; editable inputs for quantity, budget amount/currency/basis, delivery deadline, warranty/returns, must-haves (prefilled via `defaultMandateDraft`); submit validates and calls `onSubmit(normalized)`; cancel calls `onCancel()`; shows validation errors; disables actions while pending.

- [ ] **Step 1: Write the failing test**

```tsx
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourcingMandateCard } from "@/features/chat/sourcing-mandate-card";
import { sourcingMandateArgsSchema } from "@/features/chat/sourcing-mandate";

const args = sourcingMandateArgsSchema.parse({
  task_id: "task-1",
  message: "Confirm mandate before sourcing.",
  product: {
    sku: "EX-MACBOOK-AIR",
    name: "MacBook Air (M1)",
    offers: [
      { seller_name: "CircuitForge", unit_price_cents: 107999, currency: "USD", in_stock: true },
      { seller_name: "Aurora Supply", unit_price_cents: 113999, currency: "USD", in_stock: true },
    ],
  },
  defaults: { quantity: 1, budget_ceiling_cents: 150000, currency: "USD" },
});

describe("SourcingMandateCard", () => {
  it("shows locked product and offers read-only with prefilled defaults", () => {
    render(<SourcingMandateCard args={args} onSubmit={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText(/EX-MACBOOK-AIR/)).toBeInTheDocument();
    expect(screen.getByText(/MacBook Air \(M1\)/)).toBeInTheDocument();
    expect(screen.getByText(/CircuitForge/)).toBeInTheDocument();
    expect(screen.getByText(/Aurora Supply/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("1")).toBeInTheDocument(); // quantity
    expect(screen.getByDisplayValue("1500.00")).toBeInTheDocument(); // budget hint
    expect(screen.queryByRole("button", { name: /change offer/i })).not.toBeInTheDocument();
  });

  it("submits a normalized confirmed mandate", async () => {
    const onSubmit = vi.fn();
    render(<SourcingMandateCard args={args} onSubmit={onSubmit} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/delivery deadline/i), { target: { value: "2026-12-01" } });
    fireEvent.change(screen.getByLabelText(/warranty/i), { target: { value: "1 year warranty, 30-day returns" } });
    fireEvent.change(screen.getByLabelText(/must-have/i), { target: { value: "8GB RAM, 256GB SSD" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm.*buyer/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        quantity: 1,
        budget: { ceiling_cents: 150000, currency: "USD", basis: "per_unit" },
        delivery_deadline: "2026-12-01",
        must_have_attributes: ["8GB RAM", "256GB SSD"],
      }),
    );
  });

  it("cancels without submitting a mandate", () => {
    const onCancel = vi.fn();
    const onSubmit = vi.fn();
    render(<SourcingMandateCard args={args} onSubmit={onSubmit} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("blocks submit and shows errors when required fields are missing", async () => {
    const onSubmit = vi.fn();
    render(<SourcingMandateCard args={{ ...args, defaults: { quantity: 1, currency: "USD" } }} onSubmit={onSubmit} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/budget/i), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm.*buyer/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/budget/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/console && npx vitest run tests/features/chat/sourcing-mandate-card.test.tsx`
Expected: FAIL because `@/features/chat/sourcing-mandate-card` does not exist.

- [ ] **Step 3: Write minimal implementation**

```tsx
"use client";

import { useMemo, useState } from "react";
import { LockKeyhole } from "lucide-react";
import {
  defaultMandateDraft,
  normalizeMandateDraft,
  type MandateDraft,
  type SourcingMandate,
  type SourcingMandateArgs,
} from "@/features/chat/sourcing-mandate";

function formatMoney(cents: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

type Props = {
  args: SourcingMandateArgs;
  onSubmit: (mandate: SourcingMandate) => void | Promise<void>;
  onCancel: () => void | Promise<void>;
};

export function SourcingMandateCard({ args, onSubmit, onCancel }: Props) {
  const [draft, setDraft] = useState<MandateDraft>(() => defaultMandateDraft(args));
  const [errors, setErrors] = useState<string[]>([]);
  const [pending, setPending] = useState<"submit" | "cancel" | null>(null);

  const offers = args.product.offers ?? [];
  const update = (patch: Partial<MandateDraft>) => setDraft((d) => ({ ...d, ...patch }));

  const submit = async () => {
    const normalized = normalizeMandateDraft(draft);
    if (!normalized.ok) {
      setErrors(normalized.errors);
      return;
    }
    setErrors([]);
    setPending("submit");
    try {
      await onSubmit(normalized.mandate);
    } finally {
      setPending(null);
    }
  };

  const cancel = async () => {
    setPending("cancel");
    try {
      await onCancel();
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="mm-approval" aria-labelledby="sourcing-mandate-title" aria-live="polite">
      <header className="mm-approval-head">
        <div>
          <p className="mm-kicker">
            <LockKeyhole size={12} aria-hidden="true" /> Sourcing mandate
          </p>
          <h2 id="sourcing-mandate-title">Confirm mandate before sourcing</h2>
          <p className="mm-approval-prompt">
            {args.message ?? "Confirm details so the Buyer can source and negotiate. No order will be placed."}
          </p>
        </div>
        <span className="mm-approval-flag">Required</span>
      </header>

      <div className="mm-approval-award" aria-label="Locked product context">
        <div>
          <span className="mm-kicker">Product (locked)</span>
          <strong>{args.product.name}</strong>
          <div className="mm-mono-note">{args.product.sku}</div>
        </div>
        <div>
          <span className="mm-kicker">Known offers (read-only)</span>
          <ul>
            {offers.map((o) => (
              <li key={o.seller_name}>
                {o.seller_name} · {formatMoney(o.unit_price_cents, o.currency)}
                {o.in_stock === false ? " · unavailable" : " · in stock"}
              </li>
            ))}
            {offers.length === 0 ? <li>No offers listed</li> : null}
          </ul>
        </div>
      </div>

      <div className="mm-note-field">
        <label htmlFor="sm-quantity"><span>Quantity</span></label>
        <input id="sm-quantity" type="number" min={1} value={draft.quantity}
          onChange={(e) => update({ quantity: Number(e.target.value) })} />
      </div>

      <div className="mm-note-field">
        <label htmlFor="sm-budget"><span>Budget ceiling/target (amount)</span></label>
        <input id="sm-budget" type="text" inputMode="decimal" value={draft.budgetAmount}
          onChange={(e) => update({ budgetAmount: e.target.value })} placeholder="e.g. 1500.00" />
      </div>

      <div className="mm-note-field">
        <label htmlFor="sm-currency"><span>Currency</span></label>
        <input id="sm-currency" type="text" value={draft.budgetCurrency}
          onChange={(e) => update({ budgetCurrency: e.target.value })} />
      </div>

      <div className="mm-note-field">
        <label htmlFor="sm-basis"><span>Budget basis</span></label>
        <select id="sm-basis" value={draft.budgetBasis}
          onChange={(e) => update({ budgetBasis: e.target.value as MandateDraft["budgetBasis"] })}>
          <option value="per_unit">Per unit</option>
          <option value="total">Total</option>
        </select>
      </div>

      <div className="mm-note-field">
        <label htmlFor="sm-deadline"><span>Delivery deadline (need by)</span></label>
        <input id="sm-deadline" type="date" value={draft.deliveryDeadline}
          onChange={(e) => update({ deliveryDeadline: e.target.value })} />
      </div>

      <div className="mm-note-field">
        <label htmlFor="sm-warranty"><span>Warranty & returns requirements</span></label>
        <textarea id="sm-warranty" rows={2} value={draft.warrantyReturns}
          onChange={(e) => update({ warrantyReturns: e.target.value })}
          placeholder="e.g. >=1 year warranty, 30-day returns" />
      </div>

      <div className="mm-note-field">
        <label htmlFor="sm-musthave"><span>Must-have attributes (comma or newline separated)</span></label>
        <textarea id="sm-musthave" rows={2} value={draft.mustHaveAttributes}
          onChange={(e) => update({ mustHaveAttributes: e.target.value })}
          placeholder="e.g. 8GB RAM, 256GB SSD, 13-inch" />
      </div>

      {errors.length ? (
        <p className="mm-chat-approval-result" role="alert">{errors.join(" ")}</p>
      ) : null}

      <div className="mm-approval-actions">
        <button type="button" className="mm-button mm-button-signal" onClick={submit} disabled={pending !== null}>
          {pending === "submit" ? "Confirming…" : "Confirm & send to Buyer"}
        </button>
        <button type="button" className="mm-button mm-button-outline-danger" onClick={cancel} disabled={pending !== null}>
          {pending === "cancel" ? "Cancelling…" : "Cancel"}
        </button>
      </div>
    </section>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/console && npx vitest run tests/features/chat/sourcing-mandate-card.test.tsx`
Expected: PASS. If any label text does not match, adjust labels in the component to include the words used by queries (`/budget/i`, `/delivery deadline/i`, `/warranty/i`, `/must-have/i`, `/confirm.*buyer/i`, `/cancel/i`) without changing behavior.

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/sourcing-mandate-card.tsx apps/console/tests/features/chat/sourcing-mandate-card.test.tsx
git commit -m "feat(chat): add sourcing mandate HITL card"
```

### Task 3: Register `request_sourcing_mandate` in chat

**Files:**
- Modify: `apps/console/features/chat/chat.tsx`
- Test: `apps/console/tests/features/chat/chat.test.tsx`

**Interfaces:**
- Consumes: `sourcingMandateArgsSchema`, `formatMandateReceipt` from `apps/console/features/chat/sourcing-mandate.ts`; `SourcingMandateCard` from `apps/console/features/chat/sourcing-mandate-card.tsx`.
- Produces: `useHumanInTheLoop` registration `name: "request_sourcing_mandate"`, `agentId: "marketmesh_orchestrator"`, `parameters: sourcingMandateArgsSchema`, render states:
  - `inProgress` → preparing status (`role="status"`).
  - `executing && respond` → `<SourcingMandateCard args={args} onSubmit={(mandate)=>respond({confirmed:true, task_id: args.task_id, product: args.product, mandate})} onCancel={()=>respond({confirmed:false, task_id: args.task_id, reason:"user_cancelled"})} />`.
  - `complete` → `<p role="status">` with `formatMandateReceipt(parsedResult)` (defensive parse; cancelled path must mention no sourcing/no order).

- [ ] **Step 1: Write the failing test**

Add to `apps/console/tests/features/chat/chat.test.tsx`:

```tsx
describe("chat sourcing mandate", () => {
  beforeEach(() => {
    hooks.useHumanInTheLoop.mockClear();
  });

  const mandateTool = () =>
    hooks.useHumanInTheLoop.mock.calls.find(
      ([tool]) => tool.name === "request_sourcing_mandate",
    );

  const args = {
    task_id: "task-1",
    message: "Confirm mandate before sourcing.",
    product: {
      sku: "EX-MACBOOK-AIR",
      name: "MacBook Air (M1)",
      offers: [{ seller_name: "CircuitForge", unit_price_cents: 107999, currency: "USD", in_stock: true }],
    },
    defaults: { quantity: 1, budget_ceiling_cents: 150000, currency: "USD" },
  };

  it("registers request_sourcing_mandate as a blocking HITL tool", () => {
    renderChat();
    const call = mandateTool();
    expect(call?.[0]).toMatchObject({
      name: "request_sourcing_mandate",
      agentId: "marketmesh_orchestrator",
    });
    expect(call?.[0].parameters).toBeTruthy();
    expect(call?.[0].render).toEqual(expect.any(Function));
  });

  it("renders a preparing state while in progress", () => {
    renderChat();
    const call = mandateTool();
    render(call![0].render({ args, status: "inProgress" }));
    expect(screen.getByRole("status")).toHaveTextContent(/preparing.*mandate/i);
  });

  it("responds with confirmed mandate on submit and cancelled on cancel", () => {
    renderChat();
    const call = mandateTool();
    const respond = vi.fn();
    const { rerender } = render(
      call![0].render({ args, status: "executing", respond }),
    );
    // form is rendered; cancel path must be wired
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(respond).toHaveBeenCalledWith(
      expect.objectContaining({ confirmed: false, task_id: "task-1", reason: "user_cancelled" }),
    );

    const respond2 = vi.fn();
    rerender(call![0].render({ args, status: "executing", respond: respond2 }));
    fireEvent.change(screen.getByLabelText(/delivery deadline/i), { target: { value: "2026-12-01" } });
    fireEvent.change(screen.getByLabelText(/warranty/i), { target: { value: "1y warranty, 30d returns" } });
    fireEvent.change(screen.getByLabelText(/must-have/i), { target: { value: "8GB RAM" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm.*buyer/i }));
    expect(respond2).toHaveBeenCalledWith(
      expect.objectContaining({
        confirmed: true,
        task_id: "task-1",
        product: expect.objectContaining({ sku: "EX-MACBOOK-AIR" }),
        mandate: expect.objectContaining({ quantity: 1 }),
      }),
    );
  });

  it("reports confirmed and cancelled outcomes when complete", () => {
    renderChat();
    const call = mandateTool();
    const { rerender } = render(
      call![0].render({ args, status: "complete", result: JSON.stringify({ confirmed: true }) }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/confirmed/i);
    rerender(
      call![0].render({
        args,
        status: "complete",
        result: JSON.stringify({ confirmed: false, reason: "user_cancelled" }),
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/no sourcing/i);
    expect(screen.getByRole("status")).toHaveTextContent(/no order/i);
  });
});
```

(Place this `describe` block near the other HITL-related describes in the file; keep existing imports/mocks intact.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/console && npx vitest run tests/features/chat/chat.test.tsx -t "sourcing mandate"`
Expected: FAIL because `request_sourcing_mandate` is not registered (tool lookup returns undefined).

- [ ] **Step 3: Write minimal implementation**

In `apps/console/features/chat/chat.tsx`:

1. Add imports (near other chat/approval imports):
```tsx
import { SourcingMandateCard } from "./sourcing-mandate-card";
import {
  formatMandateReceipt,
  sourcingMandateArgsSchema,
} from "./sourcing-mandate";
```

2. Register the HITL tool inside `Chat` (alongside other `useHumanInTheLoop` registrations), e.g. before or after award approval block:
```tsx
useHumanInTheLoop(
  {
    agentId: "marketmesh_orchestrator",
    name: "request_sourcing_mandate",
    description:
      "Collect and confirm a sourcing mandate before handing off to MarketMesh Buyer. " +
      "Show locked product/offers read-only and collect quantity, firm budget/target, delivery deadline, " +
      "warranty/returns, and must-have attributes. Block until the user submits or cancels.",
    parameters: sourcingMandateArgsSchema,
    render: ({ args, status, respond, result }) => {
      if (status === "inProgress") {
        return (
          <div className="mm-chat-approval-pending" role="status">
            Preparing sourcing mandate…
          </div>
        );
      }

      if (status === "executing" && respond) {
        return (
          <div className="mm-chat-approval">
            <SourcingMandateCard
              args={args as any}
              onSubmit={(mandate) =>
                respond({
                  confirmed: true,
                  task_id: (args as any).task_id,
                  product: (args as any).product,
                  mandate,
                })
              }
              onCancel={() =>
                respond({
                  confirmed: false,
                  task_id: (args as any).task_id,
                  reason: "user_cancelled",
                })
              }
            />
          </div>
        );
      }

      if (status === "complete") {
        let parsed: unknown = result;
        try {
          parsed = typeof result === "string" ? JSON.parse(result) : result;
        } catch {
          parsed = result;
        }
        return (
          <p className="mm-chat-approval-result" role="status">
            {formatMandateReceipt(parsed)}
          </p>
        );
      }

      return null;
    },
  },
  [],
);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/console && npx vitest run tests/features/chat/chat.test.tsx -t "sourcing mandate"`
Expected: PASS for the new sourcing-mandate tests. Then run full chat tests: `cd apps/console && npx vitest run tests/features/chat/chat.test.tsx`
Expected: PASS (no regressions).

- [ ] **Step 5: Commit**

```bash
git add apps/console/features/chat/chat.tsx apps/console/tests/features/chat/chat.test.tsx
git commit -m "feat(chat): register sourcing mandate HITL pause"
```

### Task 4: Require the HITL mandate gate in orchestrator instructions

**Files:**
- Modify: `apps/console/app/api/copilotkit/[[...slug]]/route.ts`

**Interfaces:**
- Consumes: existing orchestration flow and tools (`send_message_to_a2a_agent`, `mediate_seller_call`, `request_award_approval`, etc.).
- Produces: updated `instructions` text for `a2aMiddlewareAgent` that (a) requires calling `request_sourcing_mandate` at the pause when mandate is incomplete/ambiguous before any Buyer handoff, (b) treats tool args product/offers as read-only context, (c) on `confirmed: true` sends a complete brief (grounded product context + mandate) to `agentName="MarketMesh Buyer"` and does not place orders, (d) on `confirmed: false`/`user_cancelled` stops handoff and reports “not confirmed, no sourcing/negotiation started, no order placed” without contacting the Buyer, (e) does not infer confirmation from chat.

- [ ] **Step 1: Write the failing test**

Create a lightweight guard test by extending `apps/console/tests/app/api/copilotkit` if it exists; if not, add a targeted assertion in this task as a scriptable check. Preferred: add `apps/console/tests/app/api/copilotkit/route-instructions.test.ts` that reads the route source to assert key rules (keeps it fast and avoids booting the runtime):

```ts
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const routePath = path.resolve(__dirname, "../../../../app/api/copilotkit/[[...slug]]/route.ts");
const source = fs.readFileSync(routePath, "utf8");

describe("orchestrator sourcing mandate instructions", () => {
  it("requires the request_sourcing_mandate HITL gate before Buyer handoff", () => {
    expect(source).toContain("request_sourcing_mandate");
    expect(source).toMatch(/confirmed\s*===?\s*true|confirmed.*true/i);
    expect(source).toMatch(/confirmed\s*===?\s*false|user_cancelled/i);
  });

  it("states cancel stops handoff with no sourcing and no order", () => {
    expect(source).toMatch(/no sourcing/i);
    expect(source).toMatch(/no order/i);
    expect(source).toMatch(/do not contact the Buyer|without contacting the Buyer/i);
  });

  it("keeps mandate context read-only and forbids order placement", () => {
    expect(source).toMatch(/read-only/i);
    expect(source).toMatch(/Do not place an order|do not place an order/);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/console && npx vitest run tests/app/api/copilotkit/route-instructions.test.ts`
Expected: FAIL because the current instructions do not reference `request_sourcing_mandate` / the new cancel-stop wording.

- [ ] **Step 3: Write minimal implementation**

In `apps/console/app/api/copilotkit/[[...slug]]/route.ts`, within the `instructions` template string, replace/augment `# 5. Product Discovery and Negotiation Handoff` so it includes the HITL gate. Keep all other sections intact. Use this exact block for section 5:

```text
  # 5. Product Discovery and Negotiation Handoff

  Use search_marketplace_products only for discovery requests
  (find, search, browse). Extract constraints: "under $1500"
  becomes max_unit_price_cents=150000, a per-unit ceiling.
  Put product or category terms in query; do not pass filler
  words. Never route discovery to send_message_to_a2a_agent
  or to a seller.

  Present only returned products and SKUs. Use match_rationale
  only for returned fields. When the user asks to negotiate
  for a shown card, read its SKU, name, price, and offers from
  the message; do not re-search unless constraints changed.

  Confirm the mandate before sourcing. Ask only for missing or
  ambiguous fields: quantity (default 1), budget ceiling or
  target, delivery deadline, warranty and returns, must-haves.
  Never re-ask a stated field; a complete brief starts without
  extra questions.

  At the sourcing pause (product context grounded, before any
  Buyer handoff), call the frontend request_sourcing_mandate
  HITL tool with the locked product and known offers as
  read-only context plus any known defaults/hints and task_id.
  Do not edit the product/offer selection in this step and do
  not collect these fields via plain chat when the tool is
  required. Wait for the tool result.

  - If the result is confirmed === true with a complete
    mandate: call send_message_to_a2a_agent with
    agentName="MarketMesh Buyer" and a task containing the
    confirmed mandate plus the grounded product context (SKU,
    name, unit price, offers). Stay in the current thread; do
    not navigate, place an order, or create an award outcome.
    request_award_approval and Verifund HITL approvals remain
    mandatory.
  - If the result is confirmed === false or reason is
    "user_cancelled": stop the handoff and report that the
    mandate was not confirmed, no sourcing/negotiation started,
    and no order will be placed. Do not contact the Buyer.

  Never infer confirmation without the tool result.
```

(Ensure the wording contains `read-only`, `no sourcing`, `no order`, and `Do not contact the Buyer` as asserted.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/console && npx vitest run tests/app/api/copilotkit/route-instructions.test.ts`
Expected: PASS. Then run TypeScript check for console: `cd apps/console && npm run typecheck`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/console/app/api/copilotkit/[[...slug]]/route.ts apps/console/tests/app/api/copilotkit/route-instructions.test.ts
git commit -m "feat(orchestrator): require sourcing mandate HITL gate before buyer handoff"
```

### Task 5: End-to-end verification and polish

**Files:**
- Modify (only if needed): `apps/console/features/chat/sourcing-mandate-card.tsx`, `apps/console/features/chat/chat.tsx`, `apps/console/features/chat/sourcing-mandate.ts`
- Test (if fixes needed): `apps/console/tests/features/chat/sourcing-mandate*.test.ts*`, `apps/console/tests/features/chat/chat.test.tsx`

**Interfaces:**
- Consumes: all interfaces produced in Tasks 1–4.
- Produces: a passing console test/typecheck suite for touched areas and a manually verifiable pause flow.

- [ ] **Step 1: Run the focused automated suite**

Run:
```bash
cd apps/console && npx vitest run \
  tests/features/chat/sourcing-mandate.test.ts \
  tests/features/chat/sourcing-mandate-card.test.tsx \
  tests/features/chat/chat.test.tsx \
  tests/app/api/copilotkit/route-instructions.test.ts
```
Expected: PASS. If any assertion fails due to wording/label drift, fix the implementation or test to match the intended behavior (confirmed/cancel semantics and read-only context) — do not weaken the constraints.

- [ ] **Step 2: Run typecheck**

Run: `cd apps/console && npm run typecheck`
Expected: PASS with no new errors.

- [ ] **Step 3: Manual verification (dev flow)**

Run: `cd apps/console && npm run dev` (with the usual local agents/runtime configured for the environment).
Verify:
- Trigger a negotiate/sourcing flow where mandate is incomplete (e.g. product locked as `EX-MACBOOK-AIR` with offers shown) → `request_sourcing_mandate` renders (preparing → form), blocking progression.
- Locked product/offer context is visible and not editable.
- Quantity defaults to 1 and budget hint prefills when provided (e.g. $1500.00); submitting with all required fields responds `confirmed: true` with structured mandate and the agent proceeds to Buyer handoff only after that result.
- Cancel responds `confirmed: false` (`user_cancelled`) and the agent reports no sourcing/negotiation and no order placed, without contacting the Buyer.

- [ ] **Step 4: Commit any verification fixes**

```bash
git add apps/console/features/chat apps/console/tests apps/console/app/api/copilotkit/[[...slug]]/route.ts
git commit -m "test(chat): verify sourcing mandate HITL pause behavior"
```
(Only if there are changes; otherwise skip this commit.)

## Self-Review

- **Spec coverage:** required blocking HITL (Task 3, Task 4) ✓; mandate fields quantity/budget/deadline/warranty-returns/must-haves collected and normalized (Tasks 1–2) ✓; product/offer context read-only (Task 2 UI, Task 4 instructions) ✓; cancel stops handoff with no sourcing/no order (Tasks 1–4) ✓; no order placement and Buyer handoff only on confirmed result (Task 4) ✓.
- **Placeholder scan:** no TBD/TODO/“implement later”/vague steps; tasks include concrete code and exact commands.
- **Type consistency:** `SourcingMandateArgs`/`SourcingMandate`/`SourcingMandateResult` and helpers defined in Task 1 are the ones consumed by Tasks 2–3; tool name `request_sourcing_mandate` and result fields `confirmed`, `task_id`, `product`, `mandate`, `reason: "user_cancelled"` are consistent across UI, tests, and orchestrator instructions.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-11-12-sourcing-mandate-hitl.md`. Two execution options:

1. **Subagent-Driven (recommended)** - dispatch a fresh subagent per task, review between tasks, fast iteration
2. **Inline Execution** - execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
