"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { EvidenceSummaryLines } from "@/features/chat/components/evidence-summary-lines";
import { useRunLaunch } from "@/features/chat/use-run-launch";
import type { SettlementProjection } from "@/lib/types";

export function EvidenceWaitCard({
  checkpoint,
  projection,
}: {
  checkpoint?: string | null;
  projection?: Partial<SettlementProjection> | null;
}) {
  const { agent } = useAgent({ agentId: "marketmesh_orchestrator" });
  const { runOnActiveThread } = useRunLaunch();

  const checkStatus = () => {
    void runOnActiveThread(() => {
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: "Check Verifund status",
      });
    });
  };

  return (
    <div
      className="mm-approval is-waiting"
      role="status"
      data-testid="verifund-evidence-wait"
      data-checkpoint={checkpoint ?? undefined}
    >
      <div className="mm-verifund-head">
        <p className="mm-kicker">Waiting for seller evidence</p>
        <span className="mm-status-pill is-amber">Evidence pending</span>
      </div>
      <p className="mm-approval-prompt">
        The seller is submitting fulfillment evidence. When it has been
        verified, check the status to continue to payment release.
      </p>
      <EvidenceSummaryLines projection={projection ?? null} />
      <button
        type="button"
        className="mm-button mm-button-signal"
        onClick={checkStatus}
        disabled={agent.isRunning}
      >
        Check status
      </button>
    </div>
  );
}
