"use client";

import { ReactNode } from "react";
import { OrganizationSwitcher, UserButton, Show, SignInButton, SignUpButton } from "@clerk/nextjs";
import { CopilotProvider, threadsEnabled } from "@/providers/copilot-provider";
import { QueryProvider } from "@/providers/query-provider";
import { Sidebar } from "@/components/layout/sidebar";
import { SkipLink } from "@/components/layout/skip-link";
import { SellerLink } from "@/components/layout/seller-link";
import { Button } from "@/components/ui/button";

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
                <Show when="signed-out">
                  <SignInButton mode="modal" fallbackRedirectUrl="/post-auth">
                    <Button variant="outline" size="sm">
                      Sign in
                    </Button>
                  </SignInButton>
                  <SignUpButton mode="modal" unsafeMetadata={{ role: "buyer" }} fallbackRedirectUrl="/post-auth">
                    <Button size="sm">
                      Sign up as buyer
                    </Button>
                  </SignUpButton>
                  <SignUpButton mode="modal" unsafeMetadata={{ role: "seller" }} fallbackRedirectUrl="/post-auth">
                    <Button variant="outline" size="sm">
                      Sign up as seller
                    </Button>
                  </SignUpButton>
                </Show>
                <Show when="signed-in">
                  <SellerLink />
                  <OrganizationSwitcher
                    afterCreateOrganizationUrl="/"
                    afterSelectOrganizationUrl="/"
                    hidePersonal={false}
                  />
                  <UserButton />
                </Show>
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
