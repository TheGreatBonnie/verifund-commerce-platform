"use client";

import { useState } from "react";
import {
  BadgeCheck,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileCheck2,
  Info,
  LockKeyhole,
  ShieldCheck,
  Truck,
} from "lucide-react";
import {
  PayPalOneTimePaymentButton,
  PayPalProvider,
} from "@paypal/react-paypal-js/sdk-v6";
import { z } from "zod";
import {
  captureOrderAction,
  createOrderAction,
  pollFundingAction,
} from "@/app/actions";
import { AgreementApprovalCard } from "@/features/agreements/AgreementApprovalCard";
import type { SettlementProjection, SettlementReceipt } from "@/lib/types";
import { evidenceCounts } from "@/lib/format";
export { evidenceCounts };
import {
  approveAgreement,
  rejectAgreement,
  requestChangesAgreement,
  type ResumeHandle,
} from "@/app/(console)/agreements/[id]/actions";

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
      attributes: z.record(z.string()).default({}),
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

export const paypalCheckoutArgsSchema = z.object({
  transaction_id: z.string().min(1),
  amount_cents: z.number().int().positive(),
  currency: z.string().min(1),
  expires_at: z.string().optional(),
  agreement: z.record(z.unknown()),
  message: z
    .string()
    .default("Complete the PayPal checkout to fund this transaction."),
});

export const agreementApprovalArgsSchema = z.object({
  agreement: z.record(z.unknown()),
  agreement_id: z.string().min(1).optional(),
  review_url: z.string().optional(),
  version: z.number().int().positive().optional(),
  digest: z.string().optional(),
  seller_decision: z.record(z.unknown()).nullable().optional(),
  precheck: z.record(z.unknown()).nullable().optional(),
  handle: z
    .object({
      task_id: z.string(),
      context_id: z.string(),
      run_id: z.string(),
    })
    .optional(),
});

export type VerifundAgreement = z.infer<typeof agreementSchema>;
export type ReviewDecision = z.infer<typeof reviewDecisionSchema>;
export type FundingApprovalArgs = z.infer<typeof fundingApprovalArgsSchema>;
export type ReleaseApprovalArgs = z.infer<typeof releaseApprovalArgsSchema>;
export type AgreementApprovalArgs = z.infer<typeof agreementApprovalArgsSchema>;
export type PayPalCheckoutArgs = z.infer<typeof paypalCheckoutArgsSchema>;

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
  buyer_approval_required: "Waiting for Buyer approval.",
  seller_operator_required: "Waiting for Seller operator review.",
  agreement_changes_requested: "Agreement changes requested.",
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

export type AgreementReviewLink = {
  agreement?: Record<string, any>;
  reviewUrl?: string;
  version?: number;
  digest?: string;
  sellerDecision?: Record<string, any> | null;
  precheck?: Record<string, any> | null;
};

/**
 * Extract the non-blocking agreement review card from a tool result.
 *
 * `verifund_create_agreement` returns `agreement_review` while the lifecycle
 * waits for the buyer. A funding checkpoint never renders this card, even
 * though it also carries the canonical agreement.
 */
export function agreementReviewLink(
  parsed: Record<string, any> | null,
): AgreementReviewLink | null {
  if (!parsed || parsed.hitl) return null;
  const review = parsed.agreement_review ?? parsed.data?.agreement_review;
  const agreement = parsed.agreement ?? parsed.data?.agreement;
  if (review) {
    return {
      agreement,
      reviewUrl: review.review_url,
      version: review.version,
      digest: review.digest,
      sellerDecision: review.seller_decision,
      precheck: review.precheck,
    };
  }
  const checkpoint = parsed.checkpoint ?? parsed.data?.checkpoint;
  if (checkpoint && checkpoint !== "buyer_approval_required") return null;
  const reviewUrl = parsed.review_url ?? parsed.data?.review_url;
  if (!reviewUrl && !agreement) return null;
  return {
    agreement,
    reviewUrl,
    version: parsed.version ?? parsed.data?.version,
    digest: parsed.digest ?? parsed.data?.digest,
    sellerDecision:
      parsed.seller_decision ?? parsed.data?.seller_decision,
    precheck: parsed.precheck ?? parsed.data?.precheck,
  };
}

