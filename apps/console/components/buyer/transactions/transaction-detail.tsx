"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type ApiError,
  getBuyerTransaction,
} from "@/lib/buyer-transaction-api";
import type { BuyerTransactionDetail } from "@/lib/buyer-transaction-types";
import { SettlementRail } from "../fulfillment/settlement-rail";
import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { formatMoney, labelize } from "../shared/format";
import {
  BuyerErrorState,
  BuyerPageSkeleton,
} from "../shared/buyer-page-states";
import { StructuredDataPanel } from "../shared/structured-data-panel";
import { BuyerAgreementCard } from "./agreement-card";
import { FulfillmentSummary } from "./fulfillment-summary";

export function TransactionDetail({ transactionId }: { transactionId: string }) {
  const [detail, setDetail] = useState<BuyerTransactionDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDetail(await getBuyerTransaction(transactionId));
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  }, [transactionId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <BuyerPageSkeleton label="Loading transaction" cards={2} rows={4} />;
  }
  if (error || !detail) {
    const notFound = error?.status === 404;
    return (
      <BuyerErrorState
        notFound={notFound}
        message={error?.message ?? "Transaction not found"}
        backHref="/transactions"
        onRetry={notFound ? undefined : () => void load()}
      />
    );
  }

  const status = detail.transaction_status ?? detail.status ?? "unknown";

  return (
    <main className="mm-page" aria-label="Transaction detail">
      <header className="mm-page-header mm-buyer-detail-head">
        <div>
          <p className="mm-kicker">Transaction</p>
          <h1>{transactionId}</h1>
          <p className="mm-buyer-detail-amount">
            {formatMoney(detail.agreed_amount_cents, detail.currency)}
          </p>
          <div className="mm-buyer-inline-actions">
            <BuyerStatusPill value={status} label={labelize(status)} />
            {detail.payment_status ? (
              <BuyerStatusPill
                value={detail.payment_status}
                label={labelize(detail.payment_status)}
              />
            ) : null}
            {detail.seller_name ? (
              <span className="mm-muted">Seller: {detail.seller_name}</span>
            ) : null}
          </div>
        </div>
      </header>

      <section className="mm-panel" aria-label="Settlement timeline">
        <div className="mm-buyer-panel-head">
          <h2>Settlement timeline</h2>
        </div>
        <SettlementRail
          events={detail.timeline}
          nextAction={detail.fulfillment?.next_action ?? null}
        />
      </section>

      {detail.agreement ? (
        <section className="mm-panel" aria-label="Agreement">
          <h2>Agreement</h2>
          <BuyerAgreementCard
            agreement={detail.agreement}
            transactionId={transactionId}
          />
        </section>
      ) : (
        <section className="mm-panel" aria-label="Agreement">
          <h2>Agreement</h2>
          <p className="mm-muted">
            Agreement details unavailable from current projection.
          </p>
        </section>
      )}

      {detail.payment ? (
        <StructuredDataPanel
          title="Payment"
          data={detail.payment}
          rawLabel="View raw payment"
        />
      ) : (
        <section className="mm-panel" aria-label="Payment">
          <h2>Payment</h2>
          <p className="mm-muted">
            Payment details unavailable from current projection.
          </p>
        </section>
      )}

      <FulfillmentSummary
        transactionId={transactionId}
        fulfillment={detail.fulfillment ?? null}
      />
    </main>
  );
}
