import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => {
  const protect = vi.fn();
  const authFn = vi.fn();
  const auth = Object.assign(authFn, { protect });
  return { protect, authFn, auth };
});

vi.mock("@clerk/nextjs/server", () => ({
  auth: hoisted.auth,
}));

vi.mock("@/app/choose-role/choose-role-client", () => ({
  ChooseRoleClient: () => <div data-testid="choose-role-client" />,
}));

import ChooseRolePage from "@/app/choose-role/page";

describe("ChooseRolePage", () => {
  it("protects and renders the role chooser", async () => {
    hoisted.protect.mockResolvedValue({ userId: "user_1" });
    hoisted.authFn.mockResolvedValue({ userId: "user_1" });
    render(await ChooseRolePage());
    expect(screen.getByTestId("choose-role-client")).toBeInTheDocument();
  });
});
