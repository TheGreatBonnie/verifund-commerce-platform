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
  const resolved = Boolean(dispute.resolution || dispute.resolved_at || dispute.status === "resolved");
  return (
    <section className="mm-panel mm-seller-dispute" aria-label="Dispute">
      <div className="mm-panel-head">
        <div>
          <p className="mm-kicker">Buyer dispute</p>
          <h2>{resolved ? "Dispute status" : "Respond to the claim"}</h2>
        </div>
        <span className={`mm-status ${resolved ? "" : "is-amber"}`}>
          {resolved ? "Dispute resolved" : "Dispute open"}
        </span>
      </div>

      <dl className="mm-seller-facts">
        <div className="mm-seller-fact">
          <dt>Reason</dt>
          <dd>{reasonLabel(dispute.reason_code)}</dd>
        </div>
        {dispute.claim_type ? (
          <div className="mm-seller-fact">
            <dt>Claim type</dt>
            <dd>{reasonLabel(dispute.claim_type)}</dd>
          </div>
        ) : null}
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
        {dispute.resolution ? (
          <div className="mm-seller-fact">
            <dt>Resolution</dt>
            <dd>{reasonLabel(dispute.resolution)}</dd>
          </div>
        ) : null}
        {dispute.resolved_at ? (
          <div className="mm-seller-fact">
            <dt>Resolved</dt>
            <dd>{formatDateTime(dispute.resolved_at)}</dd>
          </div>
        ) : null}
      </dl>

      <blockquote className="mm-seller-dispute-claim">
        <span className="mm-kicker">Buyer claim</span>
        <p>{dispute.claim}</p>
        {dispute.rationale ? <p className="mm-mono-note">Rationale: {dispute.rationale}</p> : null}
      </blockquote>

      {!resolved ? <DisputeEvidenceForm transactionId={transactionId} /> : null}
    </section>
  );
}
