"use client";

import { useState } from "react";

import { openBuyerDispute } from "@/lib/buyer-transaction-api";
import { mapActionError } from "@/lib/buyer-action-errors";
import { BuyerConfirmDialog } from "../shared/buyer-confirm-dialog";
import { BuyerSuccessMessage } from "../shared/buyer-page-states";

export function DisputePanel({
  transactionId,
  allowedActions,
  onChanged,
}: {
  transactionId: string;
  allowedActions: string[];
  onChanged: () => Promise<void> | void;
}) {
  const [claim, setClaim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const canDispute =
    allowedActions.includes("dispute") || allowedActions.includes("open_dispute");

  const submit = async () => {
    setPending(false);
    setError(null);
    setSuccess(false);
    setBusy(true);
    try {
      await openBuyerDispute(transactionId, {
        claim_type: "inspection",
        reason_code: "buyer_dispute",
        claim: claim.trim(),
      });
      setClaim("");
      setSuccess(true);
      await onChanged();
    } catch (e) {
      setError(mapActionError(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mm-panel" aria-label="Dispute">
      <h2>Dispute</h2>
      <p className="mm-muted">
        Open a dispute only when allowed by authoritative transaction state.
      </p>
      <textarea
        aria-label="Dispute claim"
        value={claim}
        onChange={(e) => setClaim(e.target.value)}
        placeholder="Describe the issue"
        disabled={!canDispute || busy}
        rows={4}
      />
      {!canDispute ? (
        <p className="mm-muted">
          Disputes are not available in the current transaction state.
        </p>
      ) : null}
      <div>
        <button
          type="button"
          disabled={!canDispute || !claim.trim() || busy}
          onClick={() => {
            setError(null);
            setSuccess(false);
            setPending(true);
          }}
        >
          {busy ? "Submitting…" : "Open dispute"}
        </button>
      </div>
      {error ? <p role="alert">{error}</p> : null}
      {success ? (
        <BuyerSuccessMessage className="mm-buyer-action-success">
          Dispute opened.
        </BuyerSuccessMessage>
      ) : null}
      {pending ? (
        <BuyerConfirmDialog
          title="Open dispute"
          body="This records a formal dispute against the transaction. An agent will follow up in chat."
          confirmLabel="Confirm dispute"
          busy={busy}
          onConfirm={() => void submit()}
          onCancel={() => setPending(false)}
        />
      ) : null}
    </section>
  );
}
