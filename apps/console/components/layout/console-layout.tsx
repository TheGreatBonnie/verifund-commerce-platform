"use client";

import { ReactNode } from "react";
import { OrganizationSwitcher, UserButton } from "@clerk/nextjs";
import { CopilotProvider, threadsEnabled } from "@/providers/copilot-provider";
import { QueryProvider } from "@/providers/query-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { SkipLink } from "@/components/layout/skip-link";

export function ConsoleLayout({
  children,
  userId,
  orgId,
}: {
  children: ReactNode;
  userId?: string;
  orgId?: string | null;
}) {
  return (
    <CopilotProvider>
      <QueryProvider>
        <div className={threadsEnabled ? "mm-app-frame" : undefined} suppressHydrationWarning>
          <div className="mm-shell" style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "stretch" }}>
            <SkipLink />
            <Sidebar />
            <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
              <header
                title={userId ?? undefined}
                style={{ display: "flex", justifyContent: "flex-end", gap: "8px", padding: "8px 16px", borderBottom: "1px solid var(--rule)" }}
              >
                <OrganizationSwitcher
                  afterCreateOrganizationUrl="/"
                  afterSelectOrganizationUrl="/"
                  hidePersonal={false}
                />
                <UserButton />
              </header>
              <main id="main-content" className="mm-console-main">
                {children}
              </main>
            </div>
          </div>
        </div>
      </QueryProvider>
    </CopilotProvider>
  );
}
