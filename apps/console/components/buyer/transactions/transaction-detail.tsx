"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getBuyerTransaction, type ApiError } from "@/lib/buyer-transaction-api";
import type { BuyerTransactionDetail } from "@/lib/buyer-transaction-types";
import { FulfillmentSummary } from "./fulfillment-summary";

export function TransactionDetail({ transactionId }: { transactionId: string }) {
  const [detail, setDetail] = useState<BuyerTransactionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        setDetail(await getBuyerTransaction(transactionId));
      } catch (e: any) {
        setError((e as ApiError)?.message ?? "Failed to load transaction");
      } finally {
        setLoading(false);
      }
    })();
  }, [transactionId]);

  if (loading) return <main className="mm-page"><p className="mm-muted">Loading transaction…</p></main>;
  if (error || !detail) {
    return (
      <main className="mm-page">
        <p role="alert">{error ?? "Transaction not found"}</p>
        <Link href="/transactions">Back to transactions</Link>
      </main>
    );
  }

  const amount =
    detail.agreed_amount_cents != null
      ? `${(detail.agreed_amount_cents / 100).toFixed(2)} ${detail.currency ?? ""}`.trim()
      : "—";

  return (
    <main className="mm-page" aria-label="Transaction detail">
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Transaction</p>
          <h1>{transactionId}</h1>
        </div>
      </header>

      <section className="mm-panel" aria-label="Transaction summary">
        <h2>Summary</h2>
        <dl>
          <div><dt>Transaction status</dt><dd>{detail.transaction_status ?? detail.status ?? "—"}</dd></div>
          <div><dt>Payment status</dt><dd>{detail.payment_status ?? "—"}</dd></div>
          <div><dt>Agreed amount</dt><dd>{amount}</dd></div>
          {detail.seller_name || detail.seller_id ? <div><dt>Seller</dt><dd>{detail.seller_name ?? detail.seller_id}</dd></div> : null}
        </dl>
      </section>

      <section className="mm-panel" aria-label="Agreement">
        <h2>Agreement</h2>
        {detail.agreement ? (
          <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(detail.agreement, null, 2)}</pre>
        ) : (
          <p className="mm-muted">Agreement details unavailable from current projection.</p>
        )}
      </section>

      <section className="mm-panel" aria-label="Payment">
        <h2>Payment</h2>
        {detail.payment ? (
          <pre style={{ whiteSpace: "pre-wrap" }}>{JSON.stringify(detail.payment, null, 2)}</pre>
        ) : (
          <p className="mm-muted">Payment details unavailable from current projection.</p>
        )}
      </section>

      <section className="mm-panel" aria-label="Timeline">
        <h2>Status timeline</h2>
        {Array.isArray(detail.timeline) && detail.timeline.length > 0 ? (
          <ul>
            {detail.timeline.map((ev: any, idx: number) => (
              <li key={idx}>{ev.type ?? ev.status ?? "event"} {ev.at ?? ev.created_at ? `· ${ev.at ?? ev.created_at}` : ""}</li>
            ))}
          </ul>
        ) : (
          <p className="mm-muted">Timeline details unavailable until provided by the buyer read projection.</p>
        )}
      </section>

      <FulfillmentSummary transactionId={transactionId} fulfillment={detail.fulfillment ?? null} />
    </main>
  );
}
