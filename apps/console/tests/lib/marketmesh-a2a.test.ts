import { afterEach, describe, expect, it, vi } from "vitest";
import {
  MarketMeshA2AClient,
  MarketMeshA2AMiddlewareAgent,
  isBuildPhase,
  resolveSellerAgentUrls,
} from "@/lib/marketmesh-a2a";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function failedCardFetch() {
  return vi.fn(async () => ({
    ok: false,
    status: 404,
    statusText: "Not Found",
    json: async () => ({}),
  })) as unknown as typeof fetch;
}

describe("MarketMeshA2AClient", () => {
  it("rejects when the agent card cannot be fetched", async () => {
    globalThis.fetch = failedCardFetch();

    const client = new MarketMeshA2AClient(
      "https://gw.example.com/sellers/missing",
    );

    await expect(client.getAgentCard()).rejects.toThrow(/404/);
  });

  it("does not raise an unhandled rejection when the agent card fetch fails", async () => {
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", onUnhandled);
    globalThis.fetch = failedCardFetch();

    try {
      const client = new MarketMeshA2AClient(
        "https://gw.example.com/sellers/missing",
      );
      // Let the constructor-issued fetch settle before asserting.
      await new Promise((resolve) => setTimeout(resolve, 20));
      await expect(client.getAgentCard()).rejects.toThrow(/404/);
      await new Promise((resolve) => setTimeout(resolve, 20));
    } finally {
      process.off("unhandledRejection", onUnhandled);
    }

    expect(unhandled).toEqual([]);
  });

  it("uses the card's advertised interface as the service endpoint", async () => {
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({
        name: "Northwind Audio",
        supportedInterfaces: [
          { url: "https://gw.example.com/sellers/northwind-audio/a2a" },
        ],
      }),
    })) as unknown as typeof fetch;

    const client = new MarketMeshA2AClient(
      "https://gw.example.com/sellers/northwind-audio",
    );
    await client.getAgentCard();

    expect((client as unknown as { serviceEndpointUrl?: string }).serviceEndpointUrl).toBe(
      "https://gw.example.com/sellers/northwind-audio/a2a",
    );
  });
});

