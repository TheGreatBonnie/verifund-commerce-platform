import { beforeEach, describe, expect, it, vi } from "vitest";

const { getToken } = vi.hoisted(() => ({ getToken: vi.fn() }));
vi.mock("@clerk/nextjs/server", () => ({
  auth: vi.fn(async () => ({ getToken, orgId: "org_1" })),
}));

import {
  activateAgent,
  createAgent,
  getAgentCard,
  getAgentStatus,
  importCatalog,
  runAgentTests,
  saveConfig,
  savePolicies,
} from "@/lib/agent-api";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function lastCall() {
  const [url, init] = vi.mocked(fetch).mock.calls.at(-1)!;
  return { url: String(url), init: init!, headers: init?.headers as Headers };
}

describe("agent-api", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getToken.mockResolvedValue("tok_1");
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ ok: true })));
  });

  it("createAgent posts to /v1/agents with an idempotency key", async () => {
    await createAgent("Acme Seller");
    const { url, init, headers } = lastCall();
    expect(url).toMatch(/\/v1\/agents$/);
    expect(init.method).toBe("POST");
    expect(headers.get("idempotency-key")).toBeTruthy();
    expect(headers.get("authorization")).toBe("Bearer tok_1");
    expect(JSON.parse(String(init.body))).toEqual({ display_name: "Acme Seller" });
  });

  it("saveConfig patches the config endpoint", async () => {
    await saveConfig("agent_acme", { instructions: "be crisp", expected_config_version: 3 });
    const { url, init, headers } = lastCall();
    expect(url).toMatch(/\/v1\/agents\/agent_acme\/config$/);
    expect(init.method).toBe("PATCH");
    expect(headers.get("content-type")).toContain("application/json");
    expect(JSON.parse(String(init.body))).toEqual({
      instructions: "be crisp",
      expected_config_version: 3,
    });
  });

  it("savePolicies patches the policies endpoint", async () => {
    await savePolicies("agent_acme", { autonomy_mode: "policy_bounded", max_discount_bps: 1500 });
    const { url, init } = lastCall();
    expect(url).toMatch(/\/v1\/agents\/agent_acme\/policies$/);
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(String(init.body))).toEqual({
      autonomy_mode: "policy_bounded",
      max_discount_bps: 1500,
    });
  });

  it("importCatalog posts the document with replace flag", async () => {
    await importCatalog('{"version":1}', true);
    const { url, init } = lastCall();
    expect(url).toMatch(/\/v1\/seller\/catalog\/import$/);
    expect(JSON.parse(String(init.body))).toEqual({
      document: '{"version":1}',
      replace_catalog: true,
    });
  });

  it("runAgentTests posts to the test endpoint", async () => {
    await runAgentTests("agent_acme");
    const { url, init } = lastCall();
    expect(url).toMatch(/\/v1\/agents\/agent_acme\/test$/);
    expect(init.method).toBe("POST");
  });

  it("activateAgent posts to the activate endpoint", async () => {
    await activateAgent("agent_acme");
    const { url, init } = lastCall();
    expect(url).toMatch(/\/v1\/agents\/agent_acme\/activate$/);
    expect(init.method).toBe("POST");
  });

  it("getAgentStatus returns null on 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({}, 404)));
    await expect(getAgentStatus("agent_missing")).resolves.toBeNull();
  });

  it("getAgentCard projects the CP card envelope", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          card: { name: "Acme" },
          card_hash: "abc123",
          card_url: "https://agents.verifund.com/acme/.well-known/agent-card.json",
        }),
      ),
    );
    const card = await getAgentCard("agent_acme");
    expect(card.card_json).toEqual({ name: "Acme" });
    expect(card.card_hash).toBe("abc123");
    expect(card.card_url).toContain("acme");
  });

  it("maps CP error bodies to SellerApiError with status and code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          { error: { message: "no passing test run", code: "onboarding_incomplete" } },
          409,
        ),
      ),
    );
    await expect(activateAgent("agent_acme")).rejects.toMatchObject({
      status: 409,
      code: "onboarding_incomplete",
      message: "no passing test run",
    });
  });
});
