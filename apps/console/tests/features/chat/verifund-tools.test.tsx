import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  AgreementReviewCard,
  AgreementReviewLinkFromResult,
  FundingApprovalCard,
  ReceiptCard,
  bilateralReviewStatus,
  fundingDecision,
  releaseDecision,
  releaseGate,
  verifundStatusLabel,
  verifundToolsEnabled,
} from "@/features/chat/verifund-tools";

const HASH = "a".repeat(64);
const NOW = "2026-10-27T12:00:00.000Z";

const agreement = {
  agreement_version: 1,
  transaction_id: "vf_1",
  run_id: "run-1",
  buyer_id: "demo-buyer",
  seller_id: "northwind-audio",
  offer_id: "offer-1",
  currency: "USD",
  amount_cents: 123400,
  quantity: 12,
  line_items: [
    {
      sku: "NC-700",
      name: "Nimbus NC-700 ANC Headset",
      quantity: 12,
      unit_price_cents: 10000,
      warranty_addon_cents: 0,
    },
  ],
  shipping_cents: 3400,
  delivery_days: 7,
  warranty_months: 24,
  returns_days: 30,
  created_at: NOW,
  agreement_hash: HASH,
};

const accepted = {
  status: "accepted" as const,
  agreement_version: 1,
  agreement_hash: HASH,
};

function fundingArgs(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "run-1",
    transaction_id: "vf_1",
    agreement_version: 1,
    agreement_hash: HASH,
    agreement,
    buyer_review: accepted,
    seller_decision: accepted,
    message: "Approve funding for this agreement.",
    ...overrides,
  };
}

