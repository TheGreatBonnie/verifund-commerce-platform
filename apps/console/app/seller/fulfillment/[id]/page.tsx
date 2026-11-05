import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { AgreementSummary } from "@/components/seller/agreement-summary";
import { DisputePanel } from "@/components/seller/dispute-panel";
import { EvidenceProgress } from "@/components/seller/evidence-progress";
import {
  FulfillmentBackLink,
  FulfillmentTabs,
} from "@/components/seller/fulfillment-tabs";
import { RequirementList } from "@/components/seller/requirement-list";
import {
  PayoutStatusBadge,
  TransactionStatusBadge,
} from "@/components/seller/seller-status-badge";
import { UploadEvidenceDialog } from "@/components/seller/upload-evidence-dialog";
import { loadSeller } from "@/lib/seller-api";
import { countVerifiedRequirements } from "@/lib/seller-evidence";
import { formatDateTime, money } from "@/lib/format";
import {
  paymentStateLabel,
  paymentStateTone,
  nextActionLabel,
} from "@/lib/seller-status";
import type {
  SellerAgreementView,
  SellerProjection,
} from "@/lib/seller-types";

export const dynamic = "force-dynamic";

const UPLOAD_STATES = new Set([
  "FUNDED",
  "FULFILLMENT_PENDING",
  "VERIFICATION_PENDING",
  "REMEDIATION_REQUIRED",
]);

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="mm-seller-fact">
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

