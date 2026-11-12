import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  addMessage: vi.fn(),
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: { addMessage: hooks.addMessage } }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
}));

import { ProductRecommendations } from "@/features/chat/product-recommendations";

const PAYLOAD = {
  title: "Top matches for a programming laptop",
  context_note: "Filtered out non-laptop items that also surfaced in the search.",
  products: [
    {
      sku: "EX-WORKSTATION-1",
      name: "Advanced Workstation Laptop",
      best_price_cents: 134999,
      currency: "USD",
      seller_name: "CircuitForge",
      notes: "Powerful workstation for intensive workloads; 4.7★",
      rating: 4.7,
    },
    {
      sku: "EX-MBA-M2",
      name: "MacBook Air M2",
      best_price_cents: 116999,
      currency: "USD",
      seller_name: "CircuitForge",
      notes: "Latest Air, upgraded performance/battery; 4.7★",
      rating: 4.7,
    },
  ],
  recommendation: {
    sku: "EX-WORKSTATION-1",
    reason: "Strongest fit for intensive programming workloads under budget.",
  },
  alternative: {
    sku: "EX-MBA-M2",
    reason: "Great balance of performance and portability for macOS.",
  },
};

describe("product recommendations table", () => {
  beforeEach(() => {
    hooks.addMessage.mockClear();
    hooks.runAgent.mockReset();
    hooks.runAgent.mockResolvedValue(undefined);
  });

  it("renders a comparison table with grounded products and recommendation", () => {
    render(<ProductRecommendations status="complete" result={JSON.stringify(PAYLOAD)} />);

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("Advanced Workstation Laptop")).toBeInTheDocument();
    expect(screen.getByText("MacBook Air M2")).toBeInTheDocument();
    expect(screen.getByText("$1,349.99")).toBeInTheDocument();
    expect(screen.getByText("$1,169.99")).toBeInTheDocument();
    expect(screen.getAllByText("CircuitForge").length).toBeGreaterThan(0);
    expect(screen.getByText(/Filtered out non-laptop items/i)).toBeInTheDocument();
    expect(screen.getByText(/Strongest fit for intensive programming workloads/i)).toBeInTheDocument();
    expect(screen.getByText(/Great balance of performance and portability/i)).toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    expect(screen.getByText("Alternative")).toBeInTheDocument();
  });

  it("dispatches a negotiate intent for the selected product", async () => {
    render(<ProductRecommendations status="complete" result={PAYLOAD} />);

    fireEvent.click(
      screen.getByRole("button", { name: /ask agent to negotiate for advanced workstation laptop/i }),
    );

    await waitFor(() => expect(hooks.addMessage).toHaveBeenCalledTimes(1));
    expect(hooks.addMessage.mock.calls[0][0].content).toContain("EX-WORKSTATION-1");
    expect(hooks.addMessage.mock.calls[0][0].content).toContain("Do not place an order");
    await waitFor(() => expect(hooks.runAgent).toHaveBeenCalledTimes(1));
  });

  it("renders loading, empty, and error states", () => {
    const { rerender } = render(
      <ProductRecommendations status="inProgress" result={undefined} />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/preparing comparison/i);

    rerender(<ProductRecommendations status="complete" result={{ products: [] }} />);
    expect(screen.getByText(/no matching products to compare/i)).toBeInTheDocument();

    rerender(
      <ProductRecommendations
        status="complete"
        result={{ error: "retrieval_unavailable", message: "Product search is temporarily unavailable" }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(/temporarily unavailable/i);
  });
});
