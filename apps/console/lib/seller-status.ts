import type { SellerEvidenceCount } from "./seller-types";

export type StatusTone = "neutral" | "signal" | "error" | "amber";

/**
 * The single transaction-state vocabulary from spec §3.9.4. Keys are the
 * backend's `TransactionState` enum values; never display the raw enum.
 */
export const TRANSACTION_STATE_LABELS: Record<string, string> = {
  AWARDED: "Awarded",
  AGREED: "Agreed",
  FUNDING_PENDING: "Funding pending",
  FUNDED: "Fulfillment required",
  FULFILLMENT_PENDING: "Evidence required",
  VERIFICATION_PENDING: "In progress",
  REMEDIATION_REQUIRED: "Action required",
  RELEASE_PERMITTED: "Fulfillment verified",
  PAYOUT_PENDING: "Payment processing",
  RELEASED: "Paid",
  REVIEW_REQUIRED: "Under review",
  DISPUTE_OPEN: "Dispute open",
  REFUNDED: "Refunded",
  CANCELED: "Canceled",
  FAILED: "Failed",
};

export const REQUIREMENT_STATUS_LABELS: Record<string, string> = {
  not_submitted: "Required",
  pending_scan: "Processing",
  review: "Under review",
  pass: "Verified",
  fail: "Action required",
};

const TRANSACTION_STATE_TONES: Record<string, StatusTone> = {
  RELEASE_PERMITTED: "signal",
  RELEASED: "signal",
  REVIEW_REQUIRED: "amber",
  REMEDIATION_REQUIRED: "amber",
  DISPUTE_OPEN: "amber",
  PAYOUT_PENDING: "amber",
  CANCELED: "error",
  FAILED: "error",
};

const REQUIREMENT_STATUS_TONES: Record<string, StatusTone> = {
  pass: "signal",
  fail: "error",
  review: "amber",
};

const TERMINAL_STATES = new Set(["RELEASED", "REFUNDED", "CANCELED", "FAILED"]);

const NEXT_ACTION_LABELS: Record<string, string> = {
  submit_evidence: "Submit evidence",
  replace_evidence: "Replace evidence",
  respond_to_dispute: "Respond to dispute",
  none: "No action due",
};

function humanize(value?: string | null): string {
  if (!value) return "Unknown";
  const words = value.replaceAll("_", " ").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function transactionStateLabel(state?: string | null): string {
  return TRANSACTION_STATE_LABELS[state ?? ""] ?? humanize(state);
}

export function transactionStateTone(state?: string | null): StatusTone {
  return TRANSACTION_STATE_TONES[state ?? ""] ?? "neutral";
}

export function requirementStatusLabel(status?: string | null): string {
  return REQUIREMENT_STATUS_LABELS[status ?? ""] ?? humanize(status);
}

export function requirementStatusTone(status?: string | null): StatusTone {
  return REQUIREMENT_STATUS_TONES[status ?? ""] ?? "neutral";
}

export function nextActionLabel(action?: string | null): string {
  return NEXT_ACTION_LABELS[action ?? ""] ?? humanize(action);
}

export function nextActionHref(
  transactionId: string,
  action?: string | null,
): string | null {
  switch (action) {
    case "submit_evidence":
    case "replace_evidence":
    case "respond_to_dispute":
      return `/seller/fulfillment/${encodeURIComponent(transactionId)}/evidence`;
    default:
      return null;
  }
}

export function isTerminalTransaction(state?: string | null): boolean {
  return TERMINAL_STATES.has(state ?? "");
}

export function evidencePercent(count?: SellerEvidenceCount | null): number {
  if (!count || count.required <= 0) return 0;
  return Math.min(100, Math.round((count.submitted / count.required) * 100));
}

export function eventTypeLabel(type?: string | null): string {
  return humanize(type);
}

export function payoutStatusLabel(status?: string | null): string {
  switch (status) {
    case "paid":
      return "Paid";
    case "pending":
      return "Payout pending";
    case "failed":
      return "Payout failed";
    default:
      return "Not payable yet";
  }
}

export function payoutStatusTone(status?: string | null): StatusTone {
  switch (status) {
    case "paid":
      return "signal";
    case "failed":
      return "error";
    case "pending":
      return "amber";
    default:
      return "neutral";
  }
}

/**
 * Payment capture is a precondition of fulfillment, so a state at or beyond
 * FUNDED means the buyer's payment has been processed. The seller projection
 * does not expose a separate funding block; this map keeps the label honest.
 */
const PAYMENT_PROCESSED_STATES = new Set([
  "FUNDED",
  "FULFILLMENT_PENDING",
  "VERIFICATION_PENDING",
  "REMEDIATION_REQUIRED",
  "RELEASE_PERMITTED",
  "PAYOUT_PENDING",
  "RELEASED",
  "REVIEW_REQUIRED",
  "DISPUTE_OPEN",
  "REFUNDED",
]);

export function paymentStateLabel(state?: string | null): string {
  if (state === "REFUNDED") return "Refunded to buyer";
  if (PAYMENT_PROCESSED_STATES.has(state ?? "")) return "Payment processed";
  if (state === "FUNDING_PENDING") return "Payment pending";
  if (state === "CANCELED" || state === "FAILED") return "No payment";
  return "Awaiting payment";
}

export function paymentStateTone(state?: string | null): StatusTone {
  if (PAYMENT_PROCESSED_STATES.has(state ?? "")) return "signal";
  if (state === "FUNDING_PENDING") return "amber";
  if (state === "REFUNDED") return "neutral";
  return "neutral";
}

export function needsSellerAttention(state?: string | null): boolean {
  return (
    state === "FUNDED" ||
    state === "FULFILLMENT_PENDING" ||
    state === "VERIFICATION_PENDING" ||
    state === "REMEDIATION_REQUIRED" ||
    state === "REVIEW_REQUIRED" ||
    state === "DISPUTE_OPEN"
  );
}
