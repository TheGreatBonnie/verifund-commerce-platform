import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  useFrontendTool: vi.fn(),
  push: vi.fn(),
  searchParams: new URLSearchParams(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotThreadsDrawer: () => <div data-testid="threads-drawer" />,
  useFrontendTool: hooks.useFrontendTool,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: hooks.push }),
  useSearchParams: () => hooks.searchParams,
}));

vi.mock("@/features/chat/chat", () => ({
  Chat: ({
    variant,
    onRunSample,
    prefilledPrompt,
  }: {
    variant?: string;
    onRunSample: () => void;
    prefilledPrompt?: string | null;
  }) => (
    <div
      data-testid="chat"
      data-variant={variant ?? "rail"}
      data-prefilled-prompt={prefilledPrompt ?? ""}
    >
      <button type="button" onClick={onRunSample}>
        Run sample brief
      </button>
    </div>
  ),
}));

import ChatPage from "@/app/(console)/chat/page";

describe("chat-only page", () => {
  beforeEach(() => {
    hooks.useFrontendTool.mockClear();
    hooks.searchParams = new URLSearchParams();
  });

  it("renders the chat full-screen without the deal room", () => {
    render(<ChatPage />);

    expect(screen.getByTestId("chat")).toBeInTheDocument();
  });

  it("renders the threads drawer for the orchestrator agent", () => {
    render(<ChatPage />);

    expect(screen.getByTestId("threads-drawer")).toBeInTheDocument();
  });

  it("renders the chat without the Demo Mandate rail section", () => {
    render(<ChatPage />);

    // The "embedded" variant hides the rail header and the Demo Mandate
    // block ("Run sample brief") above the chat surface.
    expect(screen.getByTestId("chat")).toHaveAttribute(
      "data-variant",
      "embedded",
    );
  });

  it("prefills the chat from a transaction handoff deep link", () => {
    hooks.searchParams = new URLSearchParams({
      transaction_id: "tx_123",
      intent: "release",
    });

    render(<ChatPage />);

    expect(screen.getByTestId("chat")).toHaveAttribute(
      "data-prefilled-prompt",
      expect.stringContaining("tx_123"),
    );
  });

  it("ignores a deep link that has no transaction id", () => {
    hooks.searchParams = new URLSearchParams({ intent: "release" });

    render(<ChatPage />);

    expect(screen.getByTestId("chat")).toHaveAttribute(
      "data-prefilled-prompt",
      "",
    );
  });

  it("lets the agent switch back to the full app", () => {
    render(<ChatPage />);

    const tool = hooks.useFrontendTool.mock.calls.find(
      ([config]) => config.name === "enableAppMode",
    );
    expect(tool).toBeTruthy();

    tool?.[0].handler();

    expect(hooks.push).toHaveBeenCalledWith(expect.stringMatching(/^\//));
  });
});
