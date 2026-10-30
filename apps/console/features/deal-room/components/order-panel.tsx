import { Check, Clock3, PackageCheck, ShieldCheck } from "lucide-react";

import type { BuyerState } from "@/lib/types";
import { formatDate, formatDateTime, money } from "@/lib/format";

const TIMELINE = ["Reserved", "Processing", "In transit", "Delivered"] as const;

const STATUS_INDEX: Record<string, number> = {
  reserved: 0,
  confirmed: 0,
  processing: 1,
  partially_reserved: 1,
  in_transit: 2,
  shipped: 2,
  delivered: 3,
};

function errorMessage(error: BuyerState["error"]) {
  if (!error) return null;
  if (typeof error === "string") return error;
  return error.message ?? error.code ?? "Unknown error";
}

export function OrderPanel({ state }: { state: BuyerState }) {
  const { order, approval, award, stage, error } = state;
  const statusIndex = order
    ? (STATUS_INDEX[order.fulfillment?.status] ?? 0)
    : 0;

  return (
    <section className="mm-panel mm-order" aria-labelledby="order-panel-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">Post-approval</p>
          <h2 id="order-panel-title">Order desk</h2>
        </div>
        <span className="mm-mono-note">human-gated</span>
      </header>

      {order ? (
        <div className="mm-order-confirmed">
          <div className="mm-order-stamp">
            <PackageCheck size={18} aria-hidden="true" />
            <span>Order confirmed</span>
          </div>

          <div className="mm-order-id">
            <span className="mm-kicker">Order</span>
            <strong>{order.order_id}</strong>
          </div>

          <div className="mm-order-metrics">
            <div>
              <span className="mm-kicker">Total</span>
              <strong>{money(order.total_cents)}</strong>
            </div>
            <div>
              <span className="mm-kicker">ETA</span>
              <strong>{formatDate(order.eta)}</strong>
            </div>
            <div>
              <span className="mm-kicker">Carrier</span>
              <strong>{order.fulfillment?.carrier ?? "MarketMesh Logistics"}</strong>
            </div>
            <div>
              <span className="mm-kicker">Tracking</span>
              <strong className="mm-tracking">{order.tracking_number}</strong>
            </div>
          </div>

          <div className="mm-receipt">
            <div>
              <ShieldCheck size={15} aria-hidden="true" />
              <span className="mm-kicker">Approval receipt</span>
            </div>
            <p>
              Approved by <strong>{approval?.approved_by || "Demo Buyer"}</strong>
              {approval?.note ? <> — “{approval.note}”</> : null}
            </p>
            <p className="mm-mono-note">
              Order is bound to offer {order.offer_id.slice(-10)} · reserved{" "}
              {formatDateTime(order.reserved_at)}
            </p>
          </div>

          <ol className="mm-timeline" aria-label="Fulfillment timeline">
            {TIMELINE.map((label, index) => (
              <li
                key={label}
                className={
                  index < statusIndex
                    ? "is-complete"
                    : index === statusIndex
                      ? "is-current"
                      : ""
                }
                aria-current={index === statusIndex ? "step" : undefined}
              >
                <span className="mm-timeline-dot">
                  {index < statusIndex ? (
                    <Check size={10} aria-hidden="true" />
                  ) : null}
                </span>
                <span>{label}</span>
              </li>
            ))}
          </ol>

          <details className="mm-line-items">
            <summary>Order lines · {order.quantity} units</summary>
            <ul>
              {order.line_items.map((line) => (
                <li key={line.sku}>
                  <span>
                    {line.quantity} × {line.name}
                  </span>
                  <span>{money(line.unit_price_cents * line.quantity)}</span>
                </li>
              ))}
            </ul>
          </details>
        </div>
      ) : stage === "rejected" ? (
        <div className="mm-order-stopped">
          <span className="mm-order-stamp is-stopped">No order was placed</span>
          <p>
            The human reviewer rejected the recommended award.
            {approval?.note ? <> Note: “{approval.note}”</> : null}
          </p>
          <p className="mm-mono-note">
            No purchase order was sent to {award?.winner?.seller_name ?? "the seller"}.
          </p>
        </div>
      ) : stage === "order_failed" ? (
        <div className="mm-order-stopped">
          <span className="mm-order-stamp is-error">Order failed</span>
          <p>{errorMessage(error) ?? "The seller rejected the purchase order."}</p>
        </div>
      ) : stage === "ordering" || stage === "approved" ? (
        <div className="mm-order-waiting">
          <Clock3 size={20} aria-hidden="true" />
          <div>
            <h3>Approval recorded</h3>
            <p>Buyer is sending the accepted offer and purchase order to the winner.</p>
          </div>
        </div>
      ) : award?.winner ? (
        <div className="mm-order-waiting">
          <Clock3 size={20} aria-hidden="true" />
          <div>
            <h3>Awaiting approval</h3>
            <p>
              {award.winner.seller_name} is the recommended winner. No order is
              placed until a human approves the award.
            </p>
          </div>
        </div>
      ) : (
        <p className="mm-empty">
          A signed order and approval receipt appear here after the human checkpoint.
        </p>
      )}
    </section>
  );
}
