import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const clerk = vi.hoisted(() => ({ signedIn: true }));

vi.mock("@clerk/nextjs", () => ({
  Show: ({ children, when }: { children?: React.ReactNode; when: string }) => {
    const visible = when === "signed-in" ? clerk.signedIn : !clerk.signedIn;
    return visible ? <>{children}</> : null;
  },
  OrganizationSwitcher: () => <div data-testid="org-switcher" />,
  UserButton: () => <div data-testid="user-button" />,
  SignInButton: ({ children, fallbackRedirectUrl }: { children?: React.ReactNode; fallbackRedirectUrl?: string }) => (
    <div data-testid="sign-in-button" data-redirect={fallbackRedirectUrl}>
      {children}
    </div>
  ),
  SignUpButton: ({ children, mode, unsafeMetadata, fallbackRedirectUrl }: { children?: React.ReactNode; mode?: string; unsafeMetadata?: { role?: string }; fallbackRedirectUrl?: string }) => (
    <div
      data-testid="sign-up-button"
      data-mode={mode}
      data-role={unsafeMetadata?.role}
      data-redirect={fallbackRedirectUrl}
    >
      {children}
    </div>
  ),
}));

vi.mock("@/providers/copilot-provider", () => ({
  CopilotProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  threadsEnabled: false,
}));

vi.mock("@/providers/query-provider", () => ({
  QueryProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/layout/sidebar", () => ({
  Sidebar: () => <div data-testid="sidebar" />,
}));

import { ConsoleLayout } from "@/components/layout/console-layout";

describe("ConsoleLayout", () => {
  beforeEach(() => {
    clerk.signedIn = true;
  });

  it("shows the organization and user controls when signed in", () => {
    render(
      <ConsoleLayout userId="user_1" orgId="org_1">
        <div>content</div>
      </ConsoleLayout>,
    );
    expect(screen.getByTestId("org-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("user-button")).toBeInTheDocument();
    expect(screen.queryByTestId("sign-in-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("sign-up-button")).not.toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });

  it("shows sign in and sign up modal buttons when signed out", () => {
    clerk.signedIn = false;
    render(
      <ConsoleLayout>
        <div>content</div>
      </ConsoleLayout>,
    );
    expect(screen.getByTestId("sign-in-button")).toBeInTheDocument();
    expect(screen.getAllByTestId("sign-up-button")).toHaveLength(2);
    const signUpButtons = screen.getAllByTestId("sign-up-button");
    expect(signUpButtons.map((b) => b.dataset.role)).toEqual(["buyer", "seller"]);
    signUpButtons.forEach((b) => {
      expect(b.dataset.mode).toBe("modal");
      expect(b.dataset.redirect).toBe("/post-auth");
    });
    expect(screen.getByTestId("sign-in-button").dataset.redirect).toBe("/post-auth");
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign up as buyer/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign up as seller/i })).toBeInTheDocument();
    expect(screen.queryByTestId("org-switcher")).not.toBeInTheDocument();
    expect(screen.queryByTestId("user-button")).not.toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });
});
