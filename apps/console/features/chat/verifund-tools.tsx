"use client";

import { useState } from "react";
import { z } from "zod";
import type { SettlementProjection, SettlementReceipt } from "@/lib/types";

export const reviewDecisionSchema = z.object({
  status: z.enum(["accepted", "rejected"]),
  agreement_version: z.number().int().positive(),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
});

export const agreementSchema = z.object({
  agreement_version: z.number().int().positive(),
  transaction_id: z.string().min(1),
  run_id: z.string().min(1),
  buyer_id: z.string().min(1),
  seller_id: z.string().min(1),
  offer_id: z.string().min(1),
  currency: z.string().min(1),
  amount_cents: z.number().int().positive(),
  quantity: z.number().int().positive(),
  line_items: z.array(
    z.object({
      sku: z.string(),
      name: z.string(),
      quantity: z.number().int().positive(),
      unit_price_cents: z.number().int().positive(),
      warranty_addon_cents: z.number().int().nonnegative().default(0),
    }),
  ),
  shipping_cents: z.number().int().nonnegative(),
  delivery_days: z.number().int().nonnegative(),
  warranty_months: z.number().int().nonnegative(),
  returns_days: z.number().int().nonnegative(),
  created_at: z.string().min(1),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
});

export const fundingApprovalArgsSchema = z.object({
  run_id: z.string().min(1),
  transaction_id: z.string().min(1),
  agreement_version: z.number().int().positive(),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
  agreement: agreementSchema,
  buyer_review: reviewDecisionSchema.nullable(),
  seller_decision: reviewDecisionSchema.nullable(),
  message: z.string().default("Approve funding for this agreement."),
});

export const releaseApprovalArgsSchema = z.object({
  run_id: z.string().min(1),
  transaction_id: z.string().min(1),
  agreement_version: z.number().int().positive(),
  agreement_hash: z.string().regex(/^[0-9a-f]{64}$/),
  projection: z.record(z.unknown()).nullable(),
  message: z.string().default("Release this transaction."),
});

export type VerifundAgreement = z.infer<typeof agreementSchema>;
export type ReviewDecision = z.infer<typeof reviewDecisionSchema>;
export type FundingApprovalArgs = z.infer<typeof fundingApprovalArgsSchema>;
export type ReleaseApprovalArgs = z.infer<typeof releaseApprovalArgsSchema>;

export type FundingDecision = {
  run_id: string;
  transaction_id: string;
  agreement_version: number;
  agreement_hash: string;
  approved: boolean;
  approved_by: string;
  note: string;
  decided_at: string;
  idempotency_key: string;
};

export type ReleaseDecision = {
  run_id: string;
  transaction_id: string;
  agreement_version: number;
  agreement_hash: string;
  approved: boolean;
  released_by: string;
  note: string;
  override: boolean;
  decided_at: string;
  idempotency_key: string;
};

export function verifundToolsEnabled(mode: string | undefined): boolean {
  return mode === "fake" || mode === "sandbox";
}

const CHECKPOINT_COPY: Record<string, string> = {
  buyer_review_required: "Waiting for Buyer review.",
  seller_review_required: "Waiting for Seller review.",
  funding_approval_required: "Waiting for human funding approval.",
  funding_pending: "Waiting for the funding settlement.",
  purchase_order_required: "Placing the purchase order.",
  evidence_pending: "Waiting for evidence.",
  release_approval_required: "Waiting for human release approval.",
};

export function verifundStatusLabel(
  status: string | undefined,
  checkpoint: string | null | undefined,
  state?: string | null,
): string {
  if (checkpoint && CHECKPOINT_COPY[checkpoint]) {
    return CHECKPOINT_COPY[checkpoint];
  }
  if (status === "completed") {
    if (state === "RELEASED") return "Transaction released.";
    if (state === "REVIEW_REQUIRED") {
      return "Release rejected; the transaction is paused for manual review.";
    }
    if (state === "CANCELED") {
      return "Agreement rejected; no funds moved.";
    }
    if (state === "PAYOUT_PENDING") {
      return "Released; waiting for the payout receipt.";
    }
    return "Lifecycle complete.";
  }
  if (status === "failed") {
    return "Verifund failed; no funds moved.";
  }
  return status ? status.replaceAll("_", " ") : "Unknown Verifund state.";
}

