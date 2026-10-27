import type { Offer } from "@/lib/types";
import { money, offerStatus, unitPrice } from "@/lib/format";

type OfferCardProps = {
  offer: Offer;
  label?: string;
  winner?: boolean;
};

export function OfferCard({ offer, label, winner = false }: OfferCardProps) {
  return (
    <div className={`mm-offer-card ${winner ? "is-winner" : ""}`}>
      <div className="mm-offer-card-top">
        <span>{label ?? offer.seller_name}</span>
        <span className="mm-status">{winner ? "Winner" : offerStatus(offer.status)}</span>
      </div>
      <div className="mm-offer-card-price">
        <span className="mm-money">{money(offer.total_cents)}</span>
        <span className="mm-offer-card-unit">
          {money(unitPrice(offer))} / unit
        </span>
      </div>
      <dl className="mm-offer-card-facts">
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
      </dl>
    </div>
  );
}
