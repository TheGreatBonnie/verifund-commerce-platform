import { auth } from "@clerk/nextjs/server";
import { notFound } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { BlockersPanel } from "@/components/seller/blockers-panel";
import { DisputePanel } from "@/components/seller/dispute-panel";
import { EvidenceProgress } from "@/components/seller/evidence-progress";
import {
  FulfillmentBackLink,
  FulfillmentTabs,
} from "@/components/seller/fulfillment-tabs";
import { RequirementList } from "@/components/seller/requirement-list";
import { TransactionStatusBadge } from "@/components/seller/seller-status-badge";
import { UploadEvidenceDialog } from "@/components/seller/upload-evidence-dialog";
import { loadSeller } from "@/lib/seller-api";
import { countVerifiedRequirements } from "@/lib/seller-evidence";
import { formatDateTime, money } from "@/lib/format";
import type { SellerProjection } from "@/lib/seller-types";

export const dynamic = "force-dynamic";

const UPLOAD_STATES = new Set([
  "FUNDED",
  "FULFILLMENT_PENDING",
  "VERIFICATION_PENDING",
  "REMEDIATION_REQUIRED",
]);

export default async function FulfillmentEvidencePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  await auth.protect();
  const { id } = await params;
  const result = await loadSeller<SellerProjection>(
    `/seller/transactions/${encodeURIComponent(id)}`,
    id,
  );

  if (!result.ok) {
    if (result.status === 404) notFound();
    return (
      <>
        <FulfillmentBackLink />
        <Alert message={result.error} />
      </>
    );
  }

  const projection = result.data;
  const results = projection.evidence?.requirements ?? [];
  const items = projection.evidence?.items ?? [];
  const sellerRequired = projection.requirements.filter(
    (requirement) => requirement.owner === "seller" && requirement.required,
  ).length;
  const verified = countVerifiedRequirements(results);
  const canUpload = UPLOAD_STATES.has(projection.state);
  const products = projection.line_items.map((item) => item.name).join(", ");

  return (
    <>
      <FulfillmentBackLink />

      <header className="mm-seller-detail-head">
        <div>
          <p className="mm-kicker">
            Evidence checklist / {projection.transaction_id}
          </p>
          <h1>{products || projection.run_id}</h1>
          <p className="mm-seller-detail-meta">
            {money(projection.amount_cents)} · Agreement version{" "}
            {projection.agreement_version}
            {projection.evidence?.deadline
              ? ` · Due ${formatDateTime(projection.evidence.deadline)}`
              : ""}
            {projection.deadlines?.inspection
              ? ` · Inspection by ${formatDateTime(projection.deadlines.inspection)}`
              : ""}
          </p>
        </div>
        <div className="mm-seller-detail-badges">
          <TransactionStatusBadge state={projection.state} />
          {canUpload ? (
            <UploadEvidenceDialog
              transactionId={projection.transaction_id}
              agreementVersion={projection.agreement_version}
              requirements={projection.requirements}
              evidenceItems={items}
              label="Upload evidence"
            />
          ) : null}
        </div>
      </header>

      <FulfillmentTabs
        transactionId={projection.transaction_id}
        active="evidence"
      />

      <BlockersPanel blockers={projection.blockers ?? []} />

      <div className="mm-seller-summary-grid">
        <section className="mm-panel" aria-label="Verified count">
          <p className="mm-kicker">Requirements verified</p>
          <p className="mm-seller-summary-value">
            {verified}/{sellerRequired || projection.requirements.length}
          </p>
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
        <section className="mm-panel" aria-label="Submissions">
          <p className="mm-kicker">Submissions</p>
          <p className="mm-seller-summary-value">{items.length}</p>
          <p className="mm-mono-note">
            Every submission is associated with the requirement it supports.
          </p>
        </section>
      </div>

      {projection.dispute ? (
        <DisputePanel
          transactionId={projection.transaction_id}
          dispute={projection.dispute}
        />
      ) : null}

      <section className="mm-panel" aria-label="Evidence checklist">
        <div className="mm-panel-head">
          <div>
            <p className="mm-kicker">Checklist</p>
            <h2>Evidence checklist</h2>
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
      </section>
    </>
  );
}
