import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  AdminFields,
  AdminKpis,
  AdminRawDisclosure,
  AdminTable,
  AdminValue,
} from "@/components/admin/admin-primitives";

describe("AdminValue", () => {
  it("formats money, dates and booleans by field semantics", () => {
    const { rerender } = render(
      <AdminValue field="amount_cents" value={123450} />,
    );
    expect(screen.getByText("USD 1,234.50")).toBeInTheDocument();

    rerender(<AdminValue field="created_at" value="2026-11-20T10:30:00Z" />);
    expect(screen.getByText(/Nov 20, 2026/)).toBeInTheDocument();

    rerender(<AdminValue field="is_platform_admin" value />);
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("renders missing values and statuses without leaking raw JSON", () => {
    const { rerender } = render(<AdminValue value={null} />);
    expect(screen.getByText("—")).toBeInTheDocument();

    rerender(<AdminValue field="status" value="FUNDS_HELD" />);
    expect(screen.getByText("Funds Held")).toHaveClass("mm-status");
    expect(screen.queryByText(/\{/)).toBeNull();
  });

  it("renders scalar arrays as chips", () => {
    render(<AdminValue value={["shipment_manifest", "invoice"]} />);
    expect(screen.getByText("shipment manifest")).toBeInTheDocument();
    expect(screen.getByText("invoice")).toBeInTheDocument();
  });
});

describe("AdminFields", () => {
  it("orders preferred fields, skips excluded keys and nests one level", () => {
    render(
      <AdminFields
        data={{
          status: "OPEN",
          amount_cents: 5000,
          internal_token: "secret",
          summary: { seller: "Acme", extra: { deep: true } },
        }}
        columns={["status", "amount_cents"]}
        exclude={["internal_token"]}
      />,
    );

    const fields = screen.getByTestId("admin-fields");
    const labels = within(fields)
      .getAllByRole("term")
      .map((node) => node.textContent);
    expect(labels.slice(0, 2)).toEqual(["Status", "Amount Cents"]);
    expect(labels).not.toContain("Internal Token");
    expect(screen.getByText("Acme")).toBeInTheDocument();
    expect(screen.queryByText(/secret/)).toBeNull();
  });

  it("shows an honest empty state", () => {
    render(<AdminFields data={undefined} />);
    expect(screen.getByText("No fields available.")).toBeInTheDocument();
  });
});

describe("AdminTable", () => {
  const rows = [
    {
      transaction_id: "txn_1",
      state: "FUNDED",
      amount_cents: 12550,
      created_at: "2026-11-20T10:30:00Z",
    },
    {
      transaction_id: "txn_2",
      state: "PENDING",
      amount_cents: 9000,
      created_at: "2026-11-21T10:30:00Z",
    },
  ];

  it("renders semantic columns, formatted values and detail links", () => {
    render(
      <AdminTable
        title="Platform transactions"
        rows={rows}
        columns={[
          { key: "transaction_id", label: "Transaction" },
          { key: "state", label: "State" },
          { key: "amount_cents", label: "Amount" },
          { key: "created_at", label: "Created" },
        ]}
        detailHref={(row) => `/admin/transactions/${row.transaction_id}`}
      />,
    );

    const table = screen.getByRole("table", { name: "Platform transactions" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((node) => node.textContent),
    ).toEqual(["Transaction", "State", "Amount", "Created"]);
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(within(table).getByText("USD 125.50")).toBeInTheDocument();
    expect(
      within(table).getByRole("link", { name: "txn_1" }),
    ).toHaveAttribute("href", "/admin/transactions/txn_1");
    expect(screen.queryByText(/"transaction_id"/)).toBeNull();
  });

  it("shows an empty state instead of an empty JSON blob", () => {
    render(
      <AdminTable title="Disputes" rows={[]} columns={[{ key: "id" }]} />,
    );
    expect(screen.getByText("No disputes to display.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

describe("AdminKpis", () => {
  it("renders labelled stat tiles", () => {
    render(
      <AdminKpis
        items={[
          { label: "Held funds", value: "USD 1,234.50", hint: "Across 3 transactions" },
          { label: "Open disputes", value: 2 },
        ]}
      />,
    );
    expect(screen.getByText("Held funds")).toBeInTheDocument();
    expect(screen.getByText("USD 1,234.50")).toBeInTheDocument();
    expect(screen.getByText("Across 3 transactions")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});

describe("AdminRawDisclosure", () => {
  it("keeps the raw response behind a collapsed disclosure", () => {
    render(<AdminRawDisclosure value={{ id: "txn_1" }} />);
    const details = screen
      .getByText("View raw response")
      .closest("details") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(details.querySelector("pre")?.textContent).toContain('"id": "txn_1"');
  });
});
