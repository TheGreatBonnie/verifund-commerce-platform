import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const hooks = vi.hoisted(() => ({
  useHumanInTheLoop: vi.fn(),
  useFrontendTool: vi.fn(),
  useRenderTool: vi.fn(),
  addMessage: vi.fn(),
  runAgent: vi.fn(),
  fetchRegistry: vi.fn(),
  useUser: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ fetchRegistry: hooks.fetchRegistry }));
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChat: vi.fn(() => <div data-testid="copilot-chat" />),
  useAgent: () => ({ agent: { messages: [], addMessage: hooks.addMessage }, isReady: true }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
  useFrontendTool: hooks.useFrontendTool,
  useHumanInTheLoop: hooks.useHumanInTheLoop,
  useRenderTool: hooks.useRenderTool,
}));
vi.mock("@clerk/nextjs", () => ({
  useUser: hooks.useUser,
}));

import { Chat } from "@/features/chat/chat";

hooks.fetchRegistry.mockResolvedValue([]);

describe("chat approval approver identity", () => {
  beforeEach(() => {
    hooks.useHumanInTheLoop.mockClear();
    hooks.useFrontendTool.mockClear();
    hooks.useRenderTool.mockClear();
    hooks.useUser.mockReturnValue({
      isLoaded: true,
      isSignedIn: true,
      user: {
        fullName: "Alice Example",
        firstName: "Alice",
        lastName: "Example",
        id: "user_123",
        primaryEmailAddress: { emailAddress: "alice@example.com" },
      },
    });
  });

  it("stamps the Clerk display name as approved_by instead of Demo Buyer", async () => {
    render(
      <Chat onRunSample={vi.fn()} isRunning={false} isReady threadId="t1" verifundMode="fake" />
    );
    const awardTool = hooks.useHumanInTheLoop.mock.calls.find(
      ([tool]) => tool.name === "request_award_approval"
    )?.[0];
    expect(awardTool).toBeTruthy();

    const respond = vi.fn(async (_payload: unknown) => {});
    const { container } = render(
      awardTool.render({
        args: {
          task_id: "task-1",
          message: "Approve award",
          award: {
            winner: {
              seller_name: "Northwind Audio",
              total_cents: 107999,
              seller_id: "33a492070e344199803b6d0f4331cee0",
              offer_id: "offer-1",
              offer_round: 1,
              valid_until: new Date(Date.now() + 3600_000).toISOString(),
            },
            score: 0.97,
            alternatives: [],
            mandate_checks: ["checks passed"],
            scores: {},
            run_id: "run-1",
          },
          mandate: {},
        },
        status: "executing",
        respond,
      })
    );

    // Click approve button in ApprovalCard (query by role)
    const approveBtn = screen.getByRole("button", { name: /approve/i });
    fireEvent.click(approveBtn);

    expect(respond).toHaveBeenCalled();
    const calls = respond.mock.calls as unknown[][];
    const payload = calls[0]?.[0] as { approved_by?: string } | undefined;
    expect(payload?.approved_by).toBe("Alice Example");
    expect(payload?.approved_by).not.toBe("Demo Buyer");
  });
});
