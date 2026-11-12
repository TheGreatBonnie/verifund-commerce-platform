import { act, fireEvent, render, screen } from "@testing-library/react";
import { CopilotChat } from "@copilotkit/react-core/v2";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  useFrontendTool: vi.fn(),
  useHumanInTheLoop: vi.fn(),
  useRenderTool: vi.fn(),
  addMessage: vi.fn(),
  runAgent: vi.fn(),
  fetchRegistry: vi.fn(),
  useUser: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  fetchRegistry: hooks.fetchRegistry,
}));

vi.mock("@clerk/nextjs", () => ({
  useUser: hooks.useUser,
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

hooks.useUser.mockReturnValue({ user: null });
hooks.fetchRegistry.mockResolvedValue([]);

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

describe("chat seller naming", () => {
  const NORTHWIND_ID = "33a492070e344199803b6d0f4331cee0";

  beforeEach(() => {
    hooks.useRenderTool.mockClear();
    hooks.fetchRegistry.mockReset();
    hooks.fetchRegistry.mockResolvedValue([
      {
        seller_id: NORTHWIND_ID,
        name: "Northwind Audio",
        card_url: `http://127.0.0.1:9200/${NORTHWIND_ID}/.well-known/agent-card.json`,
        categories: ["Audio"],
        card_hash: "hash",
        last_seen_at: "now",
        healthy: true,
        last_error: null,
      },
    ]);
  });

  const mediateRender = async () => {
    renderChat();
    // Flush the registry fetch so registryNames settles, mirroring page load
    // completing long before a mediation runs.
    await act(async () => {});
    return hooks.useRenderTool.mock.calls
      .filter(([tool]) => tool.name === "mediate_seller_call")
      .at(-1)?.[0].render;
  };

  it("shows the seller display name for UUID seller ids", async () => {
    const renderTool = await mediateRender();

    render(
      renderTool({
        parameters: {
          seller_id: NORTHWIND_ID,
          seller_card_url: `http://127.0.0.1:9200/${NORTHWIND_ID}/.well-known/agent-card.json`,
          seller_request: { quantity: 1, product_hint: "MacBook Air" },
        },
        status: "complete",
        result: JSON.stringify({
          seller_result: { offers: [{ total_cents: 107999 }] },
        }),
      }),
    );

    expect((await screen.findAllByText("Northwind Audio")).length).toBeGreaterThan(0);
    expect(screen.queryByText(NORTHWIND_ID)).not.toBeInTheDocument();
  });

  it("prefers an explicit seller_name when the agent supplies one", async () => {
    const renderTool = await mediateRender();

    render(
      renderTool({
        parameters: {
          seller_id: NORTHWIND_ID,
          seller_name: "Northwind Audio Co.",
          seller_card_url: `http://127.0.0.1:9200/${NORTHWIND_ID}/.well-known/agent-card.json`,
          seller_request: { quantity: 1, product_hint: "MacBook Air" },
        },
        status: "complete",
        result: JSON.stringify({
          seller_result: { offers: [{ total_cents: 107999 }] },
        }),
      }),
    );

    expect((await screen.findAllByText("Northwind Audio Co.")).length).toBeGreaterThan(0);
  });
});

describe("chat sourcing mandate", () => {
  beforeEach(() => {
    hooks.useHumanInTheLoop.mockClear();
  });

  const mandateTool = () =>
    hooks.useHumanInTheLoop.mock.calls.find(
      ([tool]) => tool.name === "request_sourcing_mandate",
    );

  const args = {
    task_id: "task-1",
    message: "Confirm mandate before sourcing.",
    product: {
      sku: "EX-MACBOOK-AIR",
      name: "MacBook Air (M1)",
      image_url: "https://example.com/macbook-air-m1.jpg",
      offers: [{ seller_name: "CircuitForge", unit_price_cents: 107999, currency: "USD", in_stock: true }],
    },
    defaults: { quantity: 1, budget_ceiling_cents: 150000, currency: "USD" },
  };

  it("registers request_sourcing_mandate as a blocking HITL tool", () => {
    renderChat();
    const call = mandateTool();
    expect(call?.[0]).toMatchObject({
      name: "request_sourcing_mandate",
      agentId: "marketmesh_orchestrator",
    });
    expect(call?.[0].parameters).toBeTruthy();
    expect(call?.[0].render).toEqual(expect.any(Function));
  });

  it("renders a preparing state while in progress", () => {
    renderChat();
    const call = mandateTool();
    render(call![0].render({ args, status: "inProgress" }));
    expect(screen.getByRole("status")).toHaveTextContent(/preparing.*mandate/i);
  });

  it("responds with confirmed mandate on submit and cancelled on cancel", () => {
    renderChat();
    const call = mandateTool();

    const respondCancel = vi.fn();
    const { unmount } = render(
      call![0].render({ args, status: "executing", respond: respondCancel }),
    );
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(respondCancel).toHaveBeenCalledWith(
      expect.objectContaining({ confirmed: false, task_id: "task-1", reason: "user_cancelled" }),
    );
    unmount();

    const respondSubmit = vi.fn();
    render(call![0].render({ args, status: "executing", respond: respondSubmit }));
    fireEvent.change(screen.getByLabelText(/delivery deadline/i), { target: { value: "2026-12-01" } });
    fireEvent.change(screen.getByLabelText(/warranty/i), { target: { value: "1y warranty, 30d returns" } });
    fireEvent.change(screen.getByLabelText(/must-have/i), { target: { value: "8GB RAM" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm.*buyer/i }));
    expect(respondSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        confirmed: true,
        task_id: "task-1",
        product: expect.objectContaining({ sku: "EX-MACBOOK-AIR" }),
        mandate: expect.objectContaining({ quantity: 1 }),
      }),
    );
  });

  it("reports confirmed and cancelled outcomes when complete", () => {
    renderChat();
    const call = mandateTool();
    const { rerender } = render(
      call![0].render({ args, status: "complete", result: JSON.stringify({ confirmed: true }) }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/confirmed/i);
    rerender(
      call![0].render({
        args,
        status: "complete",
        result: JSON.stringify({ confirmed: false, reason: "user_cancelled" }),
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent(/no sourcing/i);
    expect(screen.getByRole("status")).toHaveTextContent(/no order/i);
  });
});