export function parseVerifundToolResult(
  result: unknown,
): Record<string, any> | null {
  if (result && typeof result === "object") {
    return result as Record<string, any>;
  }
  if (typeof result !== "string") return null;
  const content = result.startsWith("A2A Agent Response: ")
    ? result.slice("A2A Agent Response: ".length)
    : result;
  try {
    const parsed = JSON.parse(content);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, any>)
      : null;
  } catch {
    return null;
  }
}

export function bilateralReviewStatus(
  args: Pick<
    FundingApprovalArgs,
    "agreement" | "buyer_review" | "seller_decision"
  >,
): "ready" | "buyer_pending" | "seller_pending" | "mismatch" {
  const { agreement, buyer_review, seller_decision } = args;
  if (!buyer_review || buyer_review.status !== "accepted") {
    return "buyer_pending";
  }
  if (!seller_decision || seller_decision.status !== "accepted") {
    return "seller_pending";
  }
  const bound = (review: ReviewDecision) =>
    review.agreement_version === agreement.agreement_version &&
    review.agreement_hash === agreement.agreement_hash;
  if (!bound(buyer_review) || !bound(seller_decision)) return "mismatch";
  return "ready";
}

export function fundingDecision(
  args: FundingApprovalArgs,
  choice: {
    approved: boolean;
    approvedBy?: string;
    note?: string;
    decidedAt?: string;
  },
): FundingDecision {
  if (
    args.agreement.run_id !== args.run_id ||
    args.agreement.transaction_id !== args.transaction_id ||
    args.agreement.agreement_version !== args.agreement_version ||
    args.agreement.agreement_hash !== args.agreement_hash
  ) {
    throw new Error("The agreement is bound to another run or version.");
  }
  if (bilateralReviewStatus(args) !== "ready") {
    throw new Error(
      "Buyer and Seller must accept the same agreement before funding.",
    );
  }
  return {
    run_id: args.run_id,
    transaction_id: args.transaction_id,
    agreement_version: args.agreement_version,
    agreement_hash: args.agreement_hash,
    approved: choice.approved,
    approved_by: choice.approvedBy ?? "Demo Buyer",
    note: choice.note ?? "",
    decided_at: choice.decidedAt ?? new Date().toISOString(),
    idempotency_key: `fund:${args.run_id}:${args.transaction_id}:${args.agreement_version}:${args.agreement_hash}`,
  };
}

export type ReleaseGate = {
  enabled: boolean;
  overrideAllowed: boolean;
  reason: string | null;
};

export function releaseGate(
  projection: Partial<SettlementProjection> | null,
): ReleaseGate {
  if (!projection) {
    return {
      enabled: false,
      overrideAllowed: false,
      reason: "Waiting for the transaction projection.",
    };
  }
  if (
    projection.state !== "RELEASE_PERMITTED" &&
    projection.state !== "REVIEW_REQUIRED"
  ) {
    return {
      enabled: false,
      overrideAllowed: false,
      reason: `Release is not permitted while the transaction is ${projection.state}.`,
    };
  }
  const overrideAllowed =
    projection.state === "REVIEW_REQUIRED" &&
    Boolean(projection.verification?.override_allowed);
  if (projection.state === "REVIEW_REQUIRED" && !overrideAllowed) {
    return {
      enabled: false,
      overrideAllowed: false,
      reason: "This verification failure cannot be overridden.",
    };
  }
  return { enabled: true, overrideAllowed, reason: null };
}

