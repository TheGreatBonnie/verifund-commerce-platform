import { ShieldCheck } from "lucide-react";
import { formatDateTime } from "@/lib/format";
import type {
  SellerAgreementView,
  SellerProjection,
} from "@/lib/seller-types";

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="mm-seller-fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export function AgreementSummary({
  projection,
  agreement,
}: {
  projection: SellerProjection;
  agreement: SellerAgreementView | null;
}) {
  const terms = agreement?.terms;
  const deliveryDays = terms?.delivery?.delivery_days ?? projection.delivery_days;

  return (
    <section className="mm-panel" aria-label="Agreement summary">
      <div className="mm-panel-head">
        <div>
          <p className="mm-kicker">Agreement</p>
          <h2>Approved terms</h2>
        </div>
        <span className="mm-status">Read-only</span>
      </div>

      <dl className="mm-seller-facts">
        <Fact
          label="Agreement"
          value={
            projection.agreement_id
              ? `${projection.agreement_id} · v${projection.agreement_version}`
              : `Version ${projection.agreement_version}`
          }
        />
        <Fact label="Status" value={agreement?.status ?? "Current version"} />
        <Fact label="Delivery window" value={`${deliveryDays} days`} />
        <Fact
          label="Warranty"
          value={`${terms?.warranty_months ?? projection.warranty_months} months`}
        />
        <Fact
          label="Returns"
          value={`${terms?.returns_days ?? projection.returns_days} days`}
        />
        <Fact
          label="Inspection"
          value={
            terms?.inspection?.period_hours
              ? `${terms.inspection.period_hours} hours after delivery`
              : "Per agreement terms"
          }
        />
        {terms?.items?.length ? (
          <Fact
            label="Items"
            value={terms.items
              .map((item) => `${item.name ?? item.sku ?? "Item"} ×${item.quantity ?? 1}`)
              .join(", ")}
          />
        ) : projection.line_items.length ? (
          <Fact
            label="Items"
            value={projection.line_items
              .map((item) => `${item.name} ×${item.quantity}`)
              .join(", ")}
          />
        ) : null}
        {agreement?.agreed_at ? (
          <Fact label="Agreed at" value={formatDateTime(agreement.agreed_at)} />
        ) : null}
        {terms?.dispute_window_hours ? (
          <Fact
            label="Dispute window"
            value={`${terms.dispute_window_hours} hours`}
          />
        ) : null}
      </dl>

      <p className="mm-seller-agreement-note">
        <ShieldCheck size={14} aria-hidden="true" />
        These terms govern this fulfillment task. Evidence submitted against a
        superseded agreement version is rejected.
      </p>
    </section>
  );
}
