"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { useRunLaunch } from "@/features/chat/use-run-launch";

export function EvidenceWaitCard({
  checkpoint,
}: {
  checkpoint?: string | null;
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
      className="mm-chat-approval"
      role="status"
      data-testid="verifund-evidence-wait"
      data-checkpoint={checkpoint ?? undefined}
    >
      <p className="mm-kicker">Waiting for seller evidence</p>
      <p>
        The seller is submitting fulfillment evidence. When it has been
        verified, check the status to continue to payment release.
      </p>
      <button type="button" onClick={checkStatus} disabled={agent.isRunning}>
        Check status
      </button>
    </div>
  );
}
