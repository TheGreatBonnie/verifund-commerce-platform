import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SourcingMandateCard } from "@/features/chat/sourcing-mandate-card";
import { sourcingMandateArgsSchema } from "@/features/chat/sourcing-mandate";

const args = sourcingMandateArgsSchema.parse({
  task_id: "task-1",
  message: "Confirm mandate before sourcing.",
  product: {
    sku: "EX-MACBOOK-AIR",
    name: "MacBook Air (M1)",
    image_url: "https://example.com/macbook-air-m1.jpg",
    offers: [
      { seller_name: "CircuitForge", unit_price_cents: 107999, currency: "USD", in_stock: true },
      { seller_name: "Aurora Supply", unit_price_cents: 113999, currency: "USD", in_stock: true },
    ],
  },
  defaults: { quantity: 1, budget_ceiling_cents: 150000, currency: "USD" },
});

describe("SourcingMandateCard", () => {
  it("shows locked product and offers read-only with prefilled defaults", () => {
    render(<SourcingMandateCard args={args} onSubmit={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.getByText(/EX-MACBOOK-AIR/)).toBeInTheDocument();
    expect(screen.getByText(/MacBook Air \(M1\)/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "MacBook Air (M1)" })).toHaveAttribute(
      "src",
      "https://example.com/macbook-air-m1.jpg",
    );
    expect(screen.getByText(/CircuitForge/)).toBeInTheDocument();
    expect(screen.getByText(/Aurora Supply/)).toBeInTheDocument();
    expect(screen.getByDisplayValue("1")).toBeInTheDocument(); // quantity
    expect(screen.getByDisplayValue("1500.00")).toBeInTheDocument(); // budget hint
    expect(screen.queryByRole("button", { name: /change offer/i })).not.toBeInTheDocument();
  });

  it("submits a normalized confirmed mandate", async () => {
    const onSubmit = vi.fn();
    render(<SourcingMandateCard args={args} onSubmit={onSubmit} onCancel={vi.fn()} />);

    fireEvent.change(screen.getByLabelText(/delivery deadline/i), { target: { value: "2026-12-01" } });
    fireEvent.change(screen.getByLabelText(/warranty/i), { target: { value: "1 year warranty, 30-day returns" } });
    fireEvent.change(screen.getByLabelText(/must-have/i), { target: { value: "8GB RAM, 256GB SSD" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm.*buyer/i }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        quantity: 1,
        budget: { ceiling_cents: 150000, currency: "USD", basis: "per_unit" },
        delivery_deadline: "2026-12-01",
        must_have_attributes: ["8GB RAM", "256GB SSD"],
      }),
    );
  });

  it("cancels without submitting a mandate", () => {
    const onCancel = vi.fn();
    const onSubmit = vi.fn();
    render(<SourcingMandateCard args={args} onSubmit={onSubmit} onCancel={onCancel} />);
    fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("blocks submit and shows errors when required fields are missing", async () => {
    const onSubmit = vi.fn();
    render(<SourcingMandateCard args={{ ...args, defaults: { quantity: 1, currency: "USD" } }} onSubmit={onSubmit} onCancel={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/budget ceiling\/target/i), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: /confirm.*buyer/i }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveTextContent(/budget/i);
  });
});
