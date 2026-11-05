const LABELS: Record<string, string> = {
  new: "Brief",
  brief_ready: "Brief parsed",
  needs_clarification: "Brief needed",
  sellers_discovered: "Sellers discovered",
  sourcing_planned: "RFQ composed",
  negotiating: "Negotiating",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  rejected: "Rejected",
  ordering: "Ordering",
  ordered: "Ordered",
  order_failed: "Order failed",
  no_award: "No award",
  failed: "Failed",
  awarded: "Awarded",
  agreed: "Agreed",
  funding_pending: "Funding pending",
  funded: "Funded",
  fulfillment_pending: "Fulfillment pending",
  verification_pending: "Verification pending",
  remediation_required: "Remediation required",
  release_permitted: "Release permitted",
  payout_pending: "Payout pending",
  released: "Released",
  review_required: "Review required",
  dispute_open: "Dispute open",
  refunded: "Refunded",
  canceled: "Canceled",
};

export const LEGACY_TERMINAL_STAGES = new Set([
  "ordered",
  "rejected",
  "failed",
  "order_failed",
  "no_award",
]);

export const SETTLEMENT_TERMINAL_STAGES = new Set([
  "released",
  "refunded",
  "canceled",
  "failed",
  "rejected",
  "no_award",
]);

export const PAUSED_STAGES = new Set([
  "awaiting_approval",
  "funding_pending",
  "verification_pending",
  "remediation_required",
  "release_permitted",
  "review_required",
  "dispute_open",
]);

export function stageLabel(stage?: string): string {
  return LABELS[(stage ?? "new").toLowerCase()] ?? "Brief";
}

export function isTerminalStage(
  stage?: string,
  settlement = false,
): boolean {
  if (!stage) return false;
  const normalized = stage.toLowerCase();
  if (settlement) {
    return SETTLEMENT_TERMINAL_STAGES.has(normalized);
  }
  return LEGACY_TERMINAL_STAGES.has(normalized);
}

export function isPausedStage(stage?: string): boolean {
  return PAUSED_STAGES.has((stage ?? "").toLowerCase());
}
