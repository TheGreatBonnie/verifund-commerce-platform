import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  addMessage: vi.fn(),
  runAgent: vi.fn(),
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: { addMessage: hooks.addMessage } }),
  useCopilotKit: () => ({ copilotkit: { runAgent: hooks.runAgent } }),
}));

import { ProductSearchCards } from "@/features/chat/product-cards";

const MACBOOK = {
  sku: "MM-MACBOOK-AIR-M4-13",
  name: "MacBook Air M4 13-inch",
  category: "Electronics",
  description: "Apple M4 · 16GB memory · 256GB SSD · Space Gray",
  image_url: "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500",
  unit_price_cents: 99900,
  original_unit_price_cents: 119900,
  currency: "USD",
  rating: 4.6,
  reviews: "128 reviews",
  seller: "Northwind Audio",
  offers: [
    {
      seller_id: "northwind-audio",
      seller_name: "Northwind Audio",
      unit_price_cents: 99900,
      currency: "USD",
      available: true,
      on_hand: 8,
      incoming: 0,
    },
  ],
  match_rationale: ["query:laptop:name"],
};

const MONITOR = {
  sku: "MM-4K-MONITOR-27",
  name: "27-inch 4K USB-C Monitor",
  category: "Electronics",
  description: "4K UHD · USB-C hub · Height adjustable",
  image_url: "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=500",
  unit_price_cents: 49900,
  original_unit_price_cents: null,
  currency: "USD",
  rating: 4.7,
  seller: "Northwind Audio",
  offers: [
    {
      seller_id: "northwind-audio",
      seller_name: "Northwind Audio",
      unit_price_cents: 49900,
      currency: "USD",
      available: false,
      on_hand: 0,
      incoming: 0,
    },
  ],
};

const PAYLOAD = {
  total_candidates: 2,
  products: [MACBOOK, MONITOR],
};

describe("product search cards", () => {
  beforeEach(() => {
    hooks.addMessage.mockClear();
    hooks.runAgent.mockReset();
    hooks.runAgent.mockResolvedValue(undefined);
  });

  it("renders grounded product name, price, seller, and availability", () => {
    render(
      <ProductSearchCards status="complete" result={JSON.stringify(PAYLOAD)} />,
    );

    expect(screen.getByText("MacBook Air M4 13-inch")).toBeInTheDocument();
    expect(screen.getByText("27-inch 4K USB-C Monitor")).toBeInTheDocument();
    expect(screen.getAllByText("$999.00").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Northwind Audio").length).toBeGreaterThan(0);
    expect(screen.getByText("In stock at 1 seller")).toBeInTheDocument();
    expect(screen.getByText("Out of stock")).toBeInTheDocument();
  });

  it("accepts the same payload as an object", () => {
    render(<ProductSearchCards status="complete" result={PAYLOAD} />);
    expect(screen.getByText("MacBook Air M4 13-inch")).toBeInTheDocument();
  });

  it("tolerates the A2A response prefix", () => {
    render(
      <ProductSearchCards
        status="complete"
        result={`A2A Agent Response: ${JSON.stringify(PAYLOAD)}`}
      />,
    );
    expect(screen.getByText("MacBook Air M4 13-inch")).toBeInTheDocument();
  });

  it("renders only the products in the result", () => {
    render(<ProductSearchCards status="complete" result={PAYLOAD} />);
    expect(screen.queryByText("Imaginary Laptop")).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /ask agent to negotiate/i }),
    ).toHaveLength(2);
  });

  it("dispatches the negotiate intent in the current thread", async () => {
    render(<ProductSearchCards status="complete" result={PAYLOAD} />);

    fireEvent.click(
      screen.getAllByRole("button", { name: /ask agent to negotiate/i })[0],
    );

    await waitFor(() => expect(hooks.addMessage).toHaveBeenCalledTimes(1));
    expect(hooks.addMessage).toHaveBeenCalledWith(
      expect.objectContaining({ role: "user" }),
    );
    expect(hooks.addMessage.mock.calls[0][0].content).toContain(
      "MM-MACBOOK-AIR-M4-13",
    );
    await waitFor(() => expect(hooks.runAgent).toHaveBeenCalledTimes(1));
  });

  it("renders marketplace-aligned art, price, and action layout", () => {
    const { container } = render(
      <ProductSearchCards status="complete" result={PAYLOAD} />,
    );

    const art = container.querySelector(".mm-product-art");
    expect(art).not.toBeNull();
    expect(art?.querySelector("img")).not.toBeNull();
    expect(art?.textContent).toContain("In stock");

    expect(container.querySelector(".mm-product-category")?.textContent).toBe(
      "Electronics",
    );
    expect(container.querySelector("del")?.textContent).toBe("$1,199.00");
    expect(container.querySelector(".mm-marketplace-rating")).not.toBeNull();

    const buttons = screen.getAllByRole("button", {
      name: /ask agent to negotiate/i,
    });
    expect(buttons.length).toBe(2);
    for (const button of buttons) {
      expect(button).toHaveClass("mm-product-action");
    }
  });

  it("renders an empty state when no products match", () => {
    render(
      <ProductSearchCards
        status="complete"
        result={{ total_candidates: 0, products: [] }}
      />,
    );
    expect(screen.getByText(/no matching products/i)).toBeInTheDocument();
  });

  it("disables the negotiate button while the dispatch is pending", async () => {
    let resolveRun: (() => void) | undefined;
    hooks.runAgent.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveRun = resolve;
        }),
    );
    render(<ProductSearchCards status="complete" result={PAYLOAD} />);

    const button = screen.getAllByRole("button", {
      name: /ask agent to negotiate/i,
    })[0];
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    await act(async () => {
      resolveRun?.();
    });
    await waitFor(() => expect(button).not.toBeDisabled());
  });

  it("renders the upstream error message instead of an empty state", () => {
    render(
      <ProductSearchCards
        status="complete"
        result={{
          error: "marketplace_unavailable",
          message: "Marketplace catalog is unavailable",
        }}
      />,
    );
    expect(
      screen.getByText("Marketplace catalog is unavailable"),
    ).toBeInTheDocument();
  });

  it("scrolls the horizontal track with prev/next controls", () => {
    const { container } = render(
      <ProductSearchCards status="complete" result={PAYLOAD} />,
    );
    const track = container.querySelector(".mm-product-grid");
    expect(track).not.toBeNull();
    const scrollBy = vi.fn();
    (track as HTMLElement).scrollBy = scrollBy;

    fireEvent.click(
      screen.getByRole("button", { name: "Next products" }),
    );
    expect(scrollBy).toHaveBeenCalledWith({
      left: 288,
      behavior: "smooth",
    });

    fireEvent.click(
      screen.getByRole("button", { name: "Previous products" }),
    );
    expect(scrollBy).toHaveBeenCalledWith({
      left: -288,
      behavior: "smooth",
    });
  });
});
