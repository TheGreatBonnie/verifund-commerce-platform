"use client";

import { ReactNode } from "react";
import { CopilotProvider, threadsEnabled } from "@/providers/copilot-provider";
import { QueryProvider } from "@/providers/query-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { SkipLink } from "@/components/layout/skip-link";

export function ConsoleLayout({ children }: { children: ReactNode }) {
  return (
    <CopilotProvider>
      <QueryProvider>
        <div className={threadsEnabled ? "mm-app-frame" : undefined}>
          <div className="mm-shell" style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "stretch" }}>
            <SkipLink />
            <Sidebar />
            <main id="main-content" className="mm-console-main">
              {children}
            </main>
          </div>
        </div>
      </QueryProvider>
    </CopilotProvider>
  );
}