export default async function FulfillmentDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await auth.protect();
  const { id } = await params;
  const projectionResult = await loadSeller<SellerProjection>(
    `/seller/transactions/${encodeURIComponent(id)}`,
    id,
  );

  if (!projectionResult.ok) {
    if (projectionResult.status === 404) notFound();
    return (
      <>
        <FulfillmentBackLink />
        <Alert message={projectionResult.error} />
      </>
    );
  }

  const projection = projectionResult.data;
  const agreementResult = projection.agreement_id
    ? await loadSeller<SellerAgreementView>(
        `/seller/agreements/${encodeURIComponent(projection.agreement_id)}`,
        id,
      )
    : null;
  const agreement =
    agreementResult?.ok === true ? agreementResult.data : null;

  const results = projection.evidence?.requirements ?? [];
  const items = projection.evidence?.items ?? [];
  const sellerRequired = projection.requirements.filter(
    (requirement) => requirement.owner === "seller" && requirement.required,
  ).length;
  const verified = countVerifiedRequirements(results);
  const canUpload = UPLOAD_STATES.has(projection.state);
  const products = projection.line_items.map((item) => item.name).join(", ");
  const evidenceDeadline =
    projection.deadlines.evidence ?? projection.evidence?.deadline ?? null;

  return (
    <>
      <FulfillmentBackLink />

      <header className="mm-seller-detail-head">
        <div>
          <p className="mm-kicker">
            Fulfillment workspace / {projection.transaction_id}
          </p>
          <h1>{products || projection.run_id}</h1>
          <p className="mm-seller-detail-meta">
            Transaction {projection.transaction_id} · Agreement version{" "}
            {projection.agreement_version} · Next:{" "}
            {nextActionLabel(
              projection.allowed_actions.includes("upload_evidence")
                ? "submit_evidence"
                : projection.state === "DISPUTE_OPEN"
                  ? "respond_to_dispute"
                  : "none",
            )}
          </p>
        </div>
        <div className="mm-seller-detail-badges">
          <span className={`mm-status ${paymentStateTone(projection.state) === "signal" ? "is-signal" : paymentStateTone(projection.state) === "amber" ? "is-amber" : ""}`}>
            {paymentStateLabel(projection.state)}
          </span>
          <TransactionStatusBadge state={projection.state} />
          {canUpload ? (
            <UploadEvidenceDialog
              transactionId={projection.transaction_id}
              agreementVersion={projection.agreement_version}
              requirements={projection.requirements}
              label="Upload evidence"
            />
          ) : null}
          {agreement ? (
            <Link
              href={`/seller/fulfillment/${encodeURIComponent(projection.transaction_id)}#agreement`}
              className="mm-button mm-button-outline"
            >
              View agreement
            </Link>
          ) : null}
        </div>
      </header>

      <FulfillmentTabs transactionId={projection.transaction_id} active="overview" />

      <div className="mm-seller-summary-grid">
        <section className="mm-panel" aria-label="Order value">
          <p className="mm-kicker">Order value</p>
          <p className="mm-seller-summary-value">{money(projection.amount_cents)}</p>
          <p className="mm-mono-note">{projection.currency} · {projection.quantity} units</p>
        </section>
        <section className="mm-panel" aria-label="Fulfillment deadline">
          <p className="mm-kicker">Fulfillment deadline</p>
          <p className="mm-seller-summary-value">
            {evidenceDeadline ? formatDateTime(evidenceDeadline) : "Per agreement"}
          </p>
          <p className="mm-mono-note">
            {projection.deadlines.inspection
              ? `Inspection by ${formatDateTime(projection.deadlines.inspection)}`
              : "Based on agreement terms"}
          </p>
        </section>
        <section className="mm-panel" aria-label="Requirements verified">
          <div className="mm-seller-progress-head">
            <p className="mm-kicker">Requirements verified</p>
            <strong>
              {verified}/{sellerRequired || projection.requirements.length}
            </strong>
          </div>
          <EvidenceProgress
            count={{
              submitted: results.filter((r) => r.status !== "not_submitted").length,
              required: sellerRequired || projection.requirements.length,
              complete: verified === (sellerRequired || projection.requirements.length),
              received_kinds: [],
            }}
            showLabel={false}
          />
        </section>
      </div>

      <div className="mm-seller-detail-grid">
        <div className="mm-seller-detail-main">
          {projection.dispute ? (
            <DisputePanel
              transactionId={projection.transaction_id}
              dispute={projection.dispute}
            />
          ) : null}

          <section className="mm-panel" aria-label="Fulfillment requirements">
            <div className="mm-panel-head">
              <div>
                <p className="mm-kicker">Obligations</p>
                <h2>Fulfillment requirements</h2>
              </div>
              <TransactionStatusBadge state={projection.state} />
            </div>
            <RequirementList
              transactionId={projection.transaction_id}
              agreementId={projection.agreement_id}
              agreementVersion={projection.agreement_version}
              requirements={projection.requirements}
              results={results}
              items={items}
              canUpload={canUpload}
            />
            <p className="mm-seller-section-link">
              <Link
                href={`/seller/fulfillment/${encodeURIComponent(projection.transaction_id)}/evidence`}
              >
                Open the evidence checklist
              </Link>
            </p>
          </section>

          <div id="agreement">
            <AgreementSummary projection={projection} agreement={agreement} />
          </div>
        </div>

        <aside className="mm-seller-detail-rail">
          <section className="mm-panel" aria-label="Transaction details">
            <p className="mm-kicker">Transaction</p>
            <dl className="mm-seller-facts mm-seller-facts-rail">
              <Fact label="Transaction" value={projection.transaction_id} />
              <Fact label="Run" value={projection.run_id} />
              <Fact label="State" value={projection.state} />
              <Fact label="Payment" value={paymentStateLabel(projection.state)} />
              {projection.purchase_order ? (
                <>
                  <Fact
                    label="Seller order"
                    value={projection.purchase_order.seller_order_id}
                  />
                  {projection.purchase_order.tracking_number ? (
                    <Fact
                      label="Tracking"
                      value={projection.purchase_order.tracking_number}
                    />
                  ) : null}
                  {projection.purchase_order.carrier ? (
                    <Fact
                      label="Carrier"
                      value={projection.purchase_order.carrier}
                    />
                  ) : null}
                </>
              ) : null}
              <Fact
                label="Payout"
                value={
                  projection.payout
                    ? projection.payout.status
                    : "Not payable yet"
                }
              />
              <Fact label="Updated" value={formatDateTime(projection.updated_at)} />
            </dl>
            <div className="mm-seller-rail-badge">
              <PayoutStatusBadge status={projection.payout?.status} />
            </div>
          </section>

          <section className="mm-panel" aria-label="Next steps">
            <p className="mm-kicker">Next steps</p>
            <ul className="mm-seller-next-steps">
              <li>
                <Link
                  href={`/seller/fulfillment/${encodeURIComponent(projection.transaction_id)}/evidence`}
                >
                  Evidence checklist
                </Link>
              </li>
              <li>
                <Link
                  href={`/seller/fulfillment/${encodeURIComponent(projection.transaction_id)}/activity`}
                >
                  Transaction activity
                </Link>
              </li>
              <li>
                <Link href="/seller/payouts">Payouts</Link>
              </li>
            </ul>
            <p className="mm-mono-note">
              Your Seller Agent can explain evidence requirements and notify you
              when a review needs attention.
            </p>
          </section>
        </aside>
      </div>
    </>
  );
}
