import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  useFrontendTool: vi.fn(),
  useHumanInTheLoop: vi.fn(),
  useRenderTool: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChat: () => <div data-testid="copilot-chat" />,
  useAgent: () => ({ agent: { messages: [] }, isReady: true }),
  useFrontendTool: hooks.useFrontendTool,
  useHumanInTheLoop: hooks.useHumanInTheLoop,
  useRenderTool: hooks.useRenderTool,
}));

import { Chat } from "./chat";

function renderChat() {
  return render(
    <Chat
      onRunSample={vi.fn()}
      isRunning={false}
      isReady
      verifundMode="fake"
    />,
  );
}

describe("chat verifund tools", () => {
  beforeEach(() => {
    hooks.useFrontendTool.mockClear();
    hooks.useHumanInTheLoop.mockClear();
    hooks.useRenderTool.mockClear();
  });

  it("registers the agreement review as a callable frontend tool", () => {
    renderChat();

    const call = hooks.useFrontendTool.mock.calls.find(
      ([tool]) => tool.name === "show_agreement_review",
    );
    expect(call).toBeTruthy();
    expect(call?.[0]).toMatchObject({
      name: "show_agreement_review",
      agentId: "marketmesh_orchestrator",
      available: true,
    });
    expect(typeof call?.[0].handler).toBe("function");
    expect(call?.[0].render).toEqual(expect.any(Function));
  });

  it("does not rely on a renderer-only review tool", () => {
    renderChat();

    const renderNames = hooks.useRenderTool.mock.calls.map(
      ([tool]) => tool.name,
    );
    expect(renderNames).not.toContain("show_agreement_review");
  });
});
