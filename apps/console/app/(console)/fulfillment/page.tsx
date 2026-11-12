"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listBuyerTransactions, type ApiError } from "@/lib/buyer-transaction-api";
import type { BuyerTransactionListResponse } from "@/lib/buyer-transaction-types";

export default function FulfillmentListPage() {
  const [data, setData] = useState<BuyerTransactionListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        // Authoritative buyer list projection with fulfillment summaries/aggregates (Q4). No run-history approximation.
        setData(await listBuyerTransactions());
      } catch (e: any) {
        setError((e as ApiError)?.message ?? "Failed to load fulfillment records");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const items = (data?.items ?? []).filter((t) => t.fulfillment_status || t.fulfillment?.status || t.next_action || t.fulfillment?.next_action);

  return (
    <main className="mm-page" aria-label="Fulfillment">
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Buyer workspace</p>
          <h1>Fulfillment</h1>
          <p className="mm-muted">Operational progress, evidence, shipment, and inspection for your orders.</p>
        </div>
      </header>

      {loading ? <p className="mm-muted">Loading fulfillment records…</p> : null}
      {error ? <p role="alert">{error}</p> : null}

      {data ? (
        <>
          <section className="mm-panel" aria-label="Overview">
            <h2>Overview</h2>
            {data.aggregates && Object.keys(data.aggregates).length > 0 ? (
              <ul>
                {Object.entries(data.aggregates).map(([k, v]) => (
                  <li key={k}><strong>{k}:</strong> {v}</li>
                ))}
              </ul>
            ) : (
              <p className="mm-muted">Aggregate counts unavailable.</p>
            )}
          </section>

          <section className="mm-panel" aria-label="Fulfillment list">
            <h2>Fulfillment records</h2>
            {items.length === 0 ? (
              <p className="mm-muted">No fulfillment records available.</p>
            ) : (
              <ul>
                {items.map((t) => {
                  const fStatus = t.fulfillment_status ?? t.fulfillment?.status ?? "unknown";
                  const next = t.next_action ?? t.fulfillment?.next_action;
                  return (
                    <li key={t.transaction_id} style={{ marginBottom: 12 }}>
                      <div><Link href={`/fulfillment/${encodeURIComponent(t.transaction_id)}`}>{t.transaction_id}</Link></div>
                      <div className="mm-muted">Status: {fStatus}{next ? ` · Next: ${next}` : ""}</div>
                      <div><Link href={`/transactions/${encodeURIComponent(t.transaction_id)}`}>View transaction</Link></div>
                    </li>
                  );
                })}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
