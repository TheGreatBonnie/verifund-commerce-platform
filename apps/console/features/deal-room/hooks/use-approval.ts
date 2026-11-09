"use client";

import { useUser } from "@clerk/nextjs";
import { useAgent, useCopilotKit } from "@copilotkit/react-core/v2";
import { useState } from "react";
import { approverDisplayName } from "@/lib/clerk-display-name";

export function useApproval(taskId: string | undefined) {
  const { agent } = useAgent({
    agentId: "marketmesh_orchestrator",
    updates: [],
  });
  const { user } = useUser();
  const approver = approverDisplayName(user);
  const { copilotkit } = useCopilotKit();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sendApproval = async (approved: boolean, note: string) => {
    if (!taskId) return;
    const payload = {
      approval: { approved, approved_by: approver, note },
      task_id: taskId,
    };
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: `MarketMesh approval response: ${JSON.stringify(payload)}`,
    });
    setIsSubmitting(true);
    try {
      await copilotkit.runAgent({ agent });
    } finally {
      setIsSubmitting(false);
    }
  };
  return { sendApproval, isSubmitting };
}
