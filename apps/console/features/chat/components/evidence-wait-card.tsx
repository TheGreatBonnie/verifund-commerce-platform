"use client";

import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";

export function EvidenceWaitCard({
  checkpoint,
}: {
  checkpoint?: string | null;
}) {
  const { agent } = useAgent({ agentId: "marketmesh_orchestrator" });
  const { copilotkit } = useCopilotKit();

  const checkStatus = () => {
    if (agent.isRunning) return;
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: "Check Verifund status",
    });
    void copilotkit.runAgent({ agent });
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
