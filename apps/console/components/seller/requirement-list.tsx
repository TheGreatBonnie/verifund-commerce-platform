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
import { DeclarationDialog } from "./declaration-dialog";
import { RequirementStatusBadge } from "./seller-status-badge";
import { UploadEvidenceDialog } from "./upload-evidence-dialog";

const STAGE_ORDER = [
  "product_identity",
  "product_condition",
  "product_compliance",
  "packaging",
  "delivery",
];

function reasonLabel(reason: string): string {
  return reason.replaceAll("_", " ");
}

function actionOwnerLabel(owner?: string | null): string {
  switch (owner) {
    case "seller":
      return "Seller action";
    case "buyer":
      return "Buyer action";
    case "reviewer":
      return "Reviewer";
    case "system":
      return "System";
    case "none":
      return "No action";
    default:
      return owner ? owner.replaceAll("_", " ") : "No action";
  }
}

function stageTitle(stage: string): string {
  return stage.replaceAll("_", " ");
}

function stageSortIndex(stage?: string | null): number {
  if (!stage) return STAGE_ORDER.length + 1;
  const idx = STAGE_ORDER.indexOf(stage);
  return idx === -1 ? STAGE_ORDER.length : idx;
}

function coveredViews(items: EvidenceItem[], requirementId: string): string[] {
  const views = new Set<string>();
  for (const item of items) {
    if (item.requirement_id === requirementId && item.view_label) {
      views.add(item.view_label);
    }
  }
  return Array.from(views);
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

  const groups = new Map<string, Requirement[]>();
  for (const requirement of requirements) {
    const key = requirement.stage || "other";
    const existing = groups.get(key) ?? [];
    existing.push(requirement);
    groups.set(key, existing);
  }
  const orderedStages = Array.from(groups.keys()).sort(
    (a, b) => stageSortIndex(a) - stageSortIndex(b) || a.localeCompare(b),
  );

  return (
    <div className="mm-seller-requirement-sections">
      {orderedStages.map((stage) => {
        const stageRequirements = groups.get(stage) ?? [];
        const stagePassed = stageRequirements.filter((req) => {
          const result = results.find((entry) => entry.requirement_id === req.requirement_id);
          return requirementStatusFor(result) === "pass";
        }).length;
        return (
          <section key={stage} className="mm-seller-stage-section" aria-label={`${stageTitle(stage)} stage`}>
            <header className="mm-seller-stage-head">
              <div>
                <p className="mm-kicker">Stage</p>
                <h3>{stageTitle(stage)}</h3>
              </div>
              <span className="mm-seller-chip">
                {stagePassed}/{stageRequirements.length} passed
              </span>
            </header>

            <div className="mm-seller-requirement-list">
              {stageRequirements.map((requirement) => {
                const result = results.find(
                  (entry) => entry.requirement_id === requirement.requirement_id,
                );
                const status = requirementStatusFor(result);
                const submissions = submissionsForRequirement(items, requirement);
                const sellerOwned = requirement.owner === "seller";
                const isDeclaration = requirement.source === "declaration";
                const views = requirement.required_views ?? [];
                const covered = coveredViews(items, requirement.requirement_id);
                const missingViews = views.filter((view) => !covered.includes(view));

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
                          <span className="mm-seller-chip">{requirementOwnerLabel(requirement)}</span>
                          {requirement.stage ? <span className="mm-seller-chip">Stage: {requirement.stage}</span> : null}
                          {typeof requirement.min_items === "number" && requirement.min_items > 1 ? (
                            <span className="mm-seller-chip">{submissions.length}/{requirement.min_items} items</span>
                          ) : null}
                          {views.length ? (
                            <span className="mm-seller-chip">Views {covered.length}/{views.length}</span>
                          ) : null}
                          {result?.action_owner ? (
                            <span className="mm-seller-chip">{actionOwnerLabel(result.action_owner)}</span>
                          ) : null}
                          {requirement.source === "reference" ? (
                            <>
                              <span className="mm-seller-chip">Reference</span>
                              <span className="mm-seller-chip">
                                <Link2 size={10} aria-hidden="true" />
                                {requirement.kind === "shipment_manifest" ? "Tracking/reference" : "URL or reference"}
                              </span>
                            </>
                          ) : isDeclaration ? (
                            <span className="mm-seller-chip">Declaration</span>
                          ) : (
                            requirement.accepted_formats.map((format) => (
                              <span className="mm-seller-chip" key={format}>{formatMediaType(format)}</span>
                            ))
                          )}
                        </div>
                      </div>
                      <div className="mm-seller-requirement-actions">
                        <RequirementStatusBadge status={status} />
                        {sellerOwned && canUpload && isDeclaration ? (
                          <DeclarationDialog transactionId={transactionId} requirement={requirement} compact />
                        ) : sellerOwned && canUpload ? (
                          <UploadEvidenceDialog
                            transactionId={transactionId}
                            agreementVersion={agreementVersion}
                            requirements={requirements}
                            evidenceItems={items}
                            defaultRequirementId={requirement.requirement_id}
                            label={requirement.source === "reference" ? "Submit" : "Upload"}
                            compact
                          />
                        ) : null}
                      </div>
                    </div>

                    {views.length ? (
                      <p className="mm-seller-requirement-reasons">
                        Required views: {views.map((v) => v.replaceAll("_", " ")).join(", ")}
                        {missingViews.length
                          ? ` · Missing: ${missingViews.map((v) => v.replaceAll("_", " ")).join(", ")}`
                          : " · All views covered"}
                      </p>
                    ) : null}

                    {result?.reasons?.length ? (
                      <p className="mm-seller-requirement-reasons">{result.reasons.map(reasonLabel).join(" · ")}</p>
                    ) : null}

                    {requirement.checks.length ? (
                      <div className="mm-seller-checks">
                        <span className="mm-kicker">Checks</span>
                        {requirement.checks.map((check) => (
                          <span key={check.check_id} className="mm-seller-check">
                            {check.check_id.replaceAll("_", " ")} · {check.operator}
                            {check.verification_method === "extraction" ? " · extraction" : ""}
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
                                <span className="mm-seller-submission-type">{artifactLabel(item)}</span>
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
                                  {item.captured_at ? ` · captured ${formatDateTime(item.captured_at)}` : ""}
                                  {item.view_label ? ` · view ${item.view_label}` : ""}
                                  {item.reason_code ? ` · ${item.reason_code}` : ""}
                                  {isReference ? "" : ` · ${formatBytes(item.size_bytes)}`}
                                </span>
                              </div>
                              <div className="mm-seller-submission-side">
                                <span className="mm-seller-chip">{item.scan_status ?? "received"}</span>
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
                      {agreementId ? ` · Linked to ${agreementId} v${agreementVersion}` : ` · Agreement version ${agreementVersion}`}
                    </footer>
                  </article>
                );
              })}
            </div>
          </section>
        );
      })}
    </div>
  );
}
