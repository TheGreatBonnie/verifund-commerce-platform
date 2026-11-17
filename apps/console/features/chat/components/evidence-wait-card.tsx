"use client";

import { useEffect } from "react";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";

export function EvidenceWaitCard({
  checkpoint,
  pollIntervalMs = 10_000,
}: {
  checkpoint?: string | null;
  pollIntervalMs?: number;
}) {
  const { agent } = useAgent({ agentId: "marketmesh_orchestrator" });
  const { copilotkit } = useCopilotKit();

  useEffect(() => {
    if (checkpoint !== "evidence_pending" || pollIntervalMs <= 0) return;
    const timer = window.setInterval(() => {
      if (agent.isRunning) return;
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: "Check Verifund status",
      });
      void copilotkit.runAgent({ agent });
    }, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [agent, checkpoint, copilotkit, pollIntervalMs]);

  return (
    <div
      className="mm-chat-approval"
      role="status"
      data-testid="verifund-evidence-wait"
    >
      <p className="mm-kicker">Waiting for seller evidence</p>
      <p>
        The seller is submitting fulfillment evidence. This chat will continue
        automatically when the evidence is verified.
      </p>
    </div>
  );
}
