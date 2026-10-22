"use client";

import {
  CopilotChatConfigurationProvider,
  CopilotKitProvider,
  CopilotThreadsDrawer,
} from "@copilotkit/react-core/v2";

import { ConsoleShell } from "@/components/console-shell";

const threadsEnabled =
  process.env.NEXT_PUBLIC_COPILOTKIT_THREADS_ENABLED === "true";

export default function Home() {
  return (
    <CopilotKitProvider
      runtimeUrl="/api/copilotkit"
      useSingleEndpoint={false}
    >
      <CopilotChatConfigurationProvider
        agentId="marketmesh_buyer"
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
        <div className={threadsEnabled ? "mm-app-frame" : undefined}>
          {threadsEnabled ? (
            <div className="mm-thread-drawer-shell">
              <CopilotThreadsDrawer
                agentId="marketmesh_buyer"
                label="MarketMesh runs"
                recentLabel="Recent sourcing runs"
              />
            </div>
          ) : null}
          <ConsoleShell />
        </div>
      </CopilotChatConfigurationProvider>
    </CopilotKitProvider>
  );
}
