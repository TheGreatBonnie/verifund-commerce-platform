import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => vi.fn());

vi.mock("@clerk/nextjs/server", () => ({ auth }));

vi.mock("@/components/layout/console-layout", () => ({
  ConsoleLayout: ({
    children,
    userId,
    orgId,
  }: {
    children: React.ReactNode;
    userId?: string;
    orgId?: string | null;
  }) => (
    <div data-testid="console-layout" data-user-id={userId ?? ""} data-org-id={orgId ?? ""}>
      {children}
    </div>
  ),
}));

import PublicLayout from "@/app/(public)/layout";

describe("(public) layout", () => {
  it("renders the console shell for signed-out visitors without calling auth.protect", async () => {
    // No `protect` on the mock: calling auth.protect() would throw.
    auth.mockResolvedValue({ userId: null, orgId: null });
    render(await PublicLayout({ children: <div>public home</div> }));
    expect(screen.getByTestId("console-layout")).toBeInTheDocument();
    expect(screen.getByText("public home")).toBeInTheDocument();
  });

  it("passes the signed-in identity through to the shell", async () => {
    auth.mockResolvedValue({ userId: "user_1", orgId: "org_1" });
    render(await PublicLayout({ children: <div>public home</div> }));
    const shell = screen.getByTestId("console-layout");
    expect(shell.dataset.userId).toBe("user_1");
    expect(shell.dataset.orgId).toBe("org_1");
  });
});
