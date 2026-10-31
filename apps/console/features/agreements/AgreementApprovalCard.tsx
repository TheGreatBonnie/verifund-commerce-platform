"use client";

import type { AgreementView } from "@/lib/types";

type Props = {
  agreement?: AgreementView | any;
  reviewUrl?: string;
  version?: number;
  digest?: string;
  sellerDecision?: any;
  precheck?: any;
};

function money(cents: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(cents / 100);
}

export function AgreementApprovalCard({
  agreement,
  reviewUrl,
  version,
  digest,
  sellerDecision,
  precheck,
}: Props) {
  const a = agreement ?? {};
  const v = version ?? a.current_version ?? a.agreement_version;
  const d = digest ?? a.agreement_hash ?? a.version?.agreement_hash;
  const url = reviewUrl ?? a.review_url ?? `/agreements/${a.agreement_id ?? ""}`;
  const total = a.amount_cents ?? a.total_cents;
  const cur = a.currency ?? "USD";
  const seller = sellerDecision ?? a.seller_decision;
  const pc = precheck ?? a.buyer_precheck ?? a.precheck;

  return (
    <section data-testid="agreement-approval-card" className="mm-agreement-approval-card">
      <p className="mm-kicker">Agreement review</p>
      {total != null ? <p>{money(Number(total), cur)}</p> : null}
      {v != null ? <p>Version {v}</p> : null}
      {d ? <p className="mm-mono-note">{String(d).slice(0, 12)}</p> : null}
      {seller ? (
        <p>Seller: {typeof seller === "string" ? seller : seller.status ?? seller.decision}</p>
      ) : null}
      {pc ? (
        <p>Precheck: {typeof pc === "string" ? pc : pc.recommendation ?? pc.status}</p>
      ) : null}
      <a href={url} data-testid="review-link">
        Review agreement
      </a>
    </section>
  );
}

export default AgreementApprovalCard;
