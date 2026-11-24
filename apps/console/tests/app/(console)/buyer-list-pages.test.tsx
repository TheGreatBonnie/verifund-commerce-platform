import { render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({
  searchParams: new URLSearchParams(),
  replace: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => nav.searchParams,
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  usePathname: () => "/transactions",
}));

const api = vi.hoisted(() => ({ listBuyerTransactions: vi.fn() }));
vi.mock("@/lib/buyer-transaction-api", () => ({
  listBuyerTransactions: api.listBuyerTransactions,
}));

import TransactionsPage from "@/app/(console)/transactions/page";
import FulfillmentListPage from "@/app/(console)/fulfillment/page";

const tx = {
  transaction_id: "tx_1",
  product_name: "Nimbus Drone",
  seller_name: "Acme Supply",
  agreed_amount_cents: 12550,
  currency: "USD",
  transaction_status: "FUNDED",
  payment_status: "PAID",
  fulfillment_status: "awaiting_inspection",
  next_action: "inspect_goods",
  updated_at: "2026-01-05T10:00:00Z",
};

beforeEach(() => {
  nav.searchParams = new URLSearchParams();
  nav.replace.mockClear();
  api.listBuyerTransactions.mockReset();
});

describe("TransactionsPage", () => {
  it("passes URL filters to the API and offers a retry on failure", async () => {
    nav.searchParams = new URLSearchParams("status=funded&payment_status=paid");
    api.listBuyerTransactions.mockRejectedValue(new Error("boom"));

    render(<TransactionsPage />);

    expect(
      await screen.findByRole("button", { name: /try again/i }),
    ).toBeInTheDocument();
    expect(api.listBuyerTransactions).toHaveBeenCalledWith({
      status: "funded",
      payment_status: "paid",
    });
  });

  it("renders overview and rows after a successful load", async () => {
    api.listBuyerTransactions.mockResolvedValue({
      items: [tx],
      aggregates: { total: 1 },
    });

    render(<TransactionsPage />);

    expect(
      await screen.findByRole("link", { name: "View transaction tx_1" }),
    ).toBeInTheDocument();
    expect(
      within(screen.getByRole("region", { name: "Overview" })).getByText("Total"),
    ).toBeInTheDocument();
  });
});

describe("FulfillmentListPage", () => {
  it("derives fulfillment-specific counts instead of reusing transaction aggregates", async () => {
    api.listBuyerTransactions.mockResolvedValue({
      items: [tx],
      aggregates: { total: 5, awaiting_payment: 2 },
    });

    render(<FulfillmentListPage />);

    const overview = await screen.findByRole("region", { name: "Overview" });
    await waitFor(() =>
      expect(within(overview).getByText("Awaiting Inspection")).toBeInTheDocument(),
    );
    expect(within(overview).queryByText("Awaiting Payment")).not.toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View fulfillment tx_1" }),
    ).toBeInTheDocument();
  });

  it("passes fulfillment filters to the API", async () => {
    nav.searchParams = new URLSearchParams("fulfillment_status=issue");
    api.listBuyerTransactions.mockResolvedValue({ items: [] });

    render(<FulfillmentListPage />);

    await waitFor(() =>
      expect(api.listBuyerTransactions).toHaveBeenCalledWith({
        fulfillment_status: "issue",
      }),
    );
  });
});
