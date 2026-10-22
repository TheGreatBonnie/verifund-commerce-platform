import {
  CopilotRuntime,
  CopilotKitIntelligence,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { HttpAgent } from "@ag-ui/client";
import { A2AMiddlewareAgent } from "@ag-ui/a2a-middleware";
import { A2AClient } from "@a2a-js/sdk/client";
import { handle } from "hono/vercel";
import { createDefaultAgent } from "../../../agent";

// MarketMesh sellers expose A2A agent cards at their well-known card path.
// The installed A2A client defaults to the older `.well-known/agent.json`
// path, so use the 1.0 path explicitly.
class MarketMeshA2AClient extends (A2AClient as any) {
  constructor(baseUrl: string, token: string) {
    super(baseUrl, ".well-known/agent-card.json");
    this.token = token;
  }

  private token: string;

  async _fetchAndCacheAgentCard() {
    const self = this as any;
    const cardUrl = `${self.agentBaseUrl}/${self.agentCardPath}`;
    const response = await fetch(cardUrl, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(
        `Failed to fetch Agent Card from ${cardUrl}: ${response.status} ${response.statusText}`,
      );
    }
    const card = await response.json();
    const serviceUrl =
      card?.supportedInterfaces?.[0]?.url ??
      card?.supported_interfaces?.[0]?.url ??
      card?.url ??
      card?.endpoint;
    if (!serviceUrl) {
      throw new Error("Fetched Agent Card does not contain a valid service endpoint URL.");
    }
    self.serviceEndpointUrl = serviceUrl;
    return card;
  }

  async getAgentCard(baseUrl?: string, agentCardPath?: string) {
    return super.getAgentCard(baseUrl, agentCardPath);
  }

  async sendMessage(params: Parameters<A2AClient["sendMessage"]>[0]) {
    const originalFetch = globalThis.fetch;
    globalThis.fetch = async (input, init) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      if (url.includes("/a2a")) {
        init = {
          ...init,
          headers: {
            ...(init?.headers ?? {}),
            Authorization: `Bearer ${this.token}`,
          },
        };
      }
      return originalFetch(input, init);
    };
    try {
      return await super.sendMessage(params);
    } finally {
      globalThis.fetch = originalFetch;
    }
  }
}

// The middleware constructor only accepts URLs, so wrap it to use the
// MarketMesh card path and authenticated seller clients.
class MarketMeshA2AMiddlewareAgent extends A2AMiddlewareAgent {
  constructor(config: {
    description: string;
    agentUrls: string[];
    orchestrationAgent: HttpAgent;
    instructions: string;
    tokens: Map<string, string>;
  }) {
    super({
      description: config.description,
      agentUrls: [],
      orchestrationAgent: config.orchestrationAgent,
      instructions: config.instructions,
    });

    this.agentClients = config.agentUrls.map((url) => {
      const port = new URL(url).port;
      return new MarketMeshA2AClient(url, config.tokens.get(port) ?? "");
    }) as any;
    this.agentCards = Promise.all(
      this.agentClients.map((client) => client.getAgentCard()),
    );
  }
}

const sellerAgentUrls = [
  process.env.NORTHWIND_A2A_URL ?? "http://127.0.0.1:9201",
  process.env.CIRCUITFORGE_A2A_URL ?? "http://127.0.0.1:9202",
  process.env.AURORA_A2A_URL ?? "http://127.0.0.1:9203",
];

const sellerTokens = new Map<string, string>([
  ["9201", process.env.SELLER_NORTHWIND_TOKEN ?? "dev-northwind"],
  ["9202", process.env.SELLER_CIRCUITFORGE_TOKEN ?? "dev-circuitforge"],
  ["9203", process.env.SELLER_AURORA_TOKEN ?? "dev-aurora"],
]);

const orchestrationAgent = createDefaultAgent();

const a2aMiddlewareAgent = new MarketMeshA2AMiddlewareAgent({
  description:
    "MarketMesh buyer orchestrator with independent seller A2A agents: Northwind Audio, CircuitForge, and Aurora Supply.",
  agentUrls: sellerAgentUrls,
  orchestrationAgent,
  instructions:
    "Use send_message_to_a2a_agent to ask each seller for structured offers. Coordinate seller responses, then stop for human approval before any order.",
  tokens: sellerTokens,
});

const runtime = new CopilotRuntime({
  agents: {
    a2a_chat: a2aMiddlewareAgent,
  },
  // --- copilotkit:intelligence (remove this block to opt out) ---
  ...(process.env.CPK_INTELLIGENCE_API_KEY
    ? {
        intelligence: new CopilotKitIntelligence({
          apiKey: process.env.CPK_INTELLIGENCE_API_KEY,
          ...(process.env.INTELLIGENCE_API_URL
            ? { apiUrl: process.env.INTELLIGENCE_API_URL }
            : {}),
          ...(process.env.INTELLIGENCE_GATEWAY_WS_URL
            ? { wsUrl: process.env.INTELLIGENCE_GATEWAY_WS_URL }
            : {}),
        }),
        // Demo stub — replace with your real auth-derived user identity before any
        // multi-user deployment, or all users share one thread history. The id
        // must correspond to a user that exists in CopilotKit Intelligence;
        // an unknown id (like this literal) can make thread operations fail.
        identifyUser: () => ({ id: "demo-user", name: "Demo User" }),
      }
    : { runner: new InMemoryAgentRunner() }),
  // --- /copilotkit:intelligence ---
});

const handler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
});

export const GET = handler;
export const POST = handler;
export const PATCH = handler;
export const DELETE = handler;
