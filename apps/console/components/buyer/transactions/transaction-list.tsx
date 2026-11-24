import Link from "next/link";

import type { BuyerTransactionSummary } from "@/lib/buyer-transaction-types";
import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { ChatHandoffLink } from "../shared/chat-handoff-link";
import { formatDate, formatMoney, labelize } from "../shared/format";

export function TransactionList({
  items,
}: {
  items: BuyerTransactionSummary[];
}) {
  if (items.length === 0) {
    return <p className="mm-muted">No transactions available.</p>;
  }

  return (
    <ul className="mm-buyer-list">
      {items.map((item) => {
        const id = encodeURIComponent(item.transaction_id);
        return (
          <li className="mm-buyer-list-item" key={item.transaction_id}>
            <div className="mm-buyer-row-main">
              <div className="mm-buyer-row-title">
                <Link
                  href={`/transactions/${id}`}
                  aria-label={`Transaction ${item.transaction_id}`}
                >
                  {item.product_name ?? item.transaction_id}
                </Link>
                <BuyerStatusPill
                  value={item.transaction_status ?? "unknown"}
                  label={labelize(item.transaction_status ?? "unknown")}
                />
              </div>
              <div className="mm-buyer-meta">
                <span>ID: {item.transaction_id}</span>
                {item.seller_name ? (
                  <span>Seller: {item.seller_name}</span>
                ) : null}
                <span className="mm-buyer-amount">
                  {formatMoney(item.agreed_amount_cents, item.currency)}
                </span>
                {item.payment_status ? (
                  <BuyerStatusPill
                    value={item.payment_status}
                    label={labelize(item.payment_status)}
                  />
                ) : null}
                {item.fulfillment_status ? (
                  <BuyerStatusPill
                    value={item.fulfillment_status}
                    label={labelize(item.fulfillment_status)}
                  />
                ) : null}
                {item.updated_at ? (
                  <time dateTime={item.updated_at}>
                    Updated {formatDate(item.updated_at)}
                  </time>
                ) : null}
              </div>
            </div>
            <div className="mm-buyer-row-actions">
              <Link
                href={`/transactions/${id}`}
                aria-label={`View transaction ${item.transaction_id}`}
              >
                View transaction
              </Link>
              <Link
                href={`/fulfillment/${id}`}
                aria-label={`View fulfillment for ${item.transaction_id}`}
              >
                View fulfillment
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
