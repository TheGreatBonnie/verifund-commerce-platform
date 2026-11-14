"use client";

import { useEffect, useState } from "react";

import { fetchRun, type BuyerRun } from "@/lib/api";
import type { Award, Mandate } from "@/lib/types";

import { ApprovalCard } from "./approval-card";

type AwardApprovalProps = {
  taskId: string;
  award?: Award | null;
  mandate?: Mandate | null;
  message?: string;
  onApprove: (note: string) => Promise<unknown> | void;
  onReject: (note: string) => Promise<unknown> | void;
};

/**
 * The orchestrator only has to forward the Buyer's task id: the award is owned
 * by the Buyer and served from the run, so the approval never depends on the
 * model echoing a large award object into its tool arguments.
 */
export function AwardApproval({
  taskId,
  award,
  mandate,
  message,
  onApprove,
  onReject,
}: AwardApprovalProps) {
  const [run, setRun] = useState<BuyerRun | null>(null);
  const [failed, setFailed] = useState(false);
  const fromArgument = Boolean(award && award.winner);

  useEffect(() => {
    if (fromArgument) return;
    let cancelled = false;
    fetchRun(taskId)
      .then((loaded) => {
        if (!cancelled) setRun(loaded);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [fromArgument, taskId]);

  if (fromArgument) {
    return (
      <ApprovalCard
        award={award}
        mandate={mandate}
        message={message}
        onApprove={onApprove}
        onReject={onReject}
      />
    );
  }

  if (failed) {
    return (
      <section className="mm-approval mm-approval-empty" role="status" aria-live="polite">
        <p className="mm-kicker">Human checkpoint</p>
        <h2>Approval required</h2>
        <p>
          Could not load the award for this run. Ask the agent to show the
          award again, or retry the request.
        </p>
      </section>
    );
  }

  if (!run) {
    return (
      <div className="mm-chat-approval-pending" role="status">
        Preparing the award for your review…
      </div>
    );
  }

  return (
    <ApprovalCard
      award={run.award ?? null}
      mandate={mandate ?? run.mandate ?? null}
      message={message}
      onApprove={onApprove}
      onReject={onReject}
    />
  );
}
