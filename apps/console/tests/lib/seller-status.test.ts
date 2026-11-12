import { describe, expect, it } from "vitest";
import {
  REQUIREMENT_STATUS_LABELS,
  evidencePercent,
  isTerminalTransaction,
  nextActionLabel,
  paymentStateLabel,
  requirementStatusLabel,
  transactionStateLabel,
} from "@/lib/seller-status";

describe("seller status vocabulary", () => {
  it("labels transaction states without raw enums", () => {
    expect(transactionStateLabel("FULFILLMENT_PENDING")).toBe("Evidence required");
    expect(transactionStateLabel("VERIFICATION_PENDING")).toBe("In progress");
    expect(transactionStateLabel("FUNDED")).toBe("Fulfillment required");
    expect(transactionStateLabel("RELEASE_PERMITTED")).toBe("Fulfillment verified");
  });

  it("covers remediation, dispute, and refund states", () => {
    expect(transactionStateLabel("REMEDIATION_REQUIRED")).toBe("Action required");
    expect(transactionStateLabel("DISPUTE_OPEN")).toBe("Dispute open");
    expect(transactionStateLabel("REFUNDED")).toBe("Refunded");
    expect(isTerminalTransaction("REFUNDED")).toBe(true);
  });

  it("labels requirement statuses with no rejected badge", () => {
    expect(requirementStatusLabel("not_submitted")).toBe("Required");
    expect(requirementStatusLabel("pending_scan")).toBe("Processing");
    expect(requirementStatusLabel("review")).toBe("Under review");
    expect(requirementStatusLabel("pass")).toBe("Verified");
    expect(requirementStatusLabel("fail")).toBe("Action required");
    // No explicit REJECTED badge exists; unknown statuses fall through to the
    // generic humanized label rather than a dedicated rejected state.
    expect(REQUIREMENT_STATUS_LABELS["rejected"]).toBeUndefined();
  });

  it("labels next actions and payment states", () => {
    expect(nextActionLabel("submit_evidence")).toBe("Submit evidence");
    expect(nextActionLabel("replace_evidence")).toBe("Replace evidence");
    expect(nextActionLabel("respond_to_dispute")).toBe("Respond to dispute");
    expect(paymentStateLabel("FUNDED")).toBe("Payment processed");
    expect(paymentStateLabel("FUNDING_PENDING")).toBe("Payment pending");
  });

  it("computes submission progress honestly", () => {
    expect(evidencePercent({ submitted: 1, required: 2, complete: false, received_kinds: [] })).toBe(50);
    expect(evidencePercent(null)).toBe(0);
    expect(evidencePercent({ submitted: 0, required: 0, complete: false, received_kinds: [] })).toBe(0);
  });
});