export function releaseDecision(
  args: ReleaseApprovalArgs,
  choice: {
    approved: boolean;
    releasedBy?: string;
    note?: string;
    override?: boolean;
    decidedAt?: string;
  },
): ReleaseDecision {
  const projection = (args.projection ?? {}) as Partial<SettlementProjection>;
  const gate = releaseGate(projection);
  if (!gate.enabled) {
    throw new Error(gate.reason ?? "Release is not permitted.");
  }
  if (projection.transaction_id && projection.transaction_id !== args.transaction_id) {
    throw new Error("The projection transaction does not match.");
  }
  if (projection.agreement_hash && projection.agreement_hash !== args.agreement_hash) {
    throw new Error("The projection agreement hash is stale.");
  }
  const override = Boolean(choice.override);
  if (override && !gate.overrideAllowed) {
    throw new Error("Override is not allowed for this verification result.");
  }
  const note = choice.note ?? "";
  if (override && !note.trim()) {
    throw new Error("An override release requires a note.");
  }
  return {
    run_id: args.run_id,
    transaction_id: args.transaction_id,
    agreement_version: args.agreement_version,
    agreement_hash: args.agreement_hash,
    approved: choice.approved,
    released_by: choice.releasedBy ?? "Demo Buyer",
    note,
    override,
    decided_at: choice.decidedAt ?? new Date().toISOString(),
    idempotency_key: `release:${args.run_id}:${args.transaction_id}:${args.agreement_version}:${args.agreement_hash}`,
  };
}

function money(cents: number, currency: string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(cents / 100);
}

function reviewLabel(prefix: string, review: ReviewDecision | null) {
  if (!review) return `${prefix} review pending`;
  if (review.status === "rejected") return `${prefix} rejected`;
  return `${prefix} accepted`;
}

export function AgreementReviewCard({
  agreement,
  buyerReview,
  sellerDecision,
}: {
  agreement: VerifundAgreement;
  buyerReview: ReviewDecision | null;
  sellerDecision: ReviewDecision | null;
}) {
  return (
    <section
      className="mm-chat-approval"
      data-testid="verifund-agreement"
      aria-labelledby="verifund-agreement-title"
    >
      <p className="mm-kicker">Verifund · canonical agreement</p>
      <h3 id="verifund-agreement-title">
        <span>{agreement.seller_id}</span> ·{" "}
        <span>{money(agreement.amount_cents, agreement.currency)}</span>
      </h3>
      <dl>
        <dt>Transaction</dt>
        <dd>{agreement.transaction_id}</dd>
        <dt>Version</dt>
        <dd>{agreement.agreement_version}</dd>
        <dt>Hash</dt>
        <dd className="mm-mono-note">{agreement.agreement_hash}</dd>
        <dt>Buyer</dt>
        <dd>{reviewLabel("Buyer", buyerReview)}</dd>
        <dt>Seller</dt>
        <dd>{reviewLabel("Seller", sellerDecision)}</dd>
      </dl>
      <ul>
        {agreement.line_items.map((item) => (
          <li key={`${item.sku}-${item.unit_price_cents}`}>
            {item.quantity} × {item.name} ·{" "}
            {money(item.unit_price_cents, agreement.currency)}
          </li>
        ))}
      </ul>
      <p>
        Delivery in {agreement.delivery_days} days · {agreement.warranty_months}
        -month warranty · {agreement.returns_days}-day returns
      </p>
    </section>
  );
}

export function FundingApprovalCard({
  args,
  onApprove,
  onReject,
}: {
  args: FundingApprovalArgs;
  onApprove: (note: string) => void;
  onReject: (note: string) => void;
}) {
  const [note, setNote] = useState("");
  const readiness = bilateralReviewStatus(args);
  const ready = readiness === "ready";
  return (
    <section
      className="mm-chat-approval"
      data-testid="verifund-funding"
      aria-labelledby="verifund-funding-title"
    >
      <p className="mm-kicker">Verifund · human funding approval</p>
      <h3 id="verifund-funding-title">{args.message}</h3>
      <AgreementReviewCard
        agreement={args.agreement}
        buyerReview={args.buyer_review}
        sellerDecision={args.seller_decision}
      />
      {!ready ? (
        <p role="alert" data-testid="verifund-funding-blocked">
          {readiness === "mismatch"
            ? "The recorded reviews are bound to different terms. Funding is blocked."
            : `Waiting for the ${
                readiness === "buyer_pending" ? "Buyer" : "Seller"
              } decision before funding.`}
        </p>
      ) : null}
      <label>
        Note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <div>
        <button
          type="button"
          disabled={!ready}
          onClick={() => onApprove(note)}
        >
          Approve funding
        </button>
        <button type="button" disabled={!ready} onClick={() => onReject(note)}>
          Reject funding
        </button>
      </div>
    </section>
  );
}

