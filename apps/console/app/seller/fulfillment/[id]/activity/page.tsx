import { notFound } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { EmptyState } from "@/components/ui/empty-state";
import {
  FulfillmentBackLink,
  FulfillmentTabs,
} from "@/components/seller/fulfillment-tabs";
import { TransactionStatusBadge } from "@/components/seller/seller-status-badge";
import { loadSeller } from "@/lib/seller-api";
import { eventSummary } from "@/lib/seller-evidence";
import { formatDateTime } from "@/lib/format";
import { eventTypeLabel } from "@/lib/seller-status";
import type {
  SellerEventsPage,
  SellerProjection,
} from "@/lib/seller-types";

export const dynamic = "force-dynamic";

export default async function FulfillmentActivityPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [projectionResult, eventsResult] = await Promise.all([
    loadSeller<SellerProjection>(
      `/seller/transactions/${encodeURIComponent(id)}`,
      id,
    ),
    loadSeller<SellerEventsPage>(
      `/seller/transactions/${encodeURIComponent(id)}/events?limit=100`,
      id,
    ),
  ]);

  if (!projectionResult.ok) {
    if (projectionResult.status === 404) notFound();
    return (
      <>
        <FulfillmentBackLink />
        <Alert message={projectionResult.error} />
      </>
    );
  }

  const projection = projectionResult.data;
  const events = eventsResult.ok ? eventsResult.data.items : [];

  return (
    <>
      <FulfillmentBackLink />

      <header className="mm-seller-detail-head">
        <div>
          <p className="mm-kicker">
            Transaction activity / {projection.transaction_id}
          </p>
          <h1>Activity</h1>
          <p className="mm-seller-detail-meta">
            A chronological record of fulfillment and evidence events.
          </p>
        </div>
        <div className="mm-seller-detail-badges">
          <TransactionStatusBadge state={projection.state} />
        </div>
      </header>

      <FulfillmentTabs
        transactionId={projection.transaction_id}
        active="activity"
      />

      {!eventsResult.ok ? (
        <Alert message={eventsResult.error} />
      ) : events.length === 0 ? (
        <EmptyState
          title="No activity yet"
          body="Fulfillment and evidence events will appear here."
        />
      ) : (
        <section className="mm-panel" aria-label="Transaction activity">
          <ol className="mm-seller-activity">
            {events
              .slice()
              .reverse()
              .map((event) => (
                <li key={event.seq} className="mm-seller-activity-row">
                  <span className="mm-seller-activity-dot" aria-hidden="true" />
                  <div className="mm-seller-activity-main">
                    <div className="mm-seller-activity-head">
                      <strong>{eventTypeLabel(event.type)}</strong>
                      <time dateTime={event.created_at}>
                        {formatDateTime(event.created_at)}
                      </time>
                    </div>
                    <p>{eventSummary(event.payload)}</p>
                    <span className="mm-mono-note">
                      {event.actor} · #{event.seq}
                    </span>
                  </div>
                </li>
              ))}
          </ol>
        </section>
      )}
    </>
  );
}
