import { ArrowUpRight, Leaf, Star } from "lucide-react";

import type { Mandate, Negotiation, Offer } from "@/lib/types";
import { money, offerStatus, scoreLabel, unitPrice } from "@/lib/format";

type SellerLaneProps = {
  negotiation: Negotiation;
  mandate?: Mandate | null;
  winner?: boolean;
  score?: number;
  onViewWire: (sellerId: string) => void;
};

function failuresFor(offer: Offer | null, mandate?: Mandate | null) {
  if (!offer || !mandate) return [];
  const failures: string[] = [];
  if (
    typeof mandate.max_total_cents === "number" &&
    offer.total_cents > mandate.max_total_cents
  ) {
    failures.push("Over budget");
  }
  if (
    typeof mandate.deadline_days === "number" &&
    offer.delivery_days > mandate.deadline_days
  ) {
    failures.push("Misses deadline");
  }
  if (
    typeof mandate.min_warranty_months === "number" &&
    offer.warranty_months < mandate.min_warranty_months
  ) {
    failures.push("Short warranty");
  }
  if (
    typeof mandate.min_returns_days === "number" &&
    offer.returns_days < mandate.min_returns_days
  ) {
    failures.push("Short returns");
  }
  if (offer.terms.stock_confidence < 1 && !offer.terms.split_shipment) {
    failures.push("Stock risk");
  }
  return failures;
}

export function SellerLane({
  negotiation,
  mandate,
  winner = false,
  score,
  onViewWire,
}: SellerLaneProps) {
  const offer =
    negotiation.final_offer ?? negotiation.rounds.at(-1) ?? null;
  const failures = failuresFor(offer, mandate);
  const status = winner
    ? "Winner"
    : negotiation.status === "accepted"
      ? "Accepted"
      : negotiation.status === "cancelled"
        ? "Cancelled"
        : offer
          ? "Final"
          : offerStatus(negotiation.status);

  return (
    <article
      className={`mm-seller-lane ${winner ? "is-winner" : ""}`}
      data-seller={negotiation.seller_id}
    >
      <header className="mm-seller-head">
        <div>
          <p className="mm-kicker">Independent seller</p>
          <h3>{negotiation.seller_name}</h3>
        </div>
        <span className={`mm-status ${winner ? "is-signal" : ""}`}>{status}</span>
      </header>

      <div className="mm-seller-rating">
        <span>
          <Star size={12} aria-hidden="true" /> {offer?.seller_rating.toFixed(1) ?? "—"}
        </span>
        {offer?.terms.sustainability_certified ? (
          <span className="mm-sustainable">
            <Leaf size={12} aria-hidden="true" /> Sustainable
          </span>
        ) : (
          <span className="mm-muted-inline">No green claim</span>
        )}
        {typeof score === "number" ? (
          <span className="mm-score-chip">{scoreLabel(score)} score</span>
        ) : null}
      </div>

      {offer ? (
        <>
          <div className="mm-seller-price">
            <span className="mm-money">{money(offer.total_cents)}</span>
            <span className="mm-muted-inline">
              {money(unitPrice(offer))} / unit
            </span>
          </div>
          <dl className="mm-fact-grid">
            <div>
              <dt>Delivery</dt>
              <dd>{offer.delivery_days} days</dd>
            </div>
            <div>
              <dt>Warranty</dt>
              <dd>{offer.warranty_months} mo</dd>
            </div>
            <div>
              <dt>Returns</dt>
              <dd>{offer.returns_days} days</dd>
            </div>
            <div>
              <dt>Stock</dt>
              <dd>{Math.round(offer.terms.stock_confidence * 100)}%</dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="mm-lane-empty">No structured offer received.</p>
      )}

      {failures.length > 0 ? (
        <p className="mm-constraint-warning">
          <span aria-hidden="true">!</span> {failures.join(" · ")}
        </p>
      ) : null}

      <div className="mm-round-strip" aria-label="Negotiation rounds">
        {negotiation.rounds.map((round) => (
          <span
            key={`${negotiation.seller_id}-${round.round}`}
            className={`mm-round-chip ${
              offer?.offer_id === round.offer_id ? "is-latest" : ""
            }`}
          >
            <span>R{round.round}</span>
            <b>{money(round.total_cents)}</b>
          </span>
        ))}
      </div>

      <footer className="mm-seller-footer">
        <span className="mm-mono-note">
          task {negotiation.task_id ? negotiation.task_id.slice(-8) : "pending"}
        </span>
        <button
          type="button"
          className="mm-text-button"
          onClick={() => onViewWire(negotiation.seller_id)}
          aria-label={`View A2A for ${negotiation.seller_name}`}
        >
          View A2A <ArrowUpRight size={13} aria-hidden="true" />
        </button>
      </footer>
    </article>
  );
}
