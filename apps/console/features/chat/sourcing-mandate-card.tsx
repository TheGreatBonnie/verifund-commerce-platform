"use client";

import { useState } from "react";
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
          {args.product.image_url ? (
            <div className="mm-sourcing-mandate-product-image">
              <img
                src={args.product.image_url}
                alt={args.product.name}
                loading="lazy"
              />
            </div>
          ) : null}
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

      <label className="mm-note-field" htmlFor="sm-quantity">
        <span>Quantity</span>
        <input
          id="sm-quantity"
          type="number"
          min={1}
          value={draft.quantity}
          onChange={(e) => update({ quantity: Number(e.target.value) })}
        />
      </label>

      <label className="mm-note-field" htmlFor="sm-budget">
        <span>Budget ceiling/target (amount)</span>
        <input
          id="sm-budget"
          type="text"
          inputMode="decimal"
          value={draft.budgetAmount}
          onChange={(e) => update({ budgetAmount: e.target.value })}
          placeholder="e.g. 1500.00"
        />
      </label>

      <label className="mm-note-field" htmlFor="sm-currency">
        <span>Currency</span>
        <input
          id="sm-currency"
          type="text"
          value={draft.budgetCurrency}
          onChange={(e) => update({ budgetCurrency: e.target.value })}
        />
      </label>

      <label className="mm-note-field" htmlFor="sm-basis">
        <span>Budget basis</span>
        <select
          id="sm-basis"
          value={draft.budgetBasis}
          onChange={(e) => update({ budgetBasis: e.target.value as MandateDraft["budgetBasis"] })}
        >
          <option value="per_unit">Per unit</option>
          <option value="total">Total</option>
        </select>
      </label>

      <label className="mm-note-field" htmlFor="sm-deadline">
        <span>Delivery deadline (need by)</span>
        <input
          id="sm-deadline"
          type="date"
          value={draft.deliveryDeadline}
          onChange={(e) => update({ deliveryDeadline: e.target.value })}
        />
      </label>

      <label className="mm-note-field" htmlFor="sm-warranty">
        <span>Warranty & returns requirements</span>
        <textarea
          id="sm-warranty"
          rows={2}
          value={draft.warrantyReturns}
          onChange={(e) => update({ warrantyReturns: e.target.value })}
          placeholder="e.g. >=1 year warranty, 30-day returns"
        />
      </label>

      <label className="mm-note-field" htmlFor="sm-musthave">
        <span>Must-have attributes (comma or newline separated)</span>
        <textarea
          id="sm-musthave"
          rows={2}
          value={draft.mustHaveAttributes}
          onChange={(e) => update({ mustHaveAttributes: e.target.value })}
          placeholder="e.g. 8GB RAM, 256GB SSD, 13-inch"
        />
      </label>

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
