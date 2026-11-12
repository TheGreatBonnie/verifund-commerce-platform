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
    image_url: "https://example.com/macbook-air-m1.jpg",
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
    expect(parsed.product.image_url).toBe("https://example.com/macbook-air-m1.jpg");
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

  it("rejects drafts missing required budget", () => {
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
      expect(result.errors.join(" ")).not.toMatch(/delivery/i);
      expect(result.errors.join(" ")).not.toMatch(/warranty/i);
      expect(result.errors.join(" ")).not.toMatch(/must-have/i);
    }
  });

  it("allows optional delivery, warranty/returns, and must-have attributes", () => {
    const result = normalizeMandateDraft({
      quantity: 1,
      budgetAmount: "1500",
      budgetCurrency: "USD",
      budgetBasis: "per_unit",
      deliveryDeadline: "",
      warrantyReturns: "",
      mustHaveAttributes: "",
    });
    expect(result).toEqual({
      ok: true,
      mandate: {
        quantity: 1,
        budget: { ceiling_cents: 150000, currency: "USD", basis: "per_unit" },
        delivery_deadline: null,
        warranty_returns: null,
        must_have_attributes: [],
      },
    });
  });

  it("formats confirmed and cancelled receipts", () => {
    expect(formatMandateReceipt({ confirmed: true, mandate: { quantity: 1 } })).toMatch(/confirmed/i);
    expect(formatMandateReceipt({ confirmed: false, reason: "user_cancelled" })).toMatch(/no sourcing/i);
    expect(formatMandateReceipt({ confirmed: false, reason: "user_cancelled" })).toMatch(/no order/i);
  });
});
