"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  acceptBuyerTransaction,
  confirmBuyerDelivery,
  getBuyerFulfillment,
  getBuyerInspection,
  type ApiError,
} from "@/lib/buyer-transaction-api";
import type { BuyerFulfillmentProjection, BuyerInspection } from "@/lib/buyer-transaction-types";
import { BlockersPanel } from "../shared/blockers-panel";
import { BuyerEvidenceDialog } from "./buyer-evidence-dialog";
import { BuyerInspectionPanel } from "./buyer-inspection-panel";
import { DisputePanel } from "./dispute-panel";
import { TransactionReference } from "./transaction-reference";

export function FulfillmentDetail({ transactionId }: { transactionId: string }) {
  const [fulfillment, setFulfillment] = useState<BuyerFulfillmentProjection | null>(null);
  const [inspection, setInspection] = useState<BuyerInspection | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [f, i] = await Promise.all([
        getBuyerFulfillment(transactionId),
        getBuyerInspection(transactionId).catch((e: ApiError) => (e?.status === 404 ? null : Promise.reject(e))),
      ]);
      setFulfillment(f);
      setInspection(i as BuyerInspection | null);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load fulfillment");
    } finally {
      setLoading(false);
    }
  }, [transactionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const allowed = fulfillment?.allowed_actions ?? [];
  const runAction = async (fn: () => Promise<any>) => {
    setActionError(null);
    try {
      await fn();
      await refresh();
    } catch (e: any) {
      setActionError(e?.message ?? "Action failed");
    }
  };

  if (loading) return <main className="mm-page"><p className="mm-muted">Loading fulfillment…</p></main>;
  if (error || !fulfillment) {
    return (
      <main className="mm-page">
        <p role="alert">{error ?? "Fulfillment not found"}</p>
        <Link href="/fulfillment">Back to fulfillment</Link>
      </main>
    );
  }

  return (
    <main className="mm-page" aria-label="Fulfillment detail">
      <header className="mm-page-header" style={{ display: "flex", justifyContent: "space-between", gap: 16, flexWrap: "wrap" }}>
        <div>
          <p className="mm-kicker">Fulfillment</p>
          <h1>Fulfillment for {transactionId}</h1>
          <p className="mm-muted">Status: {fulfillment.status ?? "unknown"}{fulfillment.next_action ? ` · Next: ${fulfillment.next_action}` : ""}</p>
        </div>
        <TransactionReference transactionId={transactionId} />
      </header>

      <BlockersPanel blockers={fulfillment.blockers ?? []} />

      <section className="mm-panel" aria-label="Requirements and evidence">
        <h2>Requirements & evidence</h2>
        {(fulfillment.requirements ?? []).length === 0 ? (
          <p className="mm-muted">No requirement details available.</p>
        ) : (
          <ul>
            {(fulfillment.requirements ?? []).map((r: any) => (
              <li key={r.requirement_id ?? r.id ?? JSON.stringify(r)}>
                <strong>{r.title ?? r.requirement_id ?? r.id}</strong>
                {r.status ? ` — ${r.status}` : ""}
                {r.owner ? ` (${r.owner})` : ""}
              </li>
            ))}
          </ul>
        )}
        {(fulfillment.evidence ?? []).length > 0 ? (
          <>
            <h3>Evidence</h3>
            <ul>
              {(fulfillment.evidence ?? []).map((e: any, idx: number) => (
                <li key={e.evidence_id ?? idx}>{e.title ?? e.kind ?? e.evidence_id ?? "Evidence item"} {e.scan_status ? `· ${e.scan_status}` : ""}</li>
              ))}
            </ul>
          </>
        ) : null}
        <BuyerEvidenceDialog transactionId={transactionId} requirements={fulfillment.requirements ?? []} onSubmitted={refresh} />
      </section>

      <section className="mm-panel" aria-label="Shipment and tracking">
        <h2>Shipment & carrier timeline</h2>
        {fulfillment.shipment ? (
          <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(fulfillment.shipment, null, 2)}</pre>
        ) : (
          <p className="mm-muted">No shipment data available.</p>
        )}
        {(fulfillment.carrier_events ?? []).length > 0 ? (
          <ul>
            {(fulfillment.carrier_events ?? []).map((ev: any, idx: number) => (
              <li key={idx}>{ev.status ?? ev.event ?? JSON.stringify(ev)} {ev.occurred_at ? `· ${ev.occurred_at}` : ""}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <BuyerInspectionPanel inspection={inspection ?? fulfillment.inspection ?? null} />

      <DisputePanel
        transactionId={transactionId}
        allowedActions={allowed}
        onChanged={refresh}
      />

      <section className="mm-panel" aria-label="Fulfillment actions">
        <h2>Actions</h2>
        <p className="mm-muted">Actions are enabled only when allowed by authoritative transaction state. Fulfillment completion does not imply payout authorization.</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button disabled={!allowed.includes("accept")} onClick={() => runAction(() => acceptBuyerTransaction(transactionId))}>Accept</button>
          <button disabled={!(allowed.includes("delivery_confirmed") || allowed.includes("confirm_delivery"))} onClick={() => runAction(() => confirmBuyerDelivery(transactionId, {}))}>Confirm delivery</button>
        </div>
        {actionError ? <p role="alert">{actionError}</p> : null}
      </section>

      <p><Link href={`/transactions/${encodeURIComponent(transactionId)}`}>View transaction details</Link></p>
    </main>
  );
}
