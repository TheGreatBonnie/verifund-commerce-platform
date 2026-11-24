import Link from "next/link";

import { ChatHandoffLink } from "../shared/chat-handoff-link";
import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { labelize } from "../shared/format";

type Summary = {
  status?: string | null;
  next_action?: string | null;
  blockers?: Array<{ code: string; message?: string }> | null;
  shipment?: Record<string, any> | null;
  inspection?: Record<string, any> | null;
};

export function FulfillmentSummary({
  transactionId,
  fulfillment,
}: {
  transactionId: string;
  fulfillment?: Summary | null;
}) {
  const status = fulfillment?.status ?? "unavailable";
  const blockers = fulfillment?.blockers ?? [];
  const shipment = fulfillment?.shipment;
  const inspection = fulfillment?.inspection;

  const shipmentHighlights = shipment
    ? [
        typeof shipment.carrier === "string" ? shipment.carrier : null,
        typeof shipment.tracking_number === "string"
          ? `Tracking ${shipment.tracking_number}`
          : null,
      ].filter(Boolean)
    : [];
  const inspectionHighlights = inspection
    ? [
        typeof inspection.status === "string"
          ? `Inspection: ${labelize(inspection.status)}`
          : null,
        typeof inspection.outcome === "string"
          ? `Outcome: ${labelize(inspection.outcome)}`
          : null,
      ].filter(Boolean)
    : [];

  return (
    <section className="mm-panel" aria-label="Fulfillment summary">
      <h2>Fulfillment</h2>
      <div className="mm-buyer-inline-actions">
        <BuyerStatusPill value={status} label={labelize(status)} />
        {fulfillment?.next_action ? (
          <span>Next: {labelize(fulfillment.next_action)}</span>
        ) : null}
      </div>
      {blockers.length > 0 ? (
        <ul className="mm-buyer-reason-list">
          {blockers.map((blocker, index) => (
            <li key={`${blocker.code}-${index}`}>
              {blocker.message ?? labelize(blocker.code)}
            </li>
          ))}
        </ul>
      ) : null}
      {shipmentHighlights.length > 0 ? (
        <p className="mm-muted">{shipmentHighlights.join(" · ")}</p>
      ) : null}
      {inspectionHighlights.length > 0 ? (
        <p className="mm-muted">{inspectionHighlights.join(" · ")}</p>
      ) : null}
      <div className="mm-buyer-inline-actions">
        <Link href={`/fulfillment/${encodeURIComponent(transactionId)}`}>
          View fulfillment
        </Link>
        <ChatHandoffLink transactionId={transactionId} intent="review">
          Review in chat
        </ChatHandoffLink>
      </div>
    </section>
  );
}
