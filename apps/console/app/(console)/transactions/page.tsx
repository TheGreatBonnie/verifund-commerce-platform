"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { listBuyerTransactions, type ApiError } from "@/lib/buyer-transaction-api";
import type { BuyerTransactionListResponse } from "@/lib/buyer-transaction-types";

function labelize(key: string) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

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

          <section className="mm-panel" aria-label="Transaction list">
            <div className="mm-buyer-panel-head">
              <h2>Transactions</h2>
            </div>
            {data.items.length === 0 ? (
              <p className="mm-muted">No transactions available.</p>
            ) : (
              <ul className="mm-buyer-list">
                {data.items.map((t) => (
                  <li key={t.transaction_id} className="mm-buyer-list-item">
                    <div className="mm-buyer-row-main">
                      <div className="mm-buyer-row-title">
                        <Link href={`/transactions/${encodeURIComponent(t.transaction_id)}`}>{t.transaction_id}</Link>
                      </div>
                      <div className="mm-buyer-meta">
                        {t.product_name ? <span>{t.product_name}</span> : null}
                        {t.seller_name ? <span>Seller: {t.seller_name}</span> : null}
                        <span>Status: {t.transaction_status ?? "unknown"}</span>
                        <span>Payment: {t.payment_status ?? "unknown"}</span>
                        {t.fulfillment_status ? <span>Fulfillment: {t.fulfillment_status}</span> : null}
                        {t.agreed_amount_cents != null ? (
                          <span>Amount: {(t.agreed_amount_cents / 100).toFixed(2)} {t.currency ?? ""}</span>
                        ) : null}
                      </div>
                    </div>
                    <div className="mm-buyer-row-actions">
                      <Link href={`/transactions/${encodeURIComponent(t.transaction_id)}`}>View transaction</Link>
                      <Link href={`/fulfillment/${encodeURIComponent(t.transaction_id)}`}>View fulfillment</Link>
                    </div>
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
