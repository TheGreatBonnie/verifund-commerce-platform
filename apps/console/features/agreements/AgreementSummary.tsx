"use client";

import type { AgreementView } from "@/lib/types";

type Props = {
  agreement?: AgreementView | any;
  version?: number;
  total?: number;
  status?: string;
  sellerDecision?: any;
  precheck?: any;
};

function money(cents: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(cents / 100);
}

export function AgreementSummary({
  agreement,
  version,
  total,
  status,
  sellerDecision,
  precheck,
}: Props) {
  const a = agreement ?? {};
  const v = version ?? a.current_version ?? a.agreement_version ?? a.version;
  const t = total ?? a.version?.totals?.total_cents ?? a.amount_cents ?? a.total_cents;
  const cur = a.currency ?? "USD";
  const st = status ?? a.status;
  const sd = sellerDecision ?? a.seller_decision ?? a.sellerDecision;
  const pc = precheck ?? a.buyer_precheck ?? a.precheck;

  return (
    <section data-testid="agreement-summary" className="mm-agreement-summary">
      <div>
        <span className="mm-kicker">Version</span>
        <strong>{v}</strong>
      </div>
      {t != null ? (
        <div>
          <span className="mm-kicker">Total</span>
          <strong>{money(Number(t), cur)}</strong>
        </div>
      ) : null}
      {st ? (
        <div>
          <span className="mm-kicker">Status</span>
          <strong>{String(st)}</strong>
        </div>
      ) : null}
      {sd ? (
        <div data-testid="seller-decision">
          <span className="mm-kicker">Seller decision</span>
          <strong>{typeof sd === "string" ? sd : sd.status ?? sd.decision ?? JSON.stringify(sd)}</strong>
        </div>
      ) : null}
      {pc ? (
        <div data-testid="buyer-precheck">
          <span className="mm-kicker">Buyer precheck</span>
          <strong>{typeof pc === "string" ? pc : pc.recommendation ?? pc.status ?? JSON.stringify(pc)}</strong>
        </div>
      ) : null}
    </section>
  );
}

export default AgreementSummary;
