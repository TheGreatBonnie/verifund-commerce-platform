"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listBuyerTransactions, type ApiError } from "@/lib/buyer-transaction-api";
import type { BuyerTransactionListResponse } from "@/lib/buyer-transaction-types";

function labelize(key: string) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

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

  const items = (data?.items ?? []).filter(
    (t) => t.fulfillment_status || t.fulfillment?.status || t.next_action || t.fulfillment?.next_action,
  );

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
            <div className="mm-buyer-panel-head">
              <h2>Overview</h2>
            </div>
            {data.aggregates && Object.keys(data.aggregates).length > 0 ? (
              <div className="mm-buyer-overview-grid">
                {Object.entries(data.aggregates).map(([k, v]) => (
                  <div key={k} className="mm-buyer-stat">
                    <span className="mm-buyer-stat-label">{labelize(k)}</span>
                    <span className="mm-buyer-stat-value">{v}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="mm-muted">Aggregate counts unavailable.</p>
            )}
          </section>

          <section className="mm-panel" aria-label="Fulfillment list">
            <div className="mm-buyer-panel-head">
              <h2>Fulfillment records</h2>
            </div>
            {items.length === 0 ? (
              <p className="mm-muted">No fulfillment records available.</p>
            ) : (
              <ul className="mm-buyer-list">
                {items.map((t) => {
                  const fStatus = t.fulfillment_status ?? t.fulfillment?.status ?? "unknown";
                  const next = t.next_action ?? t.fulfillment?.next_action;
                  return (
                    <li key={t.transaction_id} className="mm-buyer-list-item">
                      <div className="mm-buyer-row-main">
                        <div className="mm-buyer-row-title">
                          <Link href={`/fulfillment/${encodeURIComponent(t.transaction_id)}`}>{t.transaction_id}</Link>
                        </div>
                        <div className="mm-buyer-meta">
                          {t.product_name ? <span>{t.product_name}</span> : null}
                          <span>Status: {fStatus}</span>
                          {next ? <span>Next: {next}</span> : null}
                          <span>Transaction: {t.transaction_status ?? "unknown"}</span>
                        </div>
                      </div>
                      <div className="mm-buyer-row-actions">
                        <Link href={`/fulfillment/${encodeURIComponent(t.transaction_id)}`}>View fulfillment</Link>
                        <Link href={`/transactions/${encodeURIComponent(t.transaction_id)}`}>View transaction</Link>
                      </div>
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
