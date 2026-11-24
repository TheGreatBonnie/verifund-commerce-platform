import {
  BadgeCheck,
  CheckCircle2,
  Clock3,
  FileCheck2,
  Info,
  LockKeyhole,
  ShieldCheck,
} from "lucide-react";

import { ChatHandoffLink } from "../shared/chat-handoff-link";
import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { formatDate, formatMoney, labelize } from "../shared/format";
import { RawDataDisclosure } from "../shared/raw-data-disclosure";

const EVIDENCE_LABELS: Record<string, string> = {
  shipment_manifest: "Shipment manifest",
  delivery_confirmation: "Delivery confirmation",
  invoice: "Invoice",
  other: "Other evidence",
};

const REMEDY_LABELS: Record<string, string> = {
  cancel_and_refund: "Cancel and full refund",
  refund_or_replacement: "Refund or replacement",
};

function labelFor(map: Record<string, string>, value: unknown) {
  const key = String(value ?? "");
  return map[key] ?? key.replaceAll("_", " ");
}

function formatStamp(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return formatDate(date.toISOString());
}

export function BuyerAgreementCard({
  agreement,
  transactionId,
}: {
  agreement: Record<string, any> | null | undefined;
  transactionId: string;
}) {
  const a = agreement ?? {};
  const terms = a.terms && typeof a.terms === "object" ? a.terms : {};
  const totals = (terms.totals ?? {}) as Record<string, any>;
  const inspection = (terms.inspection ?? {}) as Record<string, any>;
  const delivery = (terms.delivery ?? {}) as Record<string, any>;
  const remedies = (terms.remedies ?? {}) as Record<string, any>;
  const evidence = Array.isArray(terms.evidence_required)
    ? terms.evidence_required
    : [];
  const items = Array.isArray(terms.items)
    ? terms.items
    : Array.isArray(a.line_items)
      ? a.line_items
      : [];
  const item = items[0] ?? {};
  const attrs = (item.attributes ?? {}) as Record<string, any>;
  const parties = (terms.parties ?? {}) as Record<string, any>;

  const id = String(a.agreement_id ?? a.id ?? "");
  const version = Number(
    a.agreement_version ?? a.current_version ?? a.version?.agreement_version ?? 1,
  );
  const currency = String(totals.currency ?? a.currency ?? "USD");
  const status = String(a.status ?? "unknown");
  const approved = a.status === "AGREED";
  const hash = String(a.agreement_hash ?? a.version?.agreement_hash ?? "");
  const expiresAt = formatStamp(a.expires_at);
  const createdAt = formatStamp(a.created_at);
  const sellerName =
    parties.seller?.display_name ?? a.seller_name ?? a.seller_id ?? "Seller";
  const productName = item.name ?? a.product_name ?? "Agreement item";
  const quantity = item.quantity ?? a.quantity ?? 1;
  const specs = String(attrs.specs ?? "")
    .split("·")
    .map((part) => part.trim())
    .filter(Boolean);
  const warranty = a.warranty_months ?? terms.warranty_months;
  const returns = a.returns_days ?? terms.returns_days;
  const inspectionHours =
    a.inspection_period_hours ?? terms.inspection?.period_hours;
  const chips = [
    attrs.condition,
    ...specs,
    warranty ? `${warranty}-month warranty` : null,
    returns ? `${returns}-day returns` : null,
    inspectionHours ? `${inspectionHours}-hour inspection` : null,
  ].filter((chip): chip is string => Boolean(chip));
  const visibleChips = chips.slice(0, 4);
  const overflowChips = chips.length - visibleChips.length;
  const startsOn = String(inspection.starts_on ?? "delivery")
    .replaceAll("_", " ")
    .toLowerCase();

  return (
    <div className="mm-approval mm-buyer-agreement" data-testid="buyer-agreement-card">
      <div className="mm-verifund-head">
        <div>
          <p className="mm-kicker">Agreement</p>
          <h3>
            <span>{id || "Agreement"}</span>
          </h3>
        </div>
        <BuyerStatusPill value={status} label={labelize(status)} />
      </div>

      <div className="mm-verifund-detail">
        <div>
          <p className="mm-kicker">Version</p>
          <strong>v{version}</strong>
        </div>
        <div>
          <p className="mm-kicker">Expires</p>
          <strong>{expiresAt ?? "Not set"}</strong>
        </div>
      </div>

      <div className="mm-product" data-testid="buyer-agreement-product">
        <div className="mm-product-tile">
          {attrs.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={String(attrs.image_url)} alt={String(productName)} />
          ) : null}
        </div>
        <div className="mm-product-body">
          <h4 className="mm-product-name">
            {String(productName)}
            {items.length > 1 ? ` (+${items.length - 1} more)` : ""}
          </h4>
          <p className="mm-product-seller">
            {String(sellerName)}
            <BadgeCheck size={12} aria-label="Verified seller" />
          </p>
          <ul className="mm-product-chips">
            {visibleChips.map((chip, index) => (
              <li key={`${chip}-${index}`}>{chip}</li>
            ))}
            {overflowChips > 0 ? <li>+{overflowChips} more</li> : null}
          </ul>
          <p className="mm-product-qty">
            Quantity <strong>{String(quantity)}</strong>
          </p>
        </div>
      </div>

      <div className="mm-money" data-testid="buyer-agreement-money">
        <p className="mm-money-label">Agreed commercial terms</p>
        <div className="mm-money-row">
          <span>Product price</span>
          <strong>
            {formatMoney(Number(totals.subtotal_cents ?? a.amount_cents ?? 0), currency)}
          </strong>
        </div>
        <div className="mm-money-row">
          <span>Tracked shipping</span>
          <strong>{formatMoney(Number(totals.shipping_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Taxes</span>
          <strong>{formatMoney(Number(totals.tax_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Fees</span>
          <strong>{formatMoney(Number(totals.fees_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-total">
          <span>Total payable</span>
          <strong>
            {formatMoney(Number(totals.total_cents ?? a.amount_cents ?? 0), currency)}{" "}
            <em>{currency}</em>
          </strong>
        </div>
      </div>

      <div className="mm-inspection" data-testid="buyer-agreement-inspection">
        <p className="mm-money-label">
          <Clock3 size={11} /> Inspection and verification
        </p>
        <dl className="mm-inspection-grid">
          <div>
            <dt>Inspection window</dt>
            <dd>
              {inspection.period_hours ?? a.inspection_period_hours ?? 0} hours after{" "}
              {startsOn}
            </dd>
          </div>
          <div>
            <dt>Verification checklist</dt>
            <dd>
              <ul className="mm-check-list">
                {evidence.length ? (
                  evidence.map((entry: string) => (
                    <li key={entry}>
                      <CheckCircle2 size={11} />
                      {labelFor(EVIDENCE_LABELS, entry)}
                    </li>
                  ))
                ) : (
                  <li>No evidence requirements listed</li>
                )}
              </ul>
            </dd>
          </div>
        </dl>
      </div>

      <details className="mm-card-section">
        <summary>
          <ShieldCheck size={12} /> Seller obligations
        </summary>
        <ul className="mm-check-list">
          <li>
            <CheckCircle2 size={11} /> Match the agreed product specifications
          </li>
          <li>
            <CheckCircle2 size={11} /> Provide tracked shipping within{" "}
            {delivery.delivery_days ?? a.delivery_days ?? 0} days
          </li>
          <li>
            <CheckCircle2 size={11} /> Maintain a {warranty ?? 0}-month warranty
          </li>
        </ul>
      </details>

      <details className="mm-card-section">
        <summary>
          <Info size={12} /> Returns and disputes
        </summary>
        <div className="mm-acceptance">
          <div className="mm-acceptance-row">
            <span>Not delivered</span>
            <strong>
              {remedies.non_delivery
                ? labelFor(REMEDY_LABELS, remedies.non_delivery)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Late delivery</span>
            <strong>
              {remedies.late_delivery
                ? labelFor(REMEDY_LABELS, remedies.late_delivery)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Damaged goods</span>
            <strong>
              {remedies.damaged_goods
                ? labelFor(REMEDY_LABELS, remedies.damaged_goods)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Returns window</span>
            <strong>{returns ?? 0} days</strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Dispute window</span>
            <strong>{terms.dispute_window_hours ?? 0} hours</strong>
          </div>
        </div>
      </details>

      <details className="mm-card-section">
        <summary>
          <FileCheck2 size={12} /> Agreement acceptance
        </summary>
        <div className="mm-acceptance">
          <div className="mm-acceptance-row">
            <span>Seller Agent</span>
            <strong className="is-ok">
              {String(a.seller_decision?.status ?? a.seller_decision?.decision ?? "Accepted")}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Buyer</span>
            <strong className={approved ? "is-ok" : "is-pending"}>
              {approved ? "Approved" : "Awaiting approval"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Verifund</span>
            <strong className="is-ok">Validated</strong>
          </div>
          {a.buyer_precheck ?? a.precheck ? (
            <div className="mm-acceptance-row">
              <span>Precheck</span>
              <strong>
                {String(
                  (a.buyer_precheck ?? a.precheck)?.recommendation ??
                    (a.buyer_precheck ?? a.precheck)?.status ??
                    "",
                )}
              </strong>
            </div>
          ) : null}
        </div>
      </details>

      <details className="mm-card-section">
        <summary>
          <LockKeyhole size={12} /> Agreement digest
        </summary>
        <p className="mm-digest">
          <strong>{hash.slice(0, 16) || "unavailable"}</strong>
          <span>Created {createdAt ?? "unknown"}</span>
          <span>v{version}</span>
        </p>
      </details>

      <div className="mm-buyer-inline-actions mm-buyer-agreement-actions">
        <ChatHandoffLink transactionId={transactionId} intent="review">
          Review agreement in chat
        </ChatHandoffLink>
      </div>

      <RawDataDisclosure label="View raw agreement" value={agreement} />
    </div>
  );
}
