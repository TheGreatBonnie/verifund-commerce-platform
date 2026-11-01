"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ApprovalActions } from "@/features/agreements/ApprovalActions";
import {
  approveAgreement,
  type AgreementDecisionResult,
  type Decision,
  type ResumeHandle,
  rejectAgreement,
  requestChangesAgreement,
  resumeAgreement,
} from "./actions";

type Props = {
  agreement: any;
  handle: ResumeHandle | null;
};

type PendingDecision = {
  decision: Decision;
  note: string;
  idempotencyKey: string;
};

export function AgreementDecisionPanel({ agreement, handle }: Props) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [result, setResult] = useState<AgreementDecisionResult | null>(null);
  const [lastDecision, setLastDecision] = useState<PendingDecision | null>(null);

  const id = agreement.agreement_id;
  const version =
    agreement.current_version ?? agreement.agreement_version ?? 1;
  const hash =
    agreement.agreement_hash ?? agreement.version?.agreement_hash ?? "";

  const submit =
    (
      action: (
        id: string,
        version: number,
        hash: string,
        note: string,
        idempotencyKey: string,
        handle?: ResumeHandle | null,
      ) => Promise<AgreementDecisionResult>,
      decision: Decision,
    ) =>
    (note: string) => {
      // ApprovalActions treats `disabled` as a stale digest, so guard repeat
      // submissions here instead of passing the pending flag through.
      if (pending) return;
      const decisionRecord = {
        decision,
        note,
        idempotencyKey: `buyer-decision:${decision}:${id}:${version}:${crypto.randomUUID()}`,
      };
      setLastDecision(decisionRecord);
      startTransition(async () => {
        const next = await action(
          id,
          version,
          hash,
          note,
          decisionRecord.idempotencyKey,
          handle,
        );
        setResult(next);
        if (next.decisionRecorded && !next.resumeError) router.refresh();
      });
    };

  const retryResume = () => {
    if (!lastDecision) return;
    startTransition(async () => {
      const next = await resumeAgreement(
        version,
        hash,
        lastDecision.decision,
        lastDecision.note,
        lastDecision.idempotencyKey,
        handle,
      );
      setResult((current) => ({
        ...(current ?? { decisionRecorded: true }),
        ...next,
      }));
      if (!next.resumeError) router.refresh();
    });
  };

  if (result?.decisionRecorded) {
    return (
      <section data-testid="agreement-decision-result">
        <p role="status">Decision recorded.</p>
        {result.resumeError ? (
          <div role="alert" data-testid="resume-error">
            <p>
              The decision is saved, but the agreement lifecycle did not
              resume: {result.resumeError}
            </p>
            <button
              type="button"
              onClick={retryResume}
              disabled={pending || !handle}
            >
              {pending ? "Retrying…" : "Retry resume"}
            </button>
          </div>
        ) : (
          <p>
            The agreement lifecycle resumed. Funding approval is now available
            in the chat.
          </p>
        )}
      </section>
    );
  }

  return (
    <>
      <ApprovalActions
        agreement={agreement}
        onApprove={submit(approveAgreement, "APPROVE")}
        onReject={submit(rejectAgreement, "REJECT")}
        onRequestChanges={submit(requestChangesAgreement, "REQUEST_CHANGES")}
      />
      {result?.error ? (
        <p role="alert" data-testid="decision-error">
          The decision was not recorded ({result.error}). Try again.
        </p>
      ) : null}
    </>
  );
}
