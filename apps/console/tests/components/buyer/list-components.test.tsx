import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { TransactionList } from "@/components/buyer/transactions/transaction-list";
import { FulfillmentList } from "@/components/buyer/fulfillment/fulfillment-list";
import { BuyerFilters } from "@/components/buyer/shared/buyer-filters";
import {
  deriveFulfillmentCounts,
  filterParamsFromSearch,
} from "@/lib/buyer-list-filters";

const transaction = {
  transaction_id: "tx_1",
  product_name: "Nimbus Drone",
  seller_name: "Acme Supply",
  agreed_amount_cents: 12550,
  currency: "USD",
  transaction_status: "FUNDED",
  payment_status: "PAID",
  fulfillment_status: "in_progress",
  updated_at: "2026-01-05T10:00:00Z",
};

describe("TransactionList", () => {
  it("renders scannable hybrid rows with disambiguated links and a chat handoff", () => {
    render(<TransactionList items={[transaction]} />);

    expect(screen.getByText("Nimbus Drone")).toBeInTheDocument();
    expect(screen.getByText("Seller: Acme Supply")).toBeInTheDocument();
    expect(screen.getByText("USD 125.50")).toBeInTheDocument();
    expect(screen.getByText("Funded")).toHaveClass("mm-buyer-status-pill");
    expect(
      screen.getByRole("link", { name: "View transaction tx_1" }),
    ).toHaveAttribute("href", "/transactions/tx_1");
    expect(
      screen.getByRole("link", { name: "View fulfillment for tx_1" }),
    ).toHaveAttribute("href", "/fulfillment/tx_1");
    expect(
      screen.getByRole("link", { name: /open in chat for tx_1/i }),
    ).toHaveAttribute("href", "/chat?transaction_id=tx_1&intent=review");
  });

  it("shows an empty state", () => {
    render(<TransactionList items={[]} />);
    expect(screen.getByText(/no transactions available/i)).toBeInTheDocument();
  });
});

describe("FulfillmentList", () => {
  it("leads with fulfillment state and next action plus a chat handoff", () => {
    render(
      <FulfillmentList
        items={[
          {
            ...transaction,
            fulfillment_status: "awaiting_inspection",
            next_action: "inspect_goods",
          },
        ]}
      />,
    );

    expect(screen.getByText("Awaiting Inspection")).toHaveClass(
      "mm-buyer-status-pill",
    );
    expect(screen.getByText(/inspect goods/i)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "View fulfillment tx_1" }),
    ).toHaveAttribute("href", "/fulfillment/tx_1");
    expect(
      screen.getByRole("link", { name: /open in chat for tx_1/i }),
    ).toBeInTheDocument();
  });

  it("shows an empty state", () => {
    render(<FulfillmentList items={[]} />);
    expect(screen.getByText(/no fulfillment records available/i)).toBeInTheDocument();
  });
});

describe("BuyerFilters", () => {
  it("reports a changed filter and offers an Any option", () => {
    const onChange = vi.fn();
    render(
      <BuyerFilters
        fields={[
          {
            key: "status",
            label: "Status",
            options: [{ value: "funded", label: "Funded" }],
          },
        ]}
        values={{ status: "" }}
        onChange={onChange}
      />,
    );

    const select = screen.getByRole("combobox", { name: "Filter by status" });
    expect(screen.getByRole("option", { name: "Any" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "funded" } });
    expect(onChange).toHaveBeenCalledWith("status", "funded");
  });
});

describe("buyer list filter helpers", () => {
  it("reads only supported filters from the URL", () => {
    const params = new URLSearchParams(
      "status=funded&payment_status=paid&limit=50&ignored=1",
    );
    expect(filterParamsFromSearch(params)).toEqual({
      status: "funded",
      payment_status: "paid",
      limit: "50",
    });
  });

  it("derives fulfillment counts from authoritative list items", () => {
    expect(
      deriveFulfillmentCounts([
        { ...transaction, fulfillment_status: "in_progress" },
        {
          transaction_id: "tx_2",
          fulfillment_status: null,
          fulfillment: { status: "awaiting_inspection" },
        },
        { ...transaction, transaction_id: "tx_3", fulfillment_status: "issue" },
      ]),
    ).toMatchObject({
      in_progress: 1,
      awaiting_inspection: 1,
      issue: 1,
      completed: 0,
    });
  });
});