describe("MarketMeshA2AMiddlewareAgent", () => {
  it("does not raise an unhandled rejection when an agent card is unavailable", async () => {
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", onUnhandled);
    globalThis.fetch = failedCardFetch();

    try {
      new MarketMeshA2AMiddlewareAgent({
        agentName: "marketmesh_orchestrator",
        description: "test orchestrator",
        agents: [
          { url: "https://gw.example.com/sellers/missing", name: "Missing" },
        ],
        orchestrationAgent: {} as never,
        instructions: "",
        tokens: new Map(),
      });
      // Let the constructor-issued card fetch settle.
      await new Promise((resolve) => setTimeout(resolve, 20));
      await new Promise((resolve) => setTimeout(resolve, 20));
    } finally {
      process.off("unhandledRejection", onUnhandled);
    }

    expect(unhandled).toEqual([]);
  });

  it("does not raise an unhandled rejection when an agent card is unavailable during a build phase", async () => {
    // The build-phase branch never awaits the card fetch, so the SDK's
    // constructor-issued promise is the only thing that could surface the
    // failure. This is the path the deployed console used to take.
    const unhandled: unknown[] = [];
    const onUnhandled = (reason: unknown) => {
      unhandled.push(reason);
    };
    process.on("unhandledRejection", onUnhandled);
    globalThis.fetch = failedCardFetch();
    const previousPhase = process.env.NEXT_PHASE;
    process.env.NEXT_PHASE = "phase-production-build";

    try {
      new MarketMeshA2AMiddlewareAgent({
        agentName: "marketmesh_orchestrator",
        description: "test orchestrator",
        agents: [
          { url: "https://gw.example.com/sellers/missing", name: "Missing" },
        ],
        orchestrationAgent: {} as never,
        instructions: "",
        tokens: new Map(),
      });
      // Let the constructor-issued card fetch settle.
      await new Promise((resolve) => setTimeout(resolve, 20));
      await new Promise((resolve) => setTimeout(resolve, 20));
    } finally {
      if (previousPhase === undefined) {
        delete process.env.NEXT_PHASE;
      } else {
        process.env.NEXT_PHASE = previousPhase;
      }
      process.off("unhandledRejection", onUnhandled);
    }

    expect(unhandled).toEqual([]);
  });

  it("drops an agent whose agent card cannot be fetched", async () => {
    globalThis.fetch = failedCardFetch();

    const agent = new MarketMeshA2AMiddlewareAgent({
      agentName: "marketmesh_orchestrator",
      description: "test orchestrator",
      agents: [
        { url: "https://gw.example.com/sellers/missing", name: "Missing" },
      ],
      orchestrationAgent: {} as never,
      instructions: "",
      tokens: new Map(),
    });
    const state = agent as unknown as {
      agentCards: Promise<Array<{ name: string }>>;
      agentClients: unknown[];
    };
    const cards = await state.agentCards;

    // No stand-in card is invented for an agent that never published one.
    expect(cards).toEqual([]);
    expect(state.agentClients).toEqual([]);
  });

  it("keeps only the agents whose cards are available", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/sellers/broken")) {
        return {
          ok: false,
          status: 404,
          statusText: "Not Found",
          json: async () => ({}),
        };
      }
      return {
        ok: true,
        status: 200,
        statusText: "OK",
        json: async () => ({
          name: "Northwind Audio",
          supportedInterfaces: [
            { url: "https://gw.example.com/sellers/northwind-audio/a2a" },
          ],
        }),
      };
    }) as unknown as typeof fetch;

    const agent = new MarketMeshA2AMiddlewareAgent({
      agentName: "marketmesh_orchestrator",
      description: "test orchestrator",
      agents: [
        { url: "https://gw.example.com/sellers/broken", name: "Broken" },
        {
          url: "https://gw.example.com/sellers/northwind-audio",
          name: "Northwind Audio",
        },
      ],
      orchestrationAgent: {} as never,
      instructions: "",
      tokens: new Map(),
    });
    const state = agent as unknown as {
      agentCards: Promise<Array<{ name: string }>>;
      agentClients: unknown[];
    };
    const cards = await state.agentCards;

    expect(cards.map((card) => card.name)).toEqual(["Northwind Audio"]);
    // The client list stays index-aligned with the cards.
    expect(state.agentClients).toHaveLength(1);
  });
});

describe("isBuildPhase", () => {
  it("treats the production build phase as build time", () => {
    expect(isBuildPhase({ NEXT_PHASE: "phase-production-build" })).toBe(true);
    expect(isBuildPhase({ NEXT_BUILD_PHASE: "build" })).toBe(true);
  });

  it("treats a production server runtime as runtime, not build time", () => {
    expect(isBuildPhase({ NEXT_PHASE: "phase-production-server" })).toBe(false);
    expect(isBuildPhase({ NODE_ENV: "production" })).toBe(false);
    expect(isBuildPhase({})).toBe(false);
  });
});

describe("resolveSellerAgentUrls", () => {
  it("resolves sellers from the registry's published card URLs", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        sellers: [
          {
            seller_id: "northwind-audio",
            name: "Northwind Audio",
            card_url:
              "https://agents.example.com/sellers/northwind-audio/.well-known/agent-card.json",
          },
        ],
      }),
    })) as unknown as typeof fetch;

    await expect(
      resolveSellerAgentUrls({
        registryUrl: "https://gw.example.com/registry",
        fetchImpl,
      }),
    ).resolves.toEqual([
      {
        url: "https://agents.example.com/sellers/northwind-audio",
        name: "Northwind Audio",
      },
    ]);
  });

  it("returns no seller agents when the registry has no sellers", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => ({ sellers: [] }),
    })) as unknown as typeof fetch;

    await expect(
      resolveSellerAgentUrls({
        registryUrl: "https://gw.example.com/registry",
        fetchImpl,
      }),
    ).resolves.toEqual([]);
  });

  it("returns no seller agents when the registry is unreachable", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new Error("registry offline");
    }) as unknown as typeof fetch;

    await expect(
      resolveSellerAgentUrls({
        registryUrl: "https://gw.example.com/registry",
        fetchImpl,
      }),
    ).resolves.toEqual([]);
  });
});
