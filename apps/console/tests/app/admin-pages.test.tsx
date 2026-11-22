import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  protect: vi.fn(),
  adminJson: vi.fn(),
}));

vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect: hoisted.protect }),
}));

vi.mock("@/lib/admin-api", () => ({ adminJson: hoisted.adminJson }));

vi.mock("@/components/admin/admin-page", () => ({
  AdminPage: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/app/admin/payouts/actions", () => ({
  approvePayout: vi.fn(),
}));

const pages = [
  {
    name: "overview",
    endpoint: "/v1/admin/overview",
    load: () => import("@/app/admin/page").then((m) => m.default),
  },
  {
    name: "transactions",
    endpoint: "/v1/admin/transactions",
    load: () => import("@/app/admin/transactions/page").then((m) => m.default),
  },
  {
    name: "transaction detail",
    endpoint: "/v1/admin/transactions/txn_1",
    load: () => import("@/app/admin/transactions/[id]/page").then((m) => m.default),
    params: { id: "txn_1" },
  },
  {
    name: "transaction audit",
    endpoint: "/v1/admin/transactions/txn_1/audit",
    load: () => import("@/app/admin/transactions/[id]/audit/page").then((m) => m.default),
    params: { id: "txn_1" },
  },
  {
    name: "payouts",
    endpoint: "/v1/admin/transactions?state=funded",
    load: () => import("@/app/admin/payouts/page").then((m) => m.default),
  },
  {
    name: "disputes",
    endpoint: "/v1/admin/disputes",
    load: () => import("@/app/admin/disputes/page").then((m) => m.default),
  },
  {
    name: "dispute detail",
    endpoint: "/v1/admin/disputes/txn_1",
    load: () => import("@/app/admin/disputes/[id]/page").then((m) => m.default),
    params: { id: "txn_1" },
  },
  {
    name: "verification",
    endpoint: "/v1/admin/verification/pending",
    load: () => import("@/app/admin/verification/page").then((m) => m.default),
  },
  {
    name: "users",
    endpoint: "/api/admin/users",
    load: () => import("@/app/admin/users/page").then((m) => m.default),
  },
  {
    name: "audit",
    endpoint: "/v1/admin/audit",
    load: () => import("@/app/admin/audit/page").then((m) => m.default),
  },
  {
    name: "settings",
    endpoint: "/v1/admin/settings",
    load: () => import("@/app/admin/settings/page").then((m) => m.default),
  },
];

describe("admin pages", () => {
  beforeEach(() => {
    hoisted.protect.mockReset().mockResolvedValue({ userId: "user_1" });
    hoisted.adminJson.mockReset().mockResolvedValue([]);
  });

  it.each(pages)("$name fetches $endpoint behind auth.protect", async (page) => {
    const Page = await page.load();
    await Page(
      ("params" in page ? { params: Promise.resolve(page.params) } : {}) as never,
    );
    expect(hoisted.protect).toHaveBeenCalled();
    expect(hoisted.adminJson).toHaveBeenCalledWith(page.endpoint);
  });

  it("renders the overview as labelled stats instead of a JSON blob", async () => {
    hoisted.adminJson.mockResolvedValue({
      pending_verifications: 3,
      held_funds_cents: 123450,
      currency: "USD",
      open_disputes: 2,
    });
    const Page = await pages[0].load();
    render(await Page({} as never));

    const content = screen.getByTestId("admin-overview");
    expect(content).toBeInTheDocument();
    expect(screen.getByText("Pending verifications")).toBeInTheDocument();
    expect(screen.getByText("USD 1,234.50")).toBeInTheDocument();
    expect(
      Array.from(content.children).some((child) => child.tagName === "PRE"),
    ).toBe(false);
    const raw = screen
      .getByText("View raw response")
      .closest("details") as HTMLDetailsElement;
    expect(raw.open).toBe(false);
    expect(raw.querySelector("pre")?.textContent).toContain(
      "pending_verifications",
    );
  });

  it("renders platform transactions as a table with detail links", async () => {
    hoisted.adminJson.mockResolvedValue([
      {
        transaction_id: "txn_1",
        state: "FUNDED",
        amount_cents: 12550,
        created_at: "2026-11-20T10:30:00Z",
      },
    ]);
    const Page = await pages[1].load();
    render(await Page({} as never));

    expect(
      screen.getByRole("table", { name: "Platform transactions" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "txn_1" }),
    ).toHaveAttribute("href", "/admin/transactions/txn_1");
    expect(screen.getByText("USD 125.50")).toBeInTheDocument();
    const content = screen.getByTestId("admin-transactions");
    expect(
      Array.from(content.children).some((child) => child.tagName === "PRE"),
    ).toBe(false);
    expect(
      screen.getByText("View raw response").closest("details"),
    ).toBeInTheDocument();
  });
});