export function AgreementReviewLinkFromResult({ result }: { result: unknown }) {
  const link = agreementReviewLink(parseVerifundToolResult(result));
  if (!link) return null;
  return <AgreementApprovalCard {...link} />;
}

export function bilateralReviewStatus(
  args: Pick<
    FundingApprovalArgs,
    "agreement" | "buyer_review" | "seller_decision" | "agreement_version" | "agreement_hash"
  >,
): "ready" | "buyer_pending" | "seller_pending" | "mismatch" {
  const { agreement, buyer_review, seller_decision } = args;
  if (!buyer_review || buyer_review.status !== "accepted") {
    return "buyer_pending";
  }
  if (!seller_decision || seller_decision.status !== "accepted") {
    return "seller_pending";
  }
  // The HITL args carry the binding at the top level (agreement_version /
  // agreement_hash) as well as nested inside `agreement`. The orchestrator's
  // LLM relay can drop the nested copy (same class as the earlier
  // agreement_id drop), so the top level is authoritative when present.
  const expectedVersion =
    args.agreement_version ?? agreement.agreement_version;
  const expectedHash = args.agreement_hash ?? agreement.agreement_hash;
  const bound = (review: ReviewDecision) =>
    review.agreement_version === expectedVersion &&
    review.agreement_hash === expectedHash;
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
    (args.agreement.agreement_version != null &&
      args.agreement.agreement_version !== args.agreement_version) ||
    (args.agreement.agreement_hash != null &&
      args.agreement.agreement_hash !== args.agreement_hash)
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

const EVIDENCE_LABELS: Record<string, string> = {
  shipment_manifest: "Shipment manifest",
  delivery_confirmation: "Delivery confirmation",
  invoice: "Invoice",
  other: "Other evidence",
};

const REMEDY_LABELS: Record<string, string> = {
  cancel_and_refund: "Cancel and full refund",
  refund_or_replacement: "Refund or replacement",
};

function labelFor(map: Record<string, string>, value: unknown) {
  const key = String(value ?? "");
  return map[key] ?? key.replaceAll("_", " ");
}

function hexColor(value: unknown): string | null {
  return typeof value === "string" &&
    /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value)
    ? value
    : null;
}

function agreementTerms(agreement: any): Record<string, any> {
  const terms = agreement?.terms;
  return terms && typeof terms === "object" ? terms : {};
}

function agreementItems(agreement: any): any[] {
  const items = agreementTerms(agreement).items ?? agreement?.line_items ?? [];
  return Array.isArray(items) ? items : [];
}

function formatStamp(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(date);
}

