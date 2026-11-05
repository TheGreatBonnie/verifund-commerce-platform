import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs", () => ({
  OrganizationSwitcher: () => <div data-testid="org-switcher" />,
  UserButton: () => <div data-testid="user-button" />,
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
  it("shows the organization and user controls", () => {
    render(
      <ConsoleLayout userId="user_1" orgId="org_1">
        <div>content</div>
      </ConsoleLayout>,
    );
    expect(screen.getByTestId("org-switcher")).toBeInTheDocument();
    expect(screen.getByTestId("user-button")).toBeInTheDocument();
    expect(screen.getByText("content")).toBeInTheDocument();
  });
});
