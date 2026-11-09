"use client";

import { useState } from "react";

import type {
  SettlementProjection,
  SettlementReceipt,
  SettlementReviewReason,
} from "@/lib/types";
import { money, formatDateTime, evidenceCounts } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Status } from "@/components/ui/status";

type Props = {
  settlement: SettlementProjection | null;
  receipt: SettlementReceipt | null;
  busy: boolean;
  error: string | null;
  onAdvance: () => void;
  onRelease: (body: {
    released_by: string;
    note?: string;
    override?: boolean;
  }) => void;
  onReview: (body: { action: "flag_review" | "retry_payout"; reason?: SettlementReviewReason; note?: string }) => void;
  onCancel: (body: { reason_code: string; note?: string }) => void;
  onRefreshReceipt: () => void;
  evidenceUrl: (id: string) => string;
};

export function TransactionRoom({
  settlement,
  receipt,
  busy,
  error,
  onAdvance,
  onRelease,
  onReview,
  onCancel,
  onRefreshReceipt,
  evidenceUrl,
}: Props) {
  const [releaseNote, setReleaseNote] = useState("");
  if (!settlement) {
    return (
      <div className="text-sm text-muted-foreground">No settlement.</div>
    );
  }

  const funding = settlement.funding;
  const verification = settlement.verification;
  const evidence = settlement.evidence;
  const evidenceCount = evidenceCounts(evidence);
  const evidenceItems = (evidence as any)?.items ?? [];
  const overrideAllowed = verification?.override_allowed ?? false;
  const canRelease = settlement.allowed_actions?.includes("release");
  const canRetryPayout = settlement.allowed_actions?.includes("retry_payout");
  const nonOverridableBlocker =
    verification?.status === "failed" &&
    !settlement.allowed_actions?.includes("release") &&
    (verification?.reasons ?? []).some((r) =>
      ["funding_mismatch", "ledger_incomplete", "late_capture"].includes(r),
    );

  const handleRelease = () => {
    onRelease({
      released_by: "demo-reviewer",
      note: releaseNote,
      override: false,
    });
  };

  return (
    <div className="space-y-4">
      {error && (
        <div className="text-sm text-red-600">{error}</div>
      )}

      {/* Funding */}
      <section>
        <h2 className="text-lg font-semibold">Funding</h2>
        <div className="text-sm">Status: {funding?.status ?? "—"}</div>
        {funding?.payer_action_url && (
          <a
            href={funding.payer_action_url}
            className="text-blue-600 underline"
          >
            Open PayPal checkout
          </a>
        )}
      </section>

      {/* Evidence */}
      <section>
        <h2 className="text-lg font-semibold">Evidence</h2>
        {evidenceCount ? (
          <>
            <div className="text-sm">
              {evidenceCount.received} of {evidenceCount.required} evidence items
            </div>
            <ul>
              {evidenceItems.map((item: any) => (
                <li key={item.evidence_id}>
                  <a href={evidenceUrl(item.evidence_id)} className="underline">
                    {item.original_filename}
                  </a>
                  <span className="ml-2">{item.kind}</span>
                </li>
              ))}
            </ul>
            {/* received kinds rendered in items above */}
          </>
        ) : (
          <div className="text-sm">No evidence has been reported.</div>
        )}
      </section>

      {/* Verification */}
      <section>
        <h2 className="text-lg font-semibold">Verification</h2>
        {verification && (
          <div>
            <div className="text-sm">Status: {verification.status}</div>
            {(verification.reasons ?? []).map((r) => (
              <div key={r} className="text-sm">
                {r.replace(/_/g, " ")}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Release */}
      <section>
        <h2 className="text-lg font-semibold">Release</h2>
        {nonOverridableBlocker && (
          <div className="text-sm">Resolve this in PayPal</div>
        )}
        {canRelease && !nonOverridableBlocker && (
          <div className="space-y-2">
            <label htmlFor="release-note" className="text-sm">
              Release note
            </label>
            <input
              id="release-note"
              aria-label="Release note"
              value={releaseNote}
              onChange={(e) => setReleaseNote(e.target.value)}
              className="border rounded px-2 py-1"
            />
            <Button onClick={handleRelease} disabled={busy}>
              Release funds
            </Button>
          </div>
        )}
        {canRetryPayout && (
          <Button
            onClick={() => onReview({ action: "retry_payout", note: "" })}
            disabled={busy}
          >
            Retry payout
          </Button>
        )}
      </section>

      {/* Receipt */}
      {settlement.receipt_available && receipt && (
        <section>
          <h2 className="text-lg font-semibold">Settlement receipt</h2>
          <div className="text-sm">
            {receipt.verified ? "verified" : "unverified"}
          </div>
          <div className="text-sm">{receipt.kid}</div>
        </section>
      )}
    </div>
  );
}