function ProductSummary({ agreement }: { agreement: any }) {
  const items = agreementItems(agreement);
  const item = items[0] ?? {};
  const attrs = (item.attributes ?? {}) as Record<string, any>;
  const terms = agreementTerms(agreement);
  const sellerName =
    terms?.parties?.seller?.display_name ??
    agreement?.seller_id ??
    "Seller";
  const name = item.name ?? "Agreement item";
  const quantity = item.quantity ?? agreement?.quantity ?? 1;
  const warranty = agreement?.warranty_months ?? terms.warranty_months;
  const returns = agreement?.returns_days ?? terms.returns_days;
  const inspectionHours =
    agreement?.inspection_period_hours ?? terms?.inspection?.period_hours;
  const specs = String(attrs.specs ?? "")
    .split("·")
    .map((part) => part.trim())
    .filter(Boolean);
  const chips = [
    attrs.condition,
    ...specs,
    warranty ? `${warranty}-month warranty` : null,
    returns ? `${returns}-day returns` : null,
    inspectionHours ? `${inspectionHours}-hour inspection` : null,
  ].filter((chip): chip is string => Boolean(chip));
  const visible = chips.slice(0, 4);
  const overflow = chips.length - visible.length;


  return (
    <div className="mm-product" data-testid="product-summary">
      <div className="mm-product-tile">
        {attrs.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={String(attrs.image_url)} alt={String(name)} />
        ) : null}
      </div>
      <div className="mm-product-body">
        <h4 className="mm-product-name">
          {String(name)}
          {items.length > 1 ? ` (+${items.length - 1} more)` : ""}
        </h4>
        <p className="mm-product-seller">
          {String(sellerName)}
          <BadgeCheck size={12} aria-label="Verified seller" />
        </p>
        <ul className="mm-product-chips">
          {visible.map((chip, index) => (
            <li key={`${chip}-${index}`}>{chip}</li>
          ))}
          {overflow > 0 ? <li>+{overflow} more</li> : null}
        </ul>
        <p className="mm-product-qty">
          Quantity <strong>{String(quantity)}</strong>
        </p>
      </div>
    </div>
  );
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
      className="mm-approval"
      data-testid="verifund-agreement"
      aria-labelledby="verifund-agreement-title"
    >
      <div className="mm-verifund-head">
        <div>
          <p className="mm-kicker">Verifund · canonical agreement</p>
          <h3 id="verifund-agreement-title">
            <span>{agreement.seller_id}</span> ·{" "}
            <span>{money(agreement.amount_cents, agreement.currency)}</span>
          </h3>
        </div>
        <span className="mm-approval-flag">Agreement</span>
      </div>
      <div className="mm-verifund-detail">
        <div>
          <span className="mm-kicker">Transaction</span>
          <strong>{agreement.transaction_id}</strong>
        </div>
        <div>
          <span className="mm-kicker">Version</span>
          <strong>{agreement.agreement_version}</strong>
        </div>
        <div>
          <span className="mm-kicker">Hash</span>
          <strong className="mm-mono-note">{agreement.agreement_hash}</strong>
        </div>
        <div>
          <span className="mm-kicker">Buyer</span>
          <strong>{reviewLabel("Buyer", buyerReview)}</strong>
        </div>
        <div>
          <span className="mm-kicker">Seller</span>
          <strong>{reviewLabel("Seller", sellerDecision)}</strong>
        </div>
      </div>
      <ul className="mm-verifund-lines">
        {agreement.line_items.map((item) => (
          <li key={`${item.sku}-${item.unit_price_cents}`}>
            <span>
              {item.quantity} × {item.name}
            </span>
            <span>{money(item.unit_price_cents, agreement.currency)}</span>
          </li>
        ))}
      </ul>
      <p className="mm-verifund-meta">
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
  // The LLM relay may drop the nested binding fields; show the top-level
  // binding (which the backend validates) in the agreement summary.
  const displayAgreement = {
    ...args.agreement,
    agreement_version:
      args.agreement_version ?? args.agreement.agreement_version,
    agreement_hash: args.agreement_hash ?? args.agreement.agreement_hash,
  } as VerifundAgreement;
  return (
    <section
      className="mm-approval"
      data-testid="verifund-funding"
      aria-labelledby="verifund-funding-title"
    >
      <p className="mm-kicker">Verifund · human funding approval</p>
      <h3 id="verifund-funding-title">{args.message}</h3>
      <AgreementReviewCard
        agreement={displayAgreement}
        buyerReview={args.buyer_review}
        sellerDecision={args.seller_decision}
      />
      {!ready ? (
        <p role="alert" data-testid="verifund-funding-blocked" className="mm-verifund-blocked">
          {readiness === "mismatch"
            ? "The recorded reviews are bound to different terms. Funding is blocked."
            : `Waiting for the ${
                readiness === "buyer_pending" ? "Buyer" : "Seller"
              } decision before funding.`}
        </p>
      ) : null}
      <label className="mm-note-field">
        Note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      <div className="mm-approval-actions">
        <button
          type="button"
          className="mm-button mm-button-signal"
          disabled={!ready}
          onClick={() => onApprove(note)}
        >
          Approve funding
        </button>
        <button
          type="button"
          className="mm-button mm-button-outline-danger"
          disabled={!ready}
          onClick={() => onReject(note)}
        >
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
      className="mm-approval"
      data-testid="verifund-release"
      aria-labelledby="verifund-release-title"
    >
      <p className="mm-kicker">Verifund · human release approval</p>
      <h3 id="verifund-release-title">{args.message}</h3>
      {!gate.enabled ? (
        <p role="alert" className="mm-verifund-blocked">{gate.reason}</p>
      ) : null}
      <label className="mm-note-field">
        Note
        <textarea
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>
      {gate.overrideAllowed ? (
        <label className="mm-note-field">
          <input
            type="checkbox"
            checked={override}
            onChange={(event) => setOverride(event.target.checked)}
          />
          Override the verification failure
        </label>
      ) : null}
      <div className="mm-approval-actions">
        <button
          type="button"
          className="mm-button mm-button-signal"
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
          className="mm-button mm-button-outline-danger"
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
  const counts = evidenceCounts(evidence);
  const reasons = (projection.verification?.reasons ?? []) as string[];
  return (
    <section className="mm-approval" data-testid="verifund-evidence">
      <p className="mm-kicker">Verifund · evidence review</p>
      <p>
        {counts
          ? `${counts.received}/${counts.required} required evidence items received`
          : "No evidence has been reported."}
      </p>
      {projection.verification ? (
        <p>
          Verification: {projection.verification.status}
          {reasons.length ? ` · ${reasons.join(", ")}` : ""}
        </p>
      ) : null}
    </section>
  );
}

