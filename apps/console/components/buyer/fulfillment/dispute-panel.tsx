"use client";

import { useState } from "react";
import { openBuyerDispute } from "@/lib/buyer-transaction-api";

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
  const [busy, setBusy] = useState(false);
  const canDispute = allowedActions.includes("dispute") || allowedActions.includes("open_dispute");

  const submit = async () => {
    if (!claim.trim()) return;
    setError(null);
    setBusy(true);
    try {
      await openBuyerDispute(transactionId, {
        claim_type: "inspection",
        reason_code: "buyer_dispute",
        claim: claim.trim(),
      });
      setClaim("");
      await onChanged();
    } catch (e: any) {
      setError(e?.message ?? "Dispute failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mm-panel" aria-label="Dispute">
      <h2>Dispute</h2>
      <p className="mm-muted">Open a dispute only when allowed by authoritative transaction state.</p>
      <textarea
        value={claim}
        onChange={(e) => setClaim(e.target.value)}
        placeholder="Describe the issue"
        disabled={!canDispute || busy}
        rows={4}
      />
      <div>
        <button disabled={!canDispute || !claim.trim() || busy} onClick={submit}>
          {busy ? "Submitting…" : "Open dispute"}
        </button>
      </div>
      {error ? <p role="alert">{error}</p> : null}
    </section>
  );
}
