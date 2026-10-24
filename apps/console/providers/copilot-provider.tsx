"use client";

import {
  CopilotChatConfigurationProvider,
  CopilotKitProvider,
} from "@copilotkit/react-core/v2";
import { ReactNode } from "react";

const threadsEnabled =
  process.env.NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED === "true";

export function CopilotProvider({ children }: { children: ReactNode }) {
  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" useSingleEndpoint={false}>
      <CopilotChatConfigurationProvider
        agentId="a2a_chat"
        labels={{
          modalHeaderTitle: "MarketMesh runs",
          chatInputPlaceholder:
            "Describe the purchase, budget, deadline, and warranty…",
          welcomeMessageText:
            "Tell me what your team needs. I’ll find independent sellers, negotiate structured offers, and stop for your approval before any order.",
          chatDisclaimerText:
            "Buyer agent · every order requires a human decision.",
        }}
      >
        {children}
      </CopilotChatConfigurationProvider>
    </CopilotKitProvider>
  );
}

export { threadsEnabled };