describe("verifund chat tools", () => {
  it("enables the tools only in settlement modes", () => {
    expect(verifundToolsEnabled("off")).toBe(false);
    expect(verifundToolsEnabled(undefined)).toBe(false);
    expect(verifundToolsEnabled("fake")).toBe(true);
    expect(verifundToolsEnabled("sandbox")).toBe(true);
  });

  it("requires both agents to accept the same version and hash", () => {
    expect(bilateralReviewStatus(fundingArgs())).toBe("ready");
    expect(
      bilateralReviewStatus(fundingArgs({ buyer_review: null })),
    ).toBe("buyer_pending");
    expect(
      bilateralReviewStatus(fundingArgs({ seller_decision: null })),
    ).toBe("seller_pending");
    expect(
      bilateralReviewStatus(
        fundingArgs({
          seller_decision: { ...accepted, agreement_hash: "b".repeat(64) },
        }),
      ),
    ).toBe("mismatch");
    expect(
      bilateralReviewStatus(
        fundingArgs({
          buyer_review: { ...accepted, agreement_version: 2 },
        }),
      ),
    ).toBe("mismatch");
  });

  it("labels every lifecycle checkpoint and terminal outcome", () => {
    expect(
      verifundStatusLabel("input_required", "buyer_review_required"),
    ).toMatch(/Buyer review/);
    expect(
      verifundStatusLabel("input_required", "seller_review_required"),
    ).toMatch(/Seller review/);
    expect(
      verifundStatusLabel("approval_required", "funding_approval_required"),
    ).toMatch(/funding approval/);
    expect(
      verifundStatusLabel("completed", "funding_pending"),
    ).toMatch(/funding settlement/);
    expect(
      verifundStatusLabel("input_required", "purchase_order_required"),
    ).toMatch(/purchase order/);
    expect(
      verifundStatusLabel("completed", "evidence_pending"),
    ).toMatch(/evidence/);
    expect(
      verifundStatusLabel("approval_required", "release_approval_required"),
    ).toMatch(/release approval/);
    expect(verifundStatusLabel("completed", null, "RELEASED")).toBe(
      "Transaction released.",
    );
    expect(
      verifundStatusLabel("completed", null, "REVIEW_REQUIRED"),
    ).toMatch(/manual review/);
    expect(verifundStatusLabel("completed", null, "CANCELED")).toMatch(
      /no funds moved/,
    );
  });

  it("builds a decision with the original identifiers and idempotency key", () => {
    const decision = fundingDecision(fundingArgs(), {
      approved: true,
      approvedBy: "Demo Buyer",
      note: "ok",
      decidedAt: NOW,
    });
    expect(decision).toMatchObject({
      run_id: "run-1",
      transaction_id: "vf_1",
      agreement_version: 1,
      agreement_hash: HASH,
      approved: true,
      approved_by: "Demo Buyer",
      note: "ok",
      decided_at: NOW,
    });
    expect(decision.idempotency_key).toBe(
      `fund:run-1:vf_1:1:${HASH}`,
    );
    expect(() =>
      fundingDecision(fundingArgs({ seller_decision: null }), {
        approved: true,
        decidedAt: NOW,
      }),
    ).toThrow(/Buyer and Seller/);
  });

  it("gates release on verification and requires a note for an override", () => {
    expect(releaseGate(null).enabled).toBe(false);
    expect(
      releaseGate({ state: "FUNDED" } as never).enabled,
    ).toBe(false);
    expect(
      releaseGate({
        state: "REVIEW_REQUIRED",
        verification: { override_allowed: false },
      } as never).enabled,
    ).toBe(false);
    const overrideGate = releaseGate({
      state: "REVIEW_REQUIRED",
      verification: { override_allowed: true },
    } as never);
    expect(overrideGate).toEqual({
      enabled: true,
      overrideAllowed: true,
      reason: null,
    });
    const args = {
      run_id: "run-1",
      transaction_id: "vf_1",
      agreement_version: 1,
      agreement_hash: HASH,
      projection: {
        state: "REVIEW_REQUIRED",
        transaction_id: "vf_1",
        agreement_hash: HASH,
        verification: { override_allowed: true },
      },
      message: "Release this transaction.",
    };
    expect(() =>
      releaseDecision(args as never, {
        approved: true,
        override: true,
        note: " ",
        decidedAt: NOW,
      }),
    ).toThrow(/requires a note/);
    expect(
      releaseDecision(args as never, {
        approved: true,
        override: true,
        note: "Manual inspection complete.",
        decidedAt: NOW,
        releasedBy: "Demo Buyer",
      }),
    ).toMatchObject({
      approved: true,
      override: true,
      released_by: "Demo Buyer",
      idempotency_key: `release:run-1:vf_1:1:${HASH}`,
    });
  });

  it("renders the agreement and the bilateral status", () => {
    render(
      <AgreementReviewCard
        agreement={agreement}
        buyerReview={accepted}
        sellerDecision={accepted}
      />,
    );
    expect(screen.getByTestId("verifund-agreement")).toBeInTheDocument();
    expect(screen.getByText("northwind-audio")).toBeInTheDocument();
    expect(screen.getByText("Buyer accepted")).toBeInTheDocument();
    expect(screen.getByText("Seller accepted")).toBeInTheDocument();
    expect(screen.getByText("$1,234.00")).toBeInTheDocument();
  });

  it("renders the review link from a buyer-approval tool result", () => {
    const reviewUrl =
      "/agreements/agr_1?task_id=vf-task-1&context_id=vf-context-1&run_id=run-1";
    render(
      <AgreementReviewLinkFromResult
        result={{
          status: "input_required",
          checkpoint: "buyer_approval_required",
          agreement_review: {
            review_url: reviewUrl,
            version: 1,
            digest: HASH,
            seller_decision: accepted,
            precheck: { recommendation: "accept" },
          },
          data: { agreement },
        }}
      />,
    );

    expect(screen.getByTestId("agreement-approval-card")).toBeInTheDocument();
    expect(screen.getByTestId("review-link")).toHaveAttribute(
      "href",
      reviewUrl,
    );
    expect(screen.getByText("Version 1")).toBeInTheDocument();
    expect(screen.getByText("Precheck: accept")).toBeInTheDocument();
  });

  it("does not turn a funding checkpoint into an agreement review link", () => {
    render(
      <AgreementReviewLinkFromResult
        result={{
          status: "approval_required",
          checkpoint: "funding_approval_required",
          hitl: { tool: "request_verifund_funding_approval", args: {} },
          data: { agreement },
        }}
      />,
    );

    expect(screen.queryByTestId("agreement-approval-card")).toBeNull();
  });

  it("blocks funding until both reviews are accepted", () => {
    const onApprove = vi.fn();
    const { rerender } = render(
      <FundingApprovalCard
        args={fundingArgs({ seller_decision: null })}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: "Approve funding" }),
    ).toBeDisabled();
    expect(screen.getByTestId("verifund-funding-blocked")).toBeInTheDocument();

    rerender(
      <FundingApprovalCard
        args={fundingArgs()}
        onApprove={onApprove}
        onReject={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Approve funding" }),
    );
    expect(onApprove).toHaveBeenCalledWith("");
  });

  it("renders receipt verification and refuses a malformed receipt", () => {
    render(
      <ReceiptCard
        receipt={{
          payload: {
            receipt_version: 1,
            transaction_id: "vf_1",
            agreement_hash: HASH,
            amount_cents: 123400,
            currency: "USD",
            buyer_id: "demo-buyer",
            seller_id: "northwind-audio",
            capture_id: "cap_1",
            payout_item_id: "pay_1",
            evidence_hashes: [HASH],
            released_at: NOW,
          },
          payload_hash: HASH,
          signature: "sig",
          kid: "dev-1",
          verified: true,
        }}
      />,
    );
    expect(screen.getByText("Verified receipt")).toBeInTheDocument();
    expect(screen.getByText(/dev-1/)).toBeInTheDocument();
  });
});
