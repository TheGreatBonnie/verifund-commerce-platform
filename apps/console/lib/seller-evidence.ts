import type {
  EvidenceItem,
  Requirement,
  RequirementResult,
  SellerTransactionSummary,
} from "./seller-types";

export function requirementResultFor(
  results: RequirementResult[] | undefined,
  requirementId: string,
): RequirementResult | undefined {
  return results?.find((result) => result.requirement_id === requirementId);
}

export function submissionsForRequirement(
  items: EvidenceItem[] | undefined,
  requirement: Requirement,
): EvidenceItem[] {
  if (!items?.length) return [];
  return items.filter((item) => {
    if (item.purpose && item.purpose !== "requirement") return false;
    if (item.requirement_id) return item.requirement_id === requirement.requirement_id;
    return requirement.kind !== "other" && item.kind === requirement.kind;
  });
}

export function requirementStatusFor(
  result: RequirementResult | undefined,
): string {
  return result?.status ?? "not_submitted";
}

export function countVerifiedRequirements(
  results: RequirementResult[] | undefined,
): number {
  return results?.filter((result) => result.status === "pass").length ?? 0;
}

export function allRequirementsVerified(
  results: RequirementResult[] | undefined,
  required: number,
): boolean {
  return required > 0 && countVerifiedRequirements(results) === required;
}

export function artifactTypeFor(item: EvidenceItem): string {
  if (item.artifact_type) return item.artifact_type;
  if (item.reference) return "reference";
  return "file";
}

export function artifactLabel(item: EvidenceItem): string {
  if (artifactTypeFor(item) === "reference") return "Reference";
  const media = (item.media_type ?? "").toLowerCase();
  if (media.startsWith("image/")) return "Image";
  if (media.startsWith("video/")) return "Video";
  if (media === "application/pdf") return "PDF";
  if (media === "text/csv") return "CSV";
  if (media.startsWith("text/")) return "Document";
  return "File";
}

export function artifactName(item: EvidenceItem): string {
  return item.reference || item.original_filename || item.evidence_id;
}

export function formatBytes(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatMediaType(mediaType?: string | null): string {
  if (!mediaType) return "Unknown";
  const known: Record<string, string> = {
    "image/jpeg": "JPG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "video/mp4": "MP4",
    "video/quicktime": "MOV",
    "video/webm": "WEBM",
    "text/csv": "CSV",
    "text/plain": "TXT",
    "application/pdf": "PDF",
    "application/json": "JSON",
  };
  return known[mediaType.toLowerCase()] ?? mediaType;
}

export function requirementOwnerLabel(requirement: Requirement): string {
  if (requirement.owner === "system") return "System generated";
  if (requirement.owner === "buyer") return "Buyer supplied";
  return "Seller submission";
}

export function transactionProduct(summary: SellerTransactionSummary): string {
  const names = summary.line_items.map((item) => item.name).filter(Boolean);
  return names.length ? names.join(", ") : summary.run_id;
}

export function transactionProducts(summary: SellerTransactionSummary): string {
  return transactionProduct(summary);
}

export function eventSummary(payload: Record<string, unknown>): string {
  const candidates = [
    payload.message,
    payload.reason,
    payload.detail,
    payload.note,
    payload.status,
    payload.tracking_number,
    payload.seller_order_id,
    payload.state,
  ];
  for (const value of candidates) {
    if (typeof value === "string" && value.trim()) return value;
  }
  return "Recorded";
}
