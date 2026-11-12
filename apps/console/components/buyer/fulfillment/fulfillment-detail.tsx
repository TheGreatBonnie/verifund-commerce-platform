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
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Fulfillment</p>
          <h1>Fulfillment for {transactionId}</h1>
          <p className="mm-muted">Status: {fulfillment.status ?? "unknown"}{fulfillment.next_action ? ` · Next: ${fulfillment.next_action}` : ""}</p>
        </div>
        <TransactionReference transactionId={transactionId} />
      </header>

      <BlockersPanel blockers={fulfillment.blockers ?? []} />

      <section className="mm-panel" aria-label="Requirements and evidence">
        <div className="mm-buyer-panel-head">
          <h2>Requirements & evidence</h2>
          <div className="mm-buyer-inline-actions">
            <BuyerEvidenceDialog transactionId={transactionId} requirements={fulfillment.requirements ?? []} onSubmitted={refresh} />
          </div>
        </div>
        {(fulfillment.requirements ?? []).length === 0 ? (
          <p className="mm-muted">No requirement details available.</p>
        ) : (
          <ul className="mm-buyer-list">
            {(fulfillment.requirements ?? []).map((r: any) => (
              <li key={r.requirement_id ?? r.id ?? JSON.stringify(r)} className="mm-buyer-list-item" style={{ gridTemplateColumns: "1fr" }}>
                <div className="mm-buyer-row-main">
                  <div className="mm-buyer-row-title">{r.title ?? r.requirement_id ?? r.id}</div>
                  <div className="mm-buyer-meta">
                    <span>Status: {r.status ?? "unknown"}</span>
                    {r.owner ? <span>Owner: {r.owner}</span> : null}
                    {r.kind ? <span>Kind: {r.kind}</span> : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {(fulfillment.evidence ?? []).length > 0 ? (
          <div className="mm-buyer-section-stack" style={{ marginTop: 12 }}>
            <h3>Evidence</h3>
            <ul className="mm-buyer-list">
              {(fulfillment.evidence ?? []).map((e: any, idx: number) => (
                <li key={e.evidence_id ?? idx} className="mm-buyer-list-item" style={{ gridTemplateColumns: "1fr" }}>
                  <div className="mm-buyer-row-main">
                    <div className="mm-buyer-row-title">{e.title ?? e.kind ?? e.evidence_id ?? "Evidence item"}</div>
                    <div className="mm-buyer-meta">
                      {e.scan_status ? <span>Scan: {e.scan_status}</span> : null}
                      {e.view_label ? <span>View: {e.view_label}</span> : null}
                      {e.requirement_id ? <span>Requirement: {e.requirement_id}</span> : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      <section className="mm-panel" aria-label="Shipment and tracking">
        <div className="mm-buyer-panel-head">
          <h2>Shipment & carrier timeline</h2>
        </div>
        {fulfillment.shipment ? (
          <pre>{JSON.stringify(fulfillment.shipment, null, 2)}</pre>
        ) : (
          <p className="mm-muted">No shipment data available.</p>
        )}
        {(fulfillment.carrier_events ?? []).length > 0 ? (
          <ul className="mm-buyer-list" style={{ marginTop: 10 }}>
            {(fulfillment.carrier_events ?? []).map((ev: any, idx: number) => (
              <li key={idx} className="mm-buyer-list-item" style={{ gridTemplateColumns: "1fr" }}>
                <div className="mm-buyer-row-main">
                  <div className="mm-buyer-row-title">{ev.status ?? ev.event ?? "Carrier event"}</div>
                  <div className="mm-buyer-meta">
                    {ev.occurred_at ? <span>{ev.occurred_at}</span> : null}
                    {ev.location ? <span>{ev.location}</span> : null}
                  </div>
                </div>
              </li>
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
        <div className="mm-buyer-panel-head">
          <h2>Actions</h2>
        </div>
        <p className="mm-muted">Actions are enabled only when allowed by authoritative transaction state. Fulfillment completion does not imply payout authorization.</p>
        <div className="mm-buyer-inline-actions">
          <button disabled={!allowed.includes("accept")} onClick={() => runAction(() => acceptBuyerTransaction(transactionId))}>Accept</button>
          <button disabled={!(allowed.includes("delivery_confirmed") || allowed.includes("confirm_delivery"))} onClick={() => runAction(() => confirmBuyerDelivery(transactionId, {}))}>Confirm delivery</button>
        </div>
        {actionError ? <p role="alert">{actionError}</p> : null}
      </section>

      <div className="mm-buyer-inline-actions">
        <Link href={`/transactions/${encodeURIComponent(transactionId)}`}>View transaction details</Link>
      </div>
    </main>
  );
}
