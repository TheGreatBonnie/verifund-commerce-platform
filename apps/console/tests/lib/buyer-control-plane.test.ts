import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@clerk/nextjs/server", () => ({
  auth: vi.fn(async () => ({
    getToken: vi.fn(async () => "clerk-token"),
    orgId: "org_1",
  })),
}));

describe("buyer-control-plane proxy helper", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "content-type": "application/json" } })),
    );
    process.env.VERIFUND_CONTROL_PLANE_URL = "http://cp.test";
  });

  it("forwards bearer auth and preserves path", async () => {
    const { controlPlaneBuyer } = await import("@/lib/buyer-control-plane");
    const res = await controlPlaneBuyer("/buyer/transactions/tx_1/inspection");
    expect(res.status).toBe(200);
    const [url, init] = (fetch as any).mock.calls[0];
    expect(url).toBe("http://cp.test/buyer/transactions/tx_1/inspection");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer clerk-token");
  });

  it("does not force content-type for FormData", async () => {
    const { controlPlaneBuyer } = await import("@/lib/buyer-control-plane");
    const fd = new FormData();
    fd.set("requirement_id", "req_1");
    await controlPlaneBuyer("/buyer/transactions/tx_1/evidence", { method: "POST", body: fd });
    const [, init] = (fetch as any).mock.calls[0];
    expect(new Headers(init.headers).get("content-type")).toBeNull();
  });
});
