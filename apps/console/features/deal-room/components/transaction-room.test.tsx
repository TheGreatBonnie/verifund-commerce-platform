import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type {
  SettlementProjection,
  SettlementReceipt,
} from "@/lib/types";
import { TransactionRoom } from "./transaction-room";

const HASH = "a".repeat(64);

function projection(
  overrides: Partial<SettlementProjection> = {},
): SettlementProjection {
  return {
    transaction_id: "vf_1",
    run_id: "run-1",
    state: "FUNDING_PENDING",
    last_seq: 5,
    amount_cents: 123400,
    currency: "USD",
    buyer_id: "demo-buyer",
    seller_id: "northwind-audio",
    agreement_hash: HASH,
    agreement_version: 1,
    seller_decision: null,
    approval: null,
    cancellation: null,
    funding: { status: "created" },
    purchase_order: null,
    evidence: null,
    verification: null,
    payout: null,
    receipt_available: false,
    deadlines: { evidence: null, inspection: null },
    allowed_actions: [],
    updated_at: "2026-10-27T12:00:00Z",
    ...overrides,
  };
}

function receipt(): SettlementReceipt {
  return {
    payload: {
      receipt_version: 1,
      transaction_id: "vf_1",
      agreement_hash: HASH,
      amount_cents: 123400,
      currency: "USD",
      buyer_id: "demo-buyer",
      seller_id: "northwind-audio",
      capture_id: "CAP-1",
      payout_item_id: "PAY-1",
      evidence_hashes: ["b".repeat(64)],
      released_at: "2026-10-27T12:00:00Z",
    },
    payload_hash: "c".repeat(64),
    signature: "sig-value",
    kid: "receipt-2026-10",
    verified: true,
  };
}

function noop() {}

describe("TransactionRoom", () => {
  it("shows the funding checkpoint and PayPal checkout link", () => {
    render(
      <TransactionRoom
        settlement={projection({
          funding: {
            status: "created",
            payer_action_url:
              "https://www.sandbox.paypal.com/checkoutnow?token=1",
          },
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Funding" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /open paypal checkout/i }),
    ).toHaveAttribute(
      "href",
      "https://www.sandbox.paypal.com/checkoutnow?token=1",
    );
  });

  it("lists evidence and verification blockers", () => {
    render(
      <TransactionRoom
        settlement={projection({
          state: "REVIEW_REQUIRED",
          evidence: {
            required: ["shipment_manifest", "delivery_confirmation"],
            received: ["shipment_manifest"],
            complete: false,
            deadline: "2026-10-28T12:00:00Z",
            items: [
              {
                evidence_id: "ev_1",
                kind: "shipment_manifest",
                sha256: "b".repeat(64),
                media_type: "application/json",
                size_bytes: 128,
                original_filename: "manifest.json",
                note: "auto",
                created_at: "2026-10-27T10:00:00Z",
              },
            ],
          },
          verification: {
            status: "failed",
            reasons: ["tracking_mismatch"],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: true,
          },
          allowed_actions: ["flag_review", "retry_payout", "cancel"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(screen.getByText("shipment_manifest")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "manifest.json" }),
    ).toHaveAttribute("href", "/evidence/ev_1");
    expect(screen.getByText(/tracking mismatch/i)).toBeInTheDocument();
    expect(screen.getByText(/1 of 2 evidence items/i)).toBeInTheDocument();
  });

  it("sends an audited release with the reviewer note", () => {
    const onRelease = vi.fn();
    render(
      <TransactionRoom
        settlement={projection({
          state: "RELEASE_PERMITTED",
          verification: {
            status: "passed",
            reasons: [],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: false,
          },
          allowed_actions: ["release"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={onRelease}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    fireEvent.change(screen.getByLabelText("Release note"), {
      target: { value: "documents verified" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Release funds" }));

    expect(onRelease).toHaveBeenCalledWith({
      released_by: "demo-reviewer",
      note: "documents verified",
      override: false,
    });
  });

  it("keeps non-overridable review reasons out of the release action", () => {
    render(
      <TransactionRoom
        settlement={projection({
          state: "REVIEW_REQUIRED",
          verification: {
            status: "failed",
            reasons: ["funding_mismatch"],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: true,
          },
          allowed_actions: ["flag_review", "retry_payout"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(
      screen.queryByRole("button", { name: "Release funds" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/resolve this in paypal/i),
    ).toBeInTheDocument();
  });

  it("retries a payout from review", () => {
    const onReview = vi.fn();
    render(
      <TransactionRoom
        settlement={projection({
          state: "REVIEW_REQUIRED",
          verification: {
            status: "failed",
            reasons: ["manual_flag"],
            checked_at: "2026-10-27T12:00:00Z",
            override_allowed: true,
          },
          allowed_actions: ["flag_review", "retry_payout", "cancel"],
        })}
        receipt={null}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={onReview}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Retry payout" }));

    expect(onReview).toHaveBeenCalledWith({
      action: "retry_payout",
      note: "",
    });
  });

  it("shows the signed receipt after release", () => {
    render(
      <TransactionRoom
        settlement={projection({
          state: "RELEASED",
          receipt_available: true,
          allowed_actions: [],
        })}
        receipt={receipt()}
        busy={false}
        error={null}
        onAdvance={noop}
        onRelease={noop}
        onReview={noop}
        onCancel={noop}
        onRefreshReceipt={noop}
        evidenceUrl={(id) => `/evidence/${id}`}
      />,
    );

    expect(
      screen.getByRole("heading", { name: "Settlement receipt" }),
    ).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
    expect(screen.getByText("receipt-2026-10")).toBeInTheDocument();
  });
});
