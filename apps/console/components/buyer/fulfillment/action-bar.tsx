"use client";

import { useState } from "react";

import { mapActionError } from "@/lib/buyer-action-errors";
import { BuyerConfirmDialog } from "../shared/buyer-confirm-dialog";
import { labelize } from "../shared/format";
import { BuyerSuccessMessage } from "../shared/buyer-page-states";

type Pending = "accept" | "delivery";

export function ActionBar({
  allowedActions,
  blockers,
  nextAction,
  onAccept,
  onConfirmDelivery,
}: {
  allowedActions: string[];
  blockers?: Array<{ code: string; message?: string }> | null;
  nextAction?: string | null;
  onAccept: () => Promise<void>;
  onConfirmDelivery: () => Promise<void>;
}) {
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const canAccept = allowedActions.includes("accept");
  const canConfirm =
    allowedActions.includes("delivery_confirmed") ||
    allowedActions.includes("confirm_delivery");

  const reasons = (blockers ?? []).map((blocker) => blocker.message ?? blocker.code);
  if (!canAccept && nextAction) reasons.push(`Next: ${labelize(nextAction)}`);
  const reason = reasons.join(" ");

  const dialog =
    pending === "accept"
      ? {
          title: "Accept offer",
          body: "This accepts the agreed commercial terms. It cannot be undone from this page.",
          confirmLabel: "Confirm acceptance",
        }
      : pending === "delivery"
        ? {
            title: "Confirm delivery",
            body: "Confirm that the goods were received as described. Payout authority stays with the chat approval flow.",
            confirmLabel: "Confirm delivery action",
          }
        : null;

  const execute = async () => {
    if (!pending) return;
    const kind = pending;
    setPending(null);
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      if (kind === "accept") {
        await onAccept();
        setSuccess("Offer accepted.");
      } else {
        await onConfirmDelivery();
        setSuccess("Delivery confirmed.");
      }
    } catch (e) {
      setError(mapActionError(e));
    } finally {
      setBusy(false);
    }
  };

  const begin = (kind: Pending) => {
    setError(null);
    setSuccess(null);
    setPending(kind);
  };

  return (
    <section className="mm-panel" aria-label="Fulfillment actions">
      <div className="mm-buyer-panel-head">
        <h2>Actions</h2>
      </div>
      <p className="mm-muted">
        Actions are enabled only when allowed by authoritative transaction state.
        Fulfillment completion does not imply payout authorization.
      </p>
      <div className="mm-buyer-inline-actions">
        <button
          type="button"
          disabled={!canAccept || busy}
          title={!canAccept ? reason || undefined : undefined}
          onClick={() => begin("accept")}
        >
          Accept
        </button>
        <button
          type="button"
          disabled={!canConfirm || busy}
          title={!canConfirm ? reason || undefined : undefined}
          onClick={() => begin("delivery")}
        >
          Confirm delivery
        </button>
      </div>
      {reason ? <p className="mm-muted">{reason}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      {success ? (
        <BuyerSuccessMessage className="mm-buyer-action-success">
          {success}
        </BuyerSuccessMessage>
      ) : null}
      {dialog ? (
        <BuyerConfirmDialog
          {...dialog}
          busy={busy}
          onConfirm={() => void execute()}
          onCancel={() => setPending(null)}
        />
      ) : null}
    </section>
  );
}