export function ReleaseApprovalCard({
  args,
  onDecision,
}: {
  args: ReleaseApprovalArgs;
  onDecision: (decision: ReleaseDecision) => void;
}) {
  const [note, setNote] = useState("");
  const [override, setOverride] = useState(false);
  const gate = releaseGate(
    (args.projection ?? null) as Partial<SettlementProjection> | null,
  );
  const blocked = !gate.enabled || (override && !note.trim());
  return (
    <section
      className="mm-chat-approval"
      data-testid="verifund-release"
      aria-labelledby="verifund-release-title"
    >
      <p className="mm-kicker">Verifund · human release approval</p>
      <h3 id="verifund-release-title">{args.message}</h3>
      {!gate.enabled ? <p role="alert">{gate.reason}</p> : null}
      <label>
        Note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      {gate.overrideAllowed ? (
        <label>
          <input
            type="checkbox"
            checked={override}
            onChange={(event) => setOverride(event.target.checked)}
          />
          Override the verification failure
        </label>
      ) : null}
      <div>
        <button
          type="button"
          disabled={blocked}
          onClick={() =>
            onDecision(
              releaseDecision(args, {
                approved: true,
                override,
                note,
              }),
            )
          }
        >
          Release funds
        </button>
        <button
          type="button"
          disabled={!gate.enabled}
          onClick={() =>
            onDecision(
              releaseDecision(args, {
                approved: false,
                override: false,
                note,
              }),
            )
          }
        >
          Reject release
        </button>
      </div>
    </section>
  );
}

export function EvidenceSummaryCard({
  projection,
}: {
  projection: Partial<SettlementProjection> | null;
}) {
  if (!projection) return null;
  const evidence = projection.evidence;
  return (
    <section className="mm-chat-approval" data-testid="verifund-evidence">
      <p className="mm-kicker">Verifund · evidence review</p>
      <p>
        {evidence
          ? `${evidence.received.length}/${evidence.required.length} required evidence items received`
          : "No evidence has been reported."}
      </p>
      {projection.verification ? (
        <p>
          Verification: {projection.verification.status}
          {projection.verification.reasons.length
            ? ` · ${projection.verification.reasons.join(", ")}`
            : ""}
        </p>
      ) : null}
    </section>
  );
}

export function ReceiptCard({ receipt }: { receipt: SettlementReceipt }) {
  return (
    <section className="mm-chat-approval" data-testid="verifund-receipt">
      <p className="mm-kicker">Verifund · signed receipt</p>
      <h3>{receipt.verified ? "Verified receipt" : "Receipt not verified"}</h3>
      <p>
        {receipt.payload.transaction_id} ·{" "}
        {money(receipt.payload.amount_cents, receipt.payload.currency)}
      </p>
      <p className="mm-mono-note">
        {receipt.kid} · {receipt.payload_hash}
      </p>
    </section>
  );
}

export function CheckoutCard({
  url,
  expiresAt,
}: {
  url: string;
  expiresAt?: string | null;
}) {
  return (
    <section className="mm-chat-approval" data-testid="verifund-checkout">
      <p className="mm-kicker">Verifund · funding handoff</p>
      <a href={url} target="_blank" rel="noreferrer">
        Open the payment checkout
      </a>
      {expiresAt ? <p>Link expires at {expiresAt}</p> : null}
    </section>
  );
}

export function VerifundStatusCard({
  status,
  checkpoint,
  state,
  message,
}: {
  status?: string;
  checkpoint?: string | null;
  state?: string | null;
  message?: string;
}) {
  return (
    <p className="mm-chat-approval-result" data-testid="verifund-status">
      {message || verifundStatusLabel(status, checkpoint, state)}
    </p>
  );
}
