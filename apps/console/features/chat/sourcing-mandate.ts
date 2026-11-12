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
