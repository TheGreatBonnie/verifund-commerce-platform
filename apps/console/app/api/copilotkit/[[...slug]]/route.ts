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

// Force dynamic rendering for the API route to avoid build-time fetching
export const dynamic = 'force-dynamic';
export const revalidate = 0;

// MarketMesh sellers expose A2A agent cards at their well-known card path.
// The installed A2A client defaults to the older `.well-known/agent.json`
// path, so use the 1.0 path explicitly.
class MarketMeshA2AClient extends (A2AClient as any) {
  public readonly baseUrl: string;
  constructor(baseUrl: string) {
    super(baseUrl, ".well-known/agent-card.json");
    this.baseUrl = baseUrl;
  }

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
      return new MarketMeshA2AClient(url);
    }) as any;

    // During build time (static generation), agent services aren't running.
    // Skip fetching agent cards during build to avoid ECONNREFUSED errors.
    // Agent cards will be fetched lazily at runtime when needed.
    const isBuildTime = 
      process.env.NEXT_PHASE === 'phase-production-build' || 
      process.env.NEXT_PHASE === 'phase-production-server' ||
      process.env.NODE_ENV === 'production' && typeof window === 'undefined' ||
      process.env.NEXT_BUILD_PHASE === 'build';

    if (isBuildTime) {
      // Provide minimal fallback agent cards for build-time static generation
      this.agentCards = Promise.resolve(
        config.agentUrls.map((url) => {
          const port = new URL(url).port;
          const name = port === '9100' ? 'MarketMesh Buyer' :
                       port === '9201' ? 'Northwind Audio' :
                       port === '9202' ? 'CircuitForge' :
                       port === '9203' ? 'Aurora Supply' :
                       port === '9204' ? 'Summit Tech Supply' : `Agent ${port}`;
          return {
            name,
            description: `${name} A2A agent`,
            version: '1.0.0',
            provider: { organization: name, url },
            supportedInterfaces: [{
              url: `${url}/a2a`,
              protocolBinding: 'JSONRPC',
              protocolVersion: '1.0',
            }],
            capabilities: { streaming: true, pushNotifications: false },
            defaultInputModes: ['application/json', 'text/plain'],
            defaultOutputModes: ['application/json'],
            skills: [],
          } as any;
        })
      );
    } else {
      // Runtime: fetch agent cards with graceful error handling
      this.agentCards = Promise.all(
        this.agentClients.map(async (client) => {
          const baseUrl = (client as unknown as MarketMeshA2AClient).baseUrl;
          try {
            return await client.getAgentCard();
          } catch (error) {
            console.warn(`Failed to fetch agent card for ${baseUrl}:`, error);
            // Return minimal fallback
            const port = new URL(baseUrl).port;
            const name = port === '9100' ? 'MarketMesh Buyer' :
                         port === '9201' ? 'Northwind Audio' :
                         port === '9202' ? 'CircuitForge' :
                         port === '9203' ? 'Aurora Supply' :
                         port === '9204' ? 'Summit Tech Supply' : `Agent ${port}`;
            return {
              name,
              description: `${name} A2A agent (offline)`,
              version: '1.0.0',
              provider: { organization: name, url: baseUrl },
              supportedInterfaces: [{
                url: `${baseUrl}/a2a`,
                protocolBinding: 'JSONRPC',
                protocolVersion: '1.0',
              }],
              capabilities: { streaming: true, pushNotifications: false },
              defaultInputModes: ['application/json', 'text/plain'],
              defaultOutputModes: ['application/json'],
              skills: [],
            } as any;
          }
        })
      );
    }
  }
}

const buyerAgentUrl =
  process.env.BUYER_A2A_URL ?? "http://127.0.0.1:9100";

const sellerAgentUrls = [
  process.env.NORTHWIND_A2A_URL ?? "http://127.0.0.1:9201",
  process.env.CIRCUITFORGE_A2A_URL ?? "http://127.0.0.1:9202",
  process.env.AURORA_A2A_URL ?? "http://127.0.0.1:9203",
  process.env.SUMMIT_TECH_A2A_URL ?? "http://127.0.0.1:9204",
];

const a2aAgentUrls = [buyerAgentUrl, ...sellerAgentUrls];

const sellerTokens = new Map<string, string>([
  ["9201", process.env.SELLER_NORTHWIND_TOKEN ?? "dev-northwind"],
  ["9202", process.env.SELLER_CIRCUITFORGE_TOKEN ?? "dev-circuitforge"],
  ["9203", process.env.SELLER_AURORA_TOKEN ?? "dev-aurora"],
  ["9204", process.env.SELLER_SUMMIT_TECH_TOKEN ?? "dev-summit-tech"],
]);

// The @a2a-js/sdk uses the global `fetch` and has no per-client header hook.
// Patching `globalThis.fetch` per call (inside sendMessage) is racy when several
// seller calls overlap, which intermittently drops the Authorization header and
// makes a seller's bearer-auth middleware return 401. Install a single,
// concurrency-safe wrapper once at module load instead: headers are derived
// from the request URL, so overlapping calls never clobber each other.
const marketmeshGlobalFetch = globalThis.fetch;
if (!(globalThis as { __marketmeshA2aFetchPatched?: boolean }).__marketmeshA2aFetchPatched) {
  globalThis.fetch = async (input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    if (url.includes("/a2a")) {
      const port = new URL(url).port;
      const token = sellerTokens.get(port) ?? "";
      const headers = new Headers(init?.headers);
      // @a2a-js/sdk 0.2.x speaks A2A 0.3 (lowercase JSON-RPC methods), so
      // use the server's v0.3 compatibility adapter.
      headers.set("A2A-Version", "0.3");
      if (token) {
        headers.set("Authorization", `Bearer ${token}`);
      }
      init = { ...init, headers };
    }
    return marketmeshGlobalFetch(input, init);
  };
  (globalThis as { __marketmeshA2aFetchPatched?: boolean }).__marketmeshA2aFetchPatched = true;
}

const orchestrationAgent = createDefaultAgent();

const a2aMiddlewareAgent = new MarketMeshA2AMiddlewareAgent({
  description:
    "MarketMesh orchestrator with the buyer as commerce authority and independent seller A2A agents.",
  agentUrls: a2aAgentUrls,
  orchestrationAgent,
  instructions:
    "Use MarketMesh Buyer for sourcing, negotiation, ranking, and approval. " +
    "All seller calls are orchestrator-mediated: when the Buyer pauses with a " +
    "seller_call_required response, call mediate_seller_call with buyer_task_id " +
    "from task_id, seller_card_url from card_url, seller_request from request, " +
    "and seller identifiers when present. " +
    "That tool calls the seller and resumes the same Buyer checkpoint. " +
    "Inspect its buyer_response to decide the next step: mediate another " +
    "seller_call_required response, call request_award_approval for an " +
    "approval_required response, or report a completed result. " +
    "For approval_required, call request_award_approval with the exact task_id, " +
    "message, award, and mandate from the Buyer response. " +
    "Do not ask for approval as plain chat text. " +
    "After request_award_approval returns, send the Buyer one message whose " +
    "content is the JSON object {\\\"approval\\\":{\\\"approved\\\":<decision.approved>," +
    "\\\"approved_by\\\":\\\"Demo Buyer\\\",\\\"note\\\":<decision.note>}," +
    "\\\"task_id\\\":<decision.task_id>}. " +
    "Do not place an order or continue without that tool response. " +
    "Do not send a separate Buyer message to continue sourcing after mediation. " +
    "Seller agents may be queried directly for catalog/status only; never place " +
    "orders with sellers directly. " +
    "Stop for human approval before any order.",
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
