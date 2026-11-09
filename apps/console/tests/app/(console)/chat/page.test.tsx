import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  useFrontendTool: vi.fn(),
  push: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotThreadsDrawer: () => <div data-testid="threads-drawer" />,
  useFrontendTool: hooks.useFrontendTool,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/chat",
  useRouter: () => ({ push: hooks.push }),
}));

vi.mock("@/features/chat/chat", () => ({
  Chat: ({ variant, onRunSample }: { variant?: string; onRunSample: () => void }) => (
    <div data-testid="chat" data-variant={variant ?? "rail"}>
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
