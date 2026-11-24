import Link from "next/link";

import type { BuyerTransactionSummary } from "@/lib/buyer-transaction-types";
import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { ChatHandoffLink } from "../shared/chat-handoff-link";
import { formatMoney, labelize } from "../shared/format";

export function FulfillmentList({
  items,
}: {
  items: BuyerTransactionSummary[];
}) {
  if (items.length === 0) {
    return <p className="mm-muted">No fulfillment records available.</p>;
  }

  return (
    <ul className="mm-buyer-list">
      {items.map((item) => {
        const id = encodeURIComponent(item.transaction_id);
        const status = item.fulfillment_status ?? item.fulfillment?.status ?? "unknown";
        const next = item.next_action ?? item.fulfillment?.next_action;
        return (
          <li className="mm-buyer-list-item" key={item.transaction_id}>
            <div className="mm-buyer-row-main">
              <div className="mm-buyer-row-title">
                <Link
                  href={`/fulfillment/${id}`}
                  aria-label={`Fulfillment ${item.transaction_id}`}
                >
                  {item.product_name ?? item.transaction_id}
                </Link>
                <BuyerStatusPill value={status} label={labelize(status)} />
              </div>
              <div className="mm-buyer-meta">
                <span>ID: {item.transaction_id}</span>
                {item.seller_name ? (
                  <span>Seller: {item.seller_name}</span>
                ) : null}
                <span className="mm-buyer-amount">
                  {formatMoney(item.agreed_amount_cents, item.currency)}
                </span>
                {next ? <span>Next: {labelize(next)}</span> : null}
                {item.transaction_status ? (
                  <span>Transaction: {labelize(item.transaction_status)}</span>
                ) : null}
              </div>
            </div>
            <div className="mm-buyer-row-actions">
              <Link
                href={`/fulfillment/${id}`}
                aria-label={`View fulfillment ${item.transaction_id}`}
              >
                View fulfillment
              </Link>
              <Link
                href={`/transactions/${id}`}
                aria-label={`View transaction ${item.transaction_id}`}
              >
                View transaction
              </Link>
              <ChatHandoffLink transactionId={item.transaction_id} intent="review">
                Open in chat
              </ChatHandoffLink>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
