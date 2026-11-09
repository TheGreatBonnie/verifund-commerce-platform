import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({
  pathname: "/marketplace",
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ push: nav.push }),
}));

import { ModeToggle } from "@/components/layout/mode-toggle";

const LAST_APP_PATH_KEY = "marketmesh:lastAppPath";

describe("ModeToggle", () => {
  beforeEach(() => {
    nav.push.mockClear();
    nav.pathname = "/marketplace";
    window.sessionStorage.clear();
  });

  it("switches from the app to chat-only mode", () => {
    render(<ModeToggle />);

    fireEvent.click(screen.getByRole("button", { name: "Chat only" }));

    expect(nav.push).toHaveBeenCalledWith("/chat");
    expect(
      screen.getByRole("button", { name: "Full app" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("remembers the last app page when switching back from chat", () => {
    window.sessionStorage.setItem(LAST_APP_PATH_KEY, "/marketplace");
    nav.pathname = "/chat";

    render(<ModeToggle />);

    fireEvent.click(screen.getByRole("button", { name: "Full app" }));

    expect(nav.push).toHaveBeenCalledWith("/marketplace");
    expect(
      screen.getByRole("button", { name: "Chat only" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("stores the current page as the last app page while in app mode", () => {
    render(<ModeToggle />);

    expect(window.sessionStorage.getItem(LAST_APP_PATH_KEY)).toBe(
      "/marketplace",
    );
  });
});
