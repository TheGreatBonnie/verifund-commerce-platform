"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listBuyerTransactions, type ApiError } from "@/lib/buyer-transaction-api";
import type { BuyerTransactionListResponse } from "@/lib/buyer-transaction-types";

export default function TransactionsPage() {
  const [data, setData] = useState<BuyerTransactionListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setData(await listBuyerTransactions());
      } catch (e: any) {
        setError((e as ApiError)?.message ?? "Failed to load transactions");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <main className="mm-page" aria-label="Transactions">
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Buyer workspace</p>
          <h1>Transactions</h1>
          <p className="mm-muted">Commercial and financial records for your purchases.</p>
        </div>
      </header>

      {loading ? <p className="mm-muted">Loading transactions…</p> : null}
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

          <section className="mm-panel" aria-label="Transaction list">
            <h2>Transactions</h2>
            {data.items.length === 0 ? (
              <p className="mm-muted">No transactions available.</p>
            ) : (
              <ul>
                {data.items.map((t) => (
                  <li key={t.transaction_id} style={{ marginBottom: 12 }}>
                    <div><Link href={`/transactions/${encodeURIComponent(t.transaction_id)}`}>{t.transaction_id}</Link></div>
                    <div className="mm-muted">
                      {t.product_name ? `${t.product_name} · ` : ""}
                      Status: {t.transaction_status ?? "unknown"} · Payment: {t.payment_status ?? "unknown"}
                      {t.fulfillment_status ? ` · Fulfillment: ${t.fulfillment_status}` : ""}
                    </div>
                    <div><Link href={`/fulfillment/${encodeURIComponent(t.transaction_id)}`}>View fulfillment</Link></div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}
