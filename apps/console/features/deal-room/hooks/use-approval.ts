"use client";

import { useAgent } from "@copilotkit/react-core/v2";
import { useState } from "react";

export function useApproval(taskId: string | undefined) {
  const { agent } = useAgent({ agentId: "a2a_chat", updates: [] });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const sendApproval = async (approved: boolean, note: string) => {
    if (!taskId) return;
    const payload = { approval: { approved, approved_by: "Demo Buyer", note }, task_id: taskId };
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: `MarketMesh approval response: ${JSON.stringify(payload)}`,
    });
    setIsSubmitting(true);
    try {
      await agent.runAgent();
    } finally {
      setIsSubmitting(false);
    }
  };
  return { sendApproval, isSubmitting };
}
