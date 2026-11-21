"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import {
  type ApiError,
  acceptBuyerTransaction,
  confirmBuyerDelivery,
  getBuyerFulfillment,
  getBuyerInspection,
  getBuyerTransaction,
} from "@/lib/buyer-transaction-api";
import type {
  BuyerFulfillmentProjection,
  BuyerInspection,
  BuyerTransactionDetail,
} from "@/lib/buyer-transaction-types";
import { ActionBar } from "./action-bar";
import { BuyerEvidenceDialog } from "./buyer-evidence-dialog";
import { BuyerInspectionPanel } from "./buyer-inspection-panel";
import { DisputePanel } from "./dispute-panel";
import { DisputesPanel } from "./disputes-panel";
import { SettlementRail } from "./settlement-rail";
import { TransactionReference } from "./transaction-reference";
import { VerificationPanel } from "./verification-panel";
import { BlockersPanel } from "../shared/blockers-panel";
import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { ChatHandoffLink } from "../shared/chat-handoff-link";
import { formatMoney, labelize } from "../shared/format";
import {
  BuyerErrorState,
  BuyerPageSkeleton,
} from "../shared/buyer-page-states";
import { StructuredDataPanel } from "../shared/structured-data-panel";

export function FulfillmentDetail({ transactionId }: { transactionId: string }) {
  const [fulfillment, setFulfillment] = useState<BuyerFulfillmentProjection | null>(null);
  const [inspection, setInspection] = useState<BuyerInspection | null>(null);
  const [transaction, setTransaction] = useState<BuyerTransactionDetail | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      setError(null);
      const [f, i, t] = await Promise.all([
        getBuyerFulfillment(transactionId),
        getBuyerInspection(transactionId).catch((e: ApiError) =>
          e?.status === 404 ? null : Promise.reject(e),
        ),
        getBuyerTransaction(transactionId).catch(() => null),
      ]);
      setFulfillment(f);
      setInspection(i as BuyerInspection | null);
      setTransaction(t as BuyerTransactionDetail | null);
    } catch (e) {
      setError(e as ApiError);
    } finally {
      setLoading(false);
    }
  }, [transactionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (loading) {
    return <BuyerPageSkeleton label="Loading fulfillment" cards={2} rows={5} />;
  }
  if (error || !fulfillment) {
    const notFound = error?.status === 404;
    return (
      <BuyerErrorState
        notFound={notFound}
        message={error?.message ?? "Fulfillment not found"}
        backHref="/fulfillment"
        onRetry={notFound ? undefined : () => void refresh()}
      />
    );
  }

  const allowed = fulfillment.allowed_actions ?? [];
  const status = fulfillment.status ?? "unknown";
  const carrierEvents = (fulfillment.carrier_events ?? []).map((event) => ({
    type: event?.status ?? event?.event ?? "carrier_event",
    status: event?.status,
    at: event?.occurred_at,
  }));

  const accept = async () => {
    await acceptBuyerTransaction(transactionId);
    await refresh();
  };
  const confirmDelivery = async () => {
    await confirmBuyerDelivery(transactionId, {});
    await refresh();
  };

  return (
    <main className="mm-page" aria-label="Fulfillment detail">
      <header className="mm-page-header mm-buyer-detail-head">
        <div>
          <p className="mm-kicker">Fulfillment</p>
          <h1>Fulfillment for {transactionId}</h1>
          <div className="mm-buyer-inline-actions">
            <BuyerStatusPill value={status} label={labelize(status)} />
            {fulfillment.next_action ? (
              <span>Next: {labelize(fulfillment.next_action)}</span>
            ) : null}
          </div>
        </div>
        <TransactionReference
          transactionId={transactionId}
          status={transaction?.status ?? transaction?.transaction_status}
          paymentStatus={transaction?.payment_status}
          amount={formatMoney(transaction?.agreed_amount_cents, transaction?.currency)}
        />
      </header>

      <section className="mm-panel" aria-label="Release decision">
        <div className="mm-buyer-panel-head">
          <h2>Release decision</h2>
        </div>
        <p className="mm-muted">
          Funds are released only through the chat approval flow, where the signed
          agreement is bound to the request. These links open that flow for this
          transaction.
        </p>
        <div className="mm-buyer-inline-actions">
          <ChatHandoffLink transactionId={transactionId} intent="release">
            Review &amp; release in chat
          </ChatHandoffLink>
          <ChatHandoffLink transactionId={transactionId} intent="reject">
            Reject in chat
          </ChatHandoffLink>
          <ChatHandoffLink transactionId={transactionId} intent="review">
            Open in chat
          </ChatHandoffLink>
        </div>
      </section>

      <BlockersPanel blockers={fulfillment.blockers ?? []} />

      <section className="mm-panel" aria-label="Carrier timeline">
        <div className="mm-buyer-panel-head">
          <h2>Carrier timeline</h2>
        </div>
        <SettlementRail
          events={carrierEvents}
          nextAction={fulfillment.next_action ?? null}
        />
      </section>

      <section className="mm-panel" aria-label="Requirements and evidence">
        <div className="mm-buyer-panel-head">
          <h2>Requirements &amp; evidence</h2>
          <div className="mm-buyer-inline-actions">
            <BuyerEvidenceDialog
              transactionId={transactionId}
              requirements={fulfillment.requirements ?? []}
              onSubmitted={refresh}
            />
          </div>
        </div>
        {(fulfillment.requirements ?? []).length === 0 ? (
          <p className="mm-muted">No requirement details available.</p>
        ) : (
          <ul className="mm-buyer-list">
            {(fulfillment.requirements ?? []).map((requirement) => (
              <li
                key={requirement?.requirement_id ?? requirement?.id ?? JSON.stringify(requirement)}
                className="mm-buyer-list-item mm-buyer-list-item-full"
              >
                <div className="mm-buyer-row-main">
                  <div className="mm-buyer-row-title">
                    {requirement?.title ?? requirement?.requirement_id ?? requirement?.id}
                  </div>
                  <div className="mm-buyer-meta">
                    <span>Status: {labelize(String(requirement?.status ?? "unknown"))}</span>
                    {requirement?.owner ? <span>Owner: {requirement.owner}</span> : null}
                    {requirement?.kind ? <span>Kind: {requirement.kind}</span> : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {(fulfillment.evidence ?? []).length > 0 ? (
          <div className="mm-buyer-section-stack mm-buyer-subsection">
            <h3>Evidence</h3>
            <ul className="mm-buyer-list">
              {(fulfillment.evidence ?? []).map((evidence, index) => (
                <li
                  key={evidence?.evidence_id ?? index}
                  className="mm-buyer-list-item mm-buyer-list-item-full"
                >
                  <div className="mm-buyer-row-main">
                    <div className="mm-buyer-row-title">
                      {evidence?.title ?? evidence?.kind ?? evidence?.evidence_id ?? "Evidence item"}
                    </div>
                    <div className="mm-buyer-meta">
                      {evidence?.scan_status ? (
                        <span>Scan: {labelize(String(evidence.scan_status))}</span>
                      ) : null}
                      {evidence?.view_label ? <span>View: {evidence.view_label}</span> : null}
                      {evidence?.requirement_id ? (
                        <span>Requirement: {evidence.requirement_id}</span>
                      ) : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {fulfillment.shipment ? (
        <StructuredDataPanel
          title="Shipment"
          data={fulfillment.shipment}
          rawLabel="View raw shipment"
        />
      ) : (
        <section className="mm-panel" aria-label="Shipment">
          <h2>Shipment</h2>
          <p className="mm-muted">No shipment data available.</p>
        </section>
      )}

      <section className="mm-panel" aria-label="Shipment and tracking">
        <div className="mm-buyer-panel-head">
          <h2>Shipment &amp; carrier details</h2>
        </div>
        {(fulfillment.carrier_events ?? []).length > 0 ? (
          <ul className="mm-buyer-list">
            {(fulfillment.carrier_events ?? []).map((event, index) => (
              <li
                key={index}
                className="mm-buyer-list-item mm-buyer-list-item-full"
              >
                <div className="mm-buyer-row-main">
                  <div className="mm-buyer-row-title">
                    {labelize(String(event?.status ?? event?.event ?? "carrier event"))}
                  </div>
                  <div className="mm-buyer-meta">
                    {event?.occurred_at ? <span>{event.occurred_at}</span> : null}
                    {event?.location ? <span>{event.location}</span> : null}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mm-muted">No carrier events available.</p>
        )}
      </section>

      <VerificationPanel verification={fulfillment.verification ?? null} />
      <DisputesPanel disputes={fulfillment.disputes} />

      <BuyerInspectionPanel inspection={inspection ?? fulfillment.inspection ?? null} />

      <DisputePanel
        transactionId={transactionId}
        allowedActions={allowed}
        onChanged={refresh}
      />

      <ActionBar
        allowedActions={allowed}
        blockers={fulfillment.blockers}
        nextAction={fulfillment.next_action}
        onAccept={accept}
        onConfirmDelivery={confirmDelivery}
      />

      <div className="mm-buyer-inline-actions">
        <Link href={`/transactions/${encodeURIComponent(transactionId)}`}>
          View transaction details
        </Link>
      </div>
    </main>
  );
}
