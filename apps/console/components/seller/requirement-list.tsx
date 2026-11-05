import Link from "next/link";
import { Download, FileCheck2, Link2 } from "lucide-react";
import { EmptyState } from "@/components/ui/empty-state";
import { formatDateTime } from "@/lib/format";
import {
  artifactLabel,
  artifactName,
  artifactTypeFor,
  formatBytes,
  formatMediaType,
  requirementOwnerLabel,
  requirementStatusFor,
  submissionsForRequirement,
} from "@/lib/seller-evidence";
import type {
  EvidenceItem,
  Requirement,
  RequirementResult,
} from "@/lib/seller-types";
import { RequirementStatusBadge } from "./seller-status-badge";
import { UploadEvidenceDialog } from "./upload-evidence-dialog";

function reasonLabel(reason: string): string {
  return reason.replaceAll("_", " ");
}

export function RequirementList({
  transactionId,
  agreementId,
  agreementVersion,
  requirements,
  results,
  items,
  canUpload,
}: {
  transactionId: string;
  agreementId?: string | null;
  agreementVersion: number;
  requirements: Requirement[];
  results: RequirementResult[];
  items: EvidenceItem[];
  canUpload: boolean;
}) {
  if (!requirements.length) {
    return (
      <EmptyState
        title="No requirements published"
        body="This agreement has no requirement catalog. The workspace will update when the agreement exposes one."
      />
    );
  }

  return (
    <div className="mm-seller-requirement-list">
      {requirements.map((requirement) => {
        const result = results.find(
          (entry) => entry.requirement_id === requirement.requirement_id,
        );
        const status = requirementStatusFor(result);
        const submissions = submissionsForRequirement(items, requirement);
        const sellerOwned = requirement.owner === "seller";
        return (
          <article
            className="mm-seller-requirement"
            key={requirement.requirement_id}
            data-status={status}
          >
            <div className="mm-seller-requirement-head">
              <div className="mm-seller-requirement-icon" aria-hidden="true">
                <FileCheck2 size={17} />
              </div>
              <div className="mm-seller-requirement-title">
                <h3>{requirement.title}</h3>
                <p>{requirement.description}</p>
                <div className="mm-seller-chip-row">
                  <span className="mm-seller-chip">{requirement.requirement_id}</span>
                  <span className="mm-seller-chip">
                    {requirementOwnerLabel(requirement)}
                  </span>
                  {requirement.source === "reference" ? (
                    <>
                      <span className="mm-seller-chip">Reference</span>
                      <span className="mm-seller-chip">
                        <Link2 size={10} aria-hidden="true" />
                        {requirement.kind === "shipment_manifest"
                          ? "Tracking number"
                          : "URL or reference"}
                      </span>
                    </>
                  ) : (
                    requirement.accepted_formats.map((format) => (
                      <span className="mm-seller-chip" key={format}>
                        {formatMediaType(format)}
                      </span>
                    ))
                  )}
                </div>
              </div>
              <div className="mm-seller-requirement-actions">
                <RequirementStatusBadge status={status} />
                {sellerOwned && canUpload ? (
                  <UploadEvidenceDialog
                    transactionId={transactionId}
                    agreementVersion={agreementVersion}
                    requirements={requirements}
                    defaultRequirementId={requirement.requirement_id}
                    label="Upload"
                    compact
                  />
                ) : null}
              </div>
            </div>

            {result?.reasons?.length ? (
              <p className="mm-seller-requirement-reasons">
                {result.reasons.map(reasonLabel).join(" · ")}
              </p>
            ) : null}

            {requirement.checks.length ? (
              <div className="mm-seller-checks">
                <span className="mm-kicker">Checks</span>
                {requirement.checks.map((check) => (
                  <span key={check.check_id} className="mm-seller-check">
                    {check.check_id.replaceAll("_", " ")} · {check.operator}
                    {check.verification_method === "extraction"
                      ? " · extraction"
                      : ""}
                  </span>
                ))}
              </div>
            ) : null}

            {submissions.length ? (
              <ul className="mm-seller-submissions">
                {submissions.map((item) => {
                  const isReference = artifactTypeFor(item) === "reference";
                  return (
                    <li key={item.evidence_id}>
                      <div className="mm-seller-submission-main">
                        <span className="mm-seller-submission-type">
                          {artifactLabel(item)}
                        </span>
                        <span className="mm-seller-submission-name">
                          {isReference ? (
                            item.reference
                          ) : (
                            <Link
                              href={`/api/seller/transactions/${encodeURIComponent(transactionId)}/evidence/${encodeURIComponent(item.evidence_id)}`}
                            >
                              {artifactName(item)}
                            </Link>
                          )}
                        </span>
                        <span className="mm-seller-submission-meta">
                          {item.evidence_id} · {formatDateTime(item.created_at)}
                          {item.captured_at
                            ? ` · captured ${formatDateTime(item.captured_at)}`
                            : ""}
                          {isReference ? "" : ` · ${formatBytes(item.size_bytes)}`}
                        </span>
                      </div>
                      <div className="mm-seller-submission-side">
                        <span className="mm-seller-chip">
                          {item.scan_status ?? "received"}
                        </span>
                        {!isReference ? (
                          <Link
                            href={`/api/seller/transactions/${encodeURIComponent(transactionId)}/evidence/${encodeURIComponent(item.evidence_id)}`}
                            className="mm-seller-download"
                            aria-label={`Download ${artifactName(item)}`}
                          >
                            <Download size={13} aria-hidden="true" />
                          </Link>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : null}

            <footer className="mm-seller-requirement-foot">
              Requirement {requirement.requirement_id}
              {agreementId
                ? ` · Linked to ${agreementId} v${agreementVersion}`
                : ` · Agreement version ${agreementVersion}`}
            </footer>
          </article>
        );
      })}
    </div>
  );
}
