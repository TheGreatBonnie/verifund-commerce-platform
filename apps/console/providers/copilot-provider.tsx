"use client";

import {
  CopilotChatConfigurationProvider,
  CopilotKitProvider,
} from "@copilotkit/react-core/v2";
import { ReactNode, useState } from "react";
import { ThreadLockNotice } from "@/features/chat/components/thread-lock-notice";

const threadsEnabled =
  process.env.NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED === "true";

export function CopilotProvider({ children }: { children: ReactNode }) {
  const [threadLocked, setThreadLocked] = useState(false);

  return (
    <CopilotKitProvider
      runtimeUrl="/api/copilotkit"
      useSingleEndpoint={false}
      onError={(event) => {
        if (event.code === "agent_thread_locked") setThreadLocked(true);
      }}>
      <CopilotChatConfigurationProvider
        agentId="marketmesh_orchestrator"
        labels={{
          modalHeaderTitle: "MarketMesh runs",
          chatInputPlaceholder:
            "Describe the purchase, budget, deadline, and warranty…",
          welcomeMessageText:
            "Tell me what your team needs. I’ll find independent sellers, negotiate structured offers, and stop for your approval before any order.",
          chatDisclaimerText:
            "Buyer agent · every order requires a human decision.",
        }}>
        {threadLocked ? (
          <ThreadLockNotice onDismiss={() => setThreadLocked(false)} />
        ) : null}
        {children}
      </CopilotChatConfigurationProvider>
    </CopilotKitProvider>
  );
}

export { threadsEnabled };
