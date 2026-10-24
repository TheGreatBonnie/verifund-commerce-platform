"use client";

import { CopilotThreadsDrawer } from "@copilotkit/react-core/v2";
import { ReactNode } from "react";
import { CopilotProvider, threadsEnabled } from "@/providers/copilot-provider";
import { QueryProvider } from "@/providers/query-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { ChatDrawer } from "@/components/layout/chat-drawer";
import { SkipLink } from "@/components/layout/skip-link";

export function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <CopilotProvider>
      <QueryProvider>
        <div className={threadsEnabled ? "mm-app-frame" : undefined}>
          {threadsEnabled ? (
            <div className="mm-thread-drawer-shell">
              <CopilotThreadsDrawer
                agentId="a2a_chat"
                label="MarketMesh runs"
                recentLabel="Recent sourcing runs"
              />
            </div>
          ) : null}
          <div className="mm-shell" style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "stretch" }}>
            <SkipLink />
            <Sidebar />
            <main id="main-content" className="mm-console-main">
              {children}
            </main>
            <ChatDrawer />
          </div>
        </div>
      </QueryProvider>
    </CopilotProvider>
  );
}
