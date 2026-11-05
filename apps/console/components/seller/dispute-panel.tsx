import { DisputeEvidenceForm } from "@/components/seller/dispute-evidence-form";
import { formatDateTime } from "@/lib/format";
import type { DisputeProjection } from "@/lib/seller-types";

function reasonLabel(reason: string): string {
  return reason.replaceAll("_", " ");
}

export function DisputePanel({
  transactionId,
  dispute,
}: {
  transactionId: string;
  dispute: DisputeProjection;
}) {
  return (
    <section className="mm-panel mm-seller-dispute" aria-label="Open dispute">
      <div className="mm-panel-head">
        <div>
          <p className="mm-kicker">Buyer dispute</p>
          <h2>Respond to the claim</h2>
        </div>
        <span className="mm-status is-amber">Dispute open</span>
      </div>

      <dl className="mm-seller-facts">
        <div className="mm-seller-fact">
          <dt>Reason</dt>
          <dd>{reasonLabel(dispute.reason_code)}</dd>
        </div>
        <div className="mm-seller-fact">
          <dt>Opened</dt>
          <dd>{formatDateTime(dispute.opened_at)}</dd>
        </div>
        <div className="mm-seller-fact">
          <dt>Escalation rung</dt>
          <dd>{dispute.escalation_rung}</dd>
        </div>
        <div className="mm-seller-fact">
          <dt>Requirements</dt>
          <dd>
            {dispute.requirement_ids.length
              ? dispute.requirement_ids.join(", ")
              : "—"}
          </dd>
        </div>
      </dl>

      <blockquote className="mm-seller-dispute-claim">
        <span className="mm-kicker">Buyer claim</span>
        <p>{dispute.claim}</p>
      </blockquote>

      <DisputeEvidenceForm transactionId={transactionId} />
    </section>
  );
}
