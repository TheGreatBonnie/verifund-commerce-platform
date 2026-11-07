import { render, screen } from "@testing-library/react";
import { CopilotChat } from "@copilotkit/react-core/v2";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  useFrontendTool: vi.fn(),
  useHumanInTheLoop: vi.fn(),
  useRenderTool: vi.fn(),
  addMessage: vi.fn(),
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChat: vi.fn(() => <div data-testid="copilot-chat" />),
  useAgent: () => ({
    agent: { messages: [], addMessage: hooks.addMessage },
    isReady: true,
  }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
  useFrontendTool: hooks.useFrontendTool,
  useHumanInTheLoop: hooks.useHumanInTheLoop,
  useRenderTool: hooks.useRenderTool,
}));

import { Chat } from "@/features/chat/chat";

function renderChat(
  threadId?: string,
  verifundMode: "off" | "fake" | "sandbox" = "fake",
) {
  return render(
    <Chat
      onRunSample={vi.fn()}
      isRunning={false}
      isReady
      threadId={threadId}
      verifundMode={verifundMode}
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

describe("chat paypal checkout", () => {
  beforeEach(() => {
    hooks.useFrontendTool.mockClear();
    hooks.useHumanInTheLoop.mockClear();
    hooks.useRenderTool.mockClear();
  });

  const checkoutTool = () =>
    hooks.useHumanInTheLoop.mock.calls.find(
      ([tool]) => tool.name === "request_verifund_paypal_checkout",
    );

  it("registers the embedded checkout in sandbox mode", () => {
    renderChat(undefined, "sandbox");

    const call = checkoutTool();
    expect(call?.[0]).toMatchObject({
      name: "request_verifund_paypal_checkout",
      agentId: "marketmesh_orchestrator",
      available: true,
    });
    expect(call?.[0].parameters).toBeTruthy();
  });

  it("does not offer the embedded checkout outside sandbox mode", () => {
    renderChat(undefined, "fake");
    expect(checkoutTool()?.[0].available).toBe(false);
  });

  it("reports the settlement state after the card completes", () => {
    renderChat(undefined, "sandbox");
    const call = checkoutTool();

    render(
      call![0].render({
        args: {
          transaction_id: "vf_1",
          amount_cents: 340000,
          currency: "USD",
        },
        status: "complete",
        result: { state: "FUNDED" },
      }),
    );

    expect(screen.getByTestId("verifund-checkout-settled").textContent).toContain(
      "FUNDED",
    );
  });
});

describe("chat marketplace discovery", () => {
  beforeEach(() => {
    hooks.useRenderTool.mockClear();
  });

  it("registers the marketplace search renderer", () => {
    renderChat();

    const call = hooks.useRenderTool.mock.calls.find(
      ([tool]) => tool.name === "search_marketplace_products",
    );
    expect(call).toBeTruthy();
    expect(call?.[0].parameters).toBeTruthy();
    expect(call?.[0].render).toEqual(expect.any(Function));
  });
});

describe("chat thread wiring", () => {
  it("forwards the thread id to CopilotChat", () => {
    renderChat("thread-1");

    const copilotCall = vi.mocked(CopilotChat).mock.calls.at(-1);
    expect(copilotCall?.[0]).toMatchObject({ threadId: "thread-1" });
  });
});
