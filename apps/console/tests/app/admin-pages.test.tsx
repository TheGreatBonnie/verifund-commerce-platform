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
});