export function ReceiptCard({ receipt }: { receipt: SettlementReceipt }) {
  return (
    <section className="mm-approval" data-testid="verifund-receipt">
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
    <section className="mm-approval" data-testid="verifund-checkout">
      <p className="mm-kicker">Verifund · funding handoff</p>
      <a href={url} target="_blank" rel="noreferrer">
        Open the payment checkout
      </a>
      {expiresAt ? <p>Link expires at {expiresAt}</p> : null}
    </section>
  );
}

export function PayPalCheckoutCard({
  args,
  respond,
  onVerifundAction,
  pollIntervalMs = 2000,
}: {
  args: PayPalCheckoutArgs;
  respond?: (result: unknown) => Promise<void>;
  onVerifundAction?: () => void;
  pollIntervalMs?: number;
}) {
  const [phase, setPhase] = useState<
    "ready" | "confirming" | "fallback" | "error"
  >("ready");
  const [error, setError] = useState<string | null>(null);
  const busy = phase === "confirming";
  const agreement = (args.agreement ?? {}) as Record<string, any>;
  const terms = agreementTerms(agreement);
  const totals = (terms.totals ?? {}) as Record<string, any>;
  const chargeCurrency = String(args.currency ?? "USD");
  const agreementCurrency = String(totals.currency ?? chargeCurrency);
  const agreementId = String(agreement.agreement_id ?? "");
  const agreementVersion = Number(agreement.agreement_version ?? 1);
  const inspection = (terms.inspection ?? {}) as Record<string, any>;
  const evidence = Array.isArray(terms.evidence_required)
    ? terms.evidence_required
    : [];
  const agreementTotal = Number(totals.total_cents ?? args.amount_cents);
  const currencyMismatch = agreementCurrency !== chargeCurrency;
  const amountMismatch =
    agreementTotal !== args.amount_cents || currencyMismatch;
  const status = {
    ready: { label: "Secure payment", className: " is-amber" },
    confirming: { label: "Processing payment", className: " is-amber" },
    fallback: { label: "PayPal unavailable", className: " is-muted" },
    error: { label: "Payment not completed", className: " is-muted" },
  }[phase];

  async function decide(decision: Record<string, unknown>) {
    await respond?.(decision);
    onVerifundAction?.();
  }

  function base() {
    return {
      transaction_id: args.transaction_id,
      idempotency_key: `checkout:${args.transaction_id}`,
    };
  }

  async function pollUntilFunded() {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, pollIntervalMs));
      const projection = await pollFundingAction({
        transactionId: args.transaction_id,
      });
      if (projection.state === "FUNDED") return projection;
      if (projection.state !== "FUNDING_PENDING") break;
    }
    throw new Error("Payment captured but settlement is still pending");
  }

  async function approve({ orderId }: { orderId: string }) {
    try {
      setPhase("confirming");
      setError(null);
      const result = await captureOrderAction({
        transactionId: args.transaction_id,
        orderId,
      });
      const projection =
        result.settlementState === "FUNDED"
          ? { transaction_id: args.transaction_id, state: "FUNDED" }
          : await pollUntilFunded();
      setPhase("ready");
      await decide({
        status: "completed",
        ...base(),
        order_id: result.orderId,
        capture_id: result.captureId,
        projection,
      });
    } catch (cause) {
      setPhase("error");
      setError(
        cause instanceof Error ? cause.message : "The payment did not settle.",
      );
    }
  }

  return (
    <section className="mm-approval" data-testid="paypal-checkout">
      <div className="mm-verifund-head">
        <div>
          <p className="mm-kicker">Verifund checkout</p>
          <h3>
            <span>Secure checkout</span>
          </h3>
        </div>
        <span className={`mm-status-pill${status.className}`}>
          <LockKeyhole size={11} />
          {status.label}
        </span>
      </div>

      <p className="mm-approval-prompt">
        Payment for agreement {agreementId} · v{agreementVersion}
      </p>

      <div data-testid="checkout-product-summary">
        <ProductSummary agreement={agreement} />
      </div>

      <div className="mm-money" data-testid="checkout-order-summary">
        <p className="mm-money-label">Order summary</p>
        <div className="mm-money-row">
          <span>Product price</span>
          <strong>
            {money(
              Number(totals.subtotal_cents ?? args.amount_cents),
              agreementCurrency,
            )}
          </strong>
        </div>
        <div className="mm-money-row">
          <span>Tracked shipping</span>
          <strong>
            {money(Number(totals.shipping_cents ?? 0), agreementCurrency)}
          </strong>
        </div>
        <div className="mm-money-row">
          <span>Taxes</span>
          <strong>
            {money(Number(totals.tax_cents ?? 0), agreementCurrency)}
          </strong>
        </div>
        <div className="mm-money-row">
          <span>Fees</span>
          <strong>
            {money(Number(totals.fees_cents ?? 0), agreementCurrency)}
          </strong>
        </div>
        <div className="mm-money-total">
          <span>Total payable</span>
          <strong data-testid="verifund-checkout-amount">
            {money(args.amount_cents, chargeCurrency)}{" "}
            <em>{chargeCurrency}</em>
          </strong>
        </div>
        {amountMismatch ? (
          <p className="mm-amount-warning" data-testid="checkout-amount-mismatch">
            {agreementTotal !== args.amount_cents ? (
              <>
                The agreement total is{" "}
                {money(agreementTotal, agreementCurrency)}; the amount being
                charged is {money(args.amount_cents, chargeCurrency)}.
              </>
            ) : (
              <>
                The agreement is denominated in {agreementCurrency}; the charge
                is in {chargeCurrency}.
              </>
            )}
          </p>
        ) : null}
      </div>

      <div className="mm-trust" data-testid="checkout-trust-panel">
        <p className="mm-trust-head">
          <ShieldCheck size={14} />
          <span>
            Payment is processed through PayPal and recorded against agreement{" "}
            {agreementId}. Fulfillment is evaluated against the agreed
            verification conditions.
          </span>
        </p>
        <div className="mm-trust-grid">
          <span>
            <Truck size={14} /> Tracked delivery
          </span>
          <span>
            <Clock3 size={14} />
            {inspection.period_hours ?? "—"}-hour inspection
          </span>
          <span>
            <ShieldCheck size={14} /> {evidence.length} verification rules
          </span>
        </div>
      </div>

      <div className="mm-money">
        <p className="mm-money-label">Payment method</p>
        {phase === "fallback" ? (
          <div>
            <p className="mm-approval-prompt">
              PayPal is unavailable in this browser.
            </p>
            <button
              type="button"
              className="mm-button"
              onClick={() => decide({ status: "fallback", ...base() })}
            >
              Pay on PayPal&apos;s site
            </button>
          </div>
        ) : (
          <PayPalProvider
            clientId={process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID ?? ""}
            environment={
              process.env.NEXT_PUBLIC_PAYPAL_ENVIRONMENT === "production"
                ? "production"
                : "sandbox"
            }
            components={["paypal-payments"]}
            pageType="checkout"
          >
            <div className="w-full" style={{ width: "100%" }}>
              <PayPalOneTimePaymentButton
                presentationMode="auto"
                disabled={busy}
                className="w-full"
                style={{ width: "100%" }}
                createOrder={async () => {
                  const { id } = await createOrderAction({
                    transactionId: args.transaction_id,
                  });
                  return { orderId: id };
                }}
                onApprove={approve}
                onCancel={() => decide({ status: "canceled", ...base() })}
                onError={() => setPhase("fallback")}
              />
            </div>
          </PayPalProvider>
        )}
        {busy ? <p className="mm-approval-prompt">Confirming payment…</p> : null}
        {phase === "error" && error ? <p role="alert">{error}</p> : null}
        {args.expires_at ? (
          <p className="mm-mono-note">Offer expires at {args.expires_at}</p>
        ) : null}
      </div>

      <p className="mm-approval-prompt">
        <Info size={11} /> By continuing, you authorize payment for the
        transaction described in the approved Verifund agreement.
      </p>
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

export function AgreementApprovalHitlCard({
  args,
  respond,
  onVerifundAction,
}: {
  args: AgreementApprovalArgs;
  respond?: (result: unknown) => Promise<void>;
  onVerifundAction?: () => void;
}) {
  const [note, setNote] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const a = (args?.agreement ?? {}) as Record<string, any>;
  const id = String(args?.agreement_id ?? a.agreement_id ?? a.id ?? "");
  const version = Number(args?.version ?? a.current_version ?? a.agreement_version ?? 1);
  const hash = String(args?.digest ?? a.agreement_hash ?? a.version?.agreement_hash ?? "");
  const handle: ResumeHandle | null =
    args?.handle?.task_id && args?.handle?.context_id && args?.handle?.run_id
      ? {
          task_id: args.handle.task_id,
          context_id: args.handle.context_id,
          run_id: args.handle.run_id,
        }
      : null;
  const url = args?.review_url ?? a.review_url;
  const seller = args?.seller_decision ?? a.seller_decision;
  const pc = args?.precheck;

  const terms = agreementTerms(a);
  const totals = (terms.totals ?? {}) as Record<string, any>;
  const currency = String(totals.currency ?? a.currency ?? "USD");
  const inspection = (terms.inspection ?? {}) as Record<string, any>;
  const delivery = (terms.delivery ?? {}) as Record<string, any>;
  const remedies = (terms.remedies ?? {}) as Record<string, any>;
  const evidence = Array.isArray(terms.evidence_required)
    ? terms.evidence_required
    : [];
  const approved = a.status === "AGREED";
  const expiresAt = formatStamp(a.expires_at);
  const sellerStatus =
    typeof seller === "string"
      ? seller
      : seller?.status ?? seller?.decision ?? "Accepted";
  const precheckStatus = pc
    ? typeof pc === "string"
      ? pc
      : pc.recommendation ?? pc.status
    : null;

  const decide = async (
    action: (id: string, version: number, hash: string, note: string, key: string, handle?: ResumeHandle | null) => Promise<any>,
    decision: "APPROVE" | "REJECT" | "REQUEST_CHANGES",
  ) => {
    if (pending) return;
    setPending(true);
    setError(null);
    const key = `buyer-decision:${decision}:${id}:${version}:${crypto.randomUUID()}`;
    try {
      const result = await action(id, version, hash, note, key, handle);
      if (!result?.decisionRecorded) {
        setError(result?.error ?? "decision_failed");
        return;
      }
      await respond?.(result);
      onVerifundAction?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "decision_failed");
    } finally {
      setPending(false);
    }
  };

  return (
    <section data-testid="agreement-approval-hitl" className="mm-approval">
      <div className="mm-verifund-head">
        <div>
          <p className="mm-kicker">Verifund agreement</p>
          <h3>
            <span>{id || "Agreement"}</span>
          </h3>
        </div>
        {approved ? (
          <span className="mm-status-pill">
            <CheckCircle2 size={11} /> Approved
          </span>
        ) : (
          <span className="mm-status-pill is-amber">
            <Clock3 size={11} /> Awaiting your approval
          </span>
        )}
      </div>

      <div className="mm-verifund-detail">
        <div>
          <p className="mm-kicker">Version</p>
          <strong>v{version}</strong>
        </div>
        <div>
          <p className="mm-kicker">Expires</p>
          <strong>{expiresAt ?? "Not set"}</strong>
        </div>
      </div>

      <div data-testid="agreement-product-summary">
        <ProductSummary agreement={a} />
      </div>

      <div className="mm-money" data-testid="agreement-money-rows">
        <p className="mm-money-label">Agreed commercial terms</p>
        <div className="mm-money-row">
          <span>Product price</span>
          <strong>
            {money(Number(totals.subtotal_cents ?? a.amount_cents ?? 0), currency)}
          </strong>
        </div>
        <div className="mm-money-row">
          <span>Tracked shipping</span>
          <strong>{money(Number(totals.shipping_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Taxes</span>
          <strong>{money(Number(totals.tax_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Fees</span>
          <strong>{money(Number(totals.fees_cents ?? 0), currency)}</strong>
        </div>
        <div className="mm-money-total">
          <span>Total payable</span>
          <strong>
            {money(Number(totals.total_cents ?? a.amount_cents ?? 0), currency)}{" "}
            <em>{currency}</em>
          </strong>
        </div>
      </div>

      <div className="mm-inspection" data-testid="agreement-inspection-panel">
        <p className="mm-money-label">
          <Clock3 size={11} /> Inspection and verification
        </p>
        <dl className="mm-inspection-grid">
          <div>
            <dt>Inspection window</dt>
            <dd>
              {inspection.period_hours ?? a.inspection_period_hours ?? 0} hours
              after {String(inspection.starts_on ?? "delivery").replaceAll("_", " ").toLowerCase()}
            </dd>
          </div>
          <div>
            <dt>Verification checklist</dt>
            <dd>
              <ul className="mm-check-list">
                {evidence.length ? (
                  evidence.map((item: string) => (
                    <li key={item}>
                      <CheckCircle2 size={11} />
                      {labelFor(EVIDENCE_LABELS, item)}
                    </li>
                  ))
                ) : (
                  <li>No evidence requirements listed</li>
                )}
              </ul>
            </dd>
          </div>
        </dl>
      </div>

      <details className="mm-card-section">
        <summary>
          <ShieldCheck size={12} /> Seller obligations
        </summary>
        <ul className="mm-check-list">
          <li>
            <CheckCircle2 size={11} /> Match the agreed product specifications
          </li>
          <li>
            <CheckCircle2 size={11} /> Provide tracked shipping within{" "}
            {delivery.delivery_days ?? a.delivery_days ?? 0} days
          </li>
          <li>
            <CheckCircle2 size={11} /> Maintain a{" "}
            {terms.warranty_months ?? a.warranty_months ?? 0}-month warranty
          </li>
        </ul>
      </details>

      <details className="mm-card-section">
        <summary>
          <Info size={12} /> Returns and disputes
        </summary>
        <div className="mm-acceptance">
          <div className="mm-acceptance-row">
            <span>Not delivered</span>
            <strong>
              {remedies.non_delivery
                ? labelFor(REMEDY_LABELS, remedies.non_delivery)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Late delivery</span>
            <strong>
              {remedies.late_delivery
                ? labelFor(REMEDY_LABELS, remedies.late_delivery)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Damaged goods</span>
            <strong>
              {remedies.damaged_goods
                ? labelFor(REMEDY_LABELS, remedies.damaged_goods)
                : "Not specified"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Returns window</span>
            <strong>{terms.returns_days ?? a.returns_days ?? 0} days</strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Dispute window</span>
            <strong>{terms.dispute_window_hours ?? 0} hours</strong>
          </div>
        </div>
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer">
            Open full agreement <ChevronRight size={11} />
          </a>
        ) : null}
      </details>

      <details className="mm-card-section">
        <summary>
          <FileCheck2 size={12} /> Agreement acceptance
        </summary>
        <div className="mm-acceptance">
          <div className="mm-acceptance-row">
            <span>Seller Agent</span>
            <strong className="is-ok">{String(sellerStatus)}</strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Buyer</span>
            <strong className="is-pending">
              {approved ? "Approved" : "Awaiting approval"}
            </strong>
          </div>
          <div className="mm-acceptance-row">
            <span>Verifund</span>
            <strong className="is-ok">Validated</strong>
          </div>
          {precheckStatus ? (
            <div className="mm-acceptance-row">
              <span>Precheck</span>
              <strong>{String(precheckStatus)}</strong>
            </div>
          ) : null}
        </div>
      </details>

      <details className="mm-card-section">
        <summary>
          <LockKeyhole size={12} /> Agreement digest
        </summary>
        <p className="mm-digest">
          <strong>{String(hash).slice(0, 16) || "unavailable"}</strong>
          <span>Created {formatStamp(a.created_at) ?? "unknown"}</span>
          <span>v{version}</span>
        </p>
      </details>

      <label className="mm-note-field">
        Note
        <textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          disabled={pending}
        />
      </label>

      <div className="mm-approval-actions mm-approval-actions-split">
        <button
          type="button"
          className="mm-button mm-button-signal mm-approval-primary"
          disabled={pending || !id}
          onClick={() => decide(approveAgreement, "APPROVE")}
        >
          {pending ? "Working…" : "Approve"}
        </button>
        <button
          type="button"
          className="mm-button mm-button-outline-danger"
          disabled={pending || !id}
          onClick={() => decide(rejectAgreement, "REJECT")}
        >
          Reject
        </button>
        <button
          type="button"
          className="mm-button mm-button-outline"
          disabled={pending || !id}
          onClick={() => decide(requestChangesAgreement, "REQUEST_CHANGES")}
        >
          Request changes
        </button>
      </div>

      {!id ? (
        <p role="alert" data-testid="agreement-hitl-missing-id">
          Agreement id is missing — please re-present the approval card.
        </p>
      ) : null}

      {error ? (
        <p role="alert" data-testid="agreement-hitl-error">
          {error}
        </p>
      ) : null}

      <p className="mm-approval-prompt">
        Approval applies only to agreement {id}, version v{version}.
      </p>
    </section>
  );
}
