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
  SignInButton: ({ children, mode }: { children: React.ReactNode; mode?: string }) => (
    <div data-testid="sign-in-button" data-mode={mode}>
      {children}
    </div>
  ),
  SignUpButton: ({ children, mode }: { children: React.ReactNode; mode?: string }) => (
    <div data-testid="sign-up-button" data-mode={mode}>
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
    expect(screen.getByTestId("sign-up-button")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign up/i })).toBeInTheDocument();
    expect(screen.queryByTestId("org-switcher")).not.toBeInTheDocument();
    expect(screen.queryByTestId("user-button")).not.toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });
});
