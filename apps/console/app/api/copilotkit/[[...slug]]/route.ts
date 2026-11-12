import {
  CopilotRuntime,
  CopilotKitIntelligence,
  createCopilotRuntimeHandler,
  InMemoryAgentRunner,
} from "@copilotkit/runtime/v2";
import { HttpAgent } from "@ag-ui/client";
import { A2AMiddlewareAgent } from "@ag-ui/a2a-middleware";
import type { RunAgentInput } from "@ag-ui/core";
import { A2AClient } from "@a2a-js/sdk/client";
import { handle } from "hono/vercel";
import { createDefaultAgent } from "../../../agent";
import { auth } from "@clerk/nextjs/server";
import { singleTerminalStream } from "@/lib/single-terminal-stream";
import { identifyCopilotUser } from "@/lib/copilot-user";

// Force dynamic rendering for the API route to avoid build-time fetching
export const dynamic = "force-dynamic";
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
      throw new Error(
        "Fetched Agent Card does not contain a valid service endpoint URL.",
      );
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
    agentName: string;
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
      process.env.NEXT_PHASE === "phase-production-build" ||
      process.env.NEXT_PHASE === "phase-production-server" ||
      (process.env.NODE_ENV === "production" &&
        typeof window === "undefined") ||
      process.env.NEXT_BUILD_PHASE === "build";

    if (isBuildTime) {
      // Provide minimal fallback agent cards for build-time static generation
      this.agentCards = Promise.resolve(
        config.agentUrls.map((url) => {
          const port = new URL(url).port;
          const name =
            port === "9100"
              ? "MarketMesh Buyer"
              : port === "9201"
                ? "Northwind Audio"
                : port === "9202"
                  ? "CircuitForge"
                  : port === "9203"
                    ? "Aurora Supply"
                    : port === "9204"
                      ? "Summit Tech Supply"
                      : `Agent ${port}`;
          return {
            name,
            description: `${name} A2A agent`,
            version: "1.0.0",
            provider: { organization: name, url },
            supportedInterfaces: [
              {
                url: `${url}/a2a`,
                protocolBinding: "JSONRPC",
                protocolVersion: "1.0",
              },
            ],
            capabilities: { streaming: true, pushNotifications: false },
            defaultInputModes: ["application/json", "text/plain"],
            defaultOutputModes: ["application/json"],
            skills: [],
          } as any;
        }),
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
            const name =
              port === "9100"
                ? "MarketMesh Buyer"
                : port === "9201"
                  ? "Northwind Audio"
                  : port === "9202"
                    ? "CircuitForge"
                    : port === "9203"
                      ? "Aurora Supply"
                      : port === "9204"
                        ? "Summit Tech Supply"
                        : `Agent ${port}`;
            return {
              name,
              description: `${name} A2A agent (offline)`,
              version: "1.0.0",
              provider: { organization: name, url: baseUrl },
              supportedInterfaces: [
                {
                  url: `${baseUrl}/a2a`,
                  protocolBinding: "JSONRPC",
                  protocolVersion: "1.0",
                },
              ],
              capabilities: { streaming: true, pushNotifications: false },
              defaultInputModes: ["application/json", "text/plain"],
              defaultOutputModes: ["application/json"],
              skills: [],
            } as any;
          }
        }),
      );
    }
  }

  // A2AMiddlewareAgent starts a new orchestration sub-run after each A2A tool
  // call while keeping the original run id, so downstream consumers receive
  // duplicate RUN_STARTED/RUN_FINISHED pairs for one logical run. CopilotKit
  // Intelligence rejects the second terminal event as
  // `terminal_event_already_received` and aborts the run, so normalize the
  // stream to a single start and a single terminal event.
  run(input: RunAgentInput) {
    return singleTerminalStream(super.run(input));
  }
}

const buyerAgentUrl = process.env.BUYER_A2A_URL ?? "http://127.0.0.1:9100";
const sharedSellerBaseUrl = process.env.SELLER_SHARED_URL ?? "http://127.0.0.1:9200";
const sellerAgentToken =
  process.env.BUYER_AGENT_TOKEN ??
  process.env.SELLER_NORTHWIND_TOKEN ??
  "dev-buyer-agent";

const sellerAgentUrls = [
  `${sharedSellerBaseUrl}/northwind-audio`,
  `${sharedSellerBaseUrl}/circuitforge`,
  `${sharedSellerBaseUrl}/aurora-supply`,
  `${sharedSellerBaseUrl}/summit-tech`,
];

const a2aAgentUrls = [buyerAgentUrl, ...sellerAgentUrls];

const sharedSellerPort = new URL(sharedSellerBaseUrl).port || "9200";
const sellerTokens = new Map<string, string>([
  [sharedSellerPort, sellerAgentToken],
]);

// The @a2a-js/sdk uses the global `fetch` and has no per-client header hook.
// Patching `globalThis.fetch` per call (inside sendMessage) is racy when several
// seller calls overlap, which intermittently drops the Authorization header and
// makes a seller's bearer-auth middleware return 401. Install a single,
// concurrency-safe wrapper once at module load instead: headers are derived
// from the request URL, so overlapping calls never clobber each other.
const marketmeshGlobalFetch = globalThis.fetch;
if (
  !(globalThis as { __marketmeshA2aFetchPatched?: boolean })
    .__marketmeshA2aFetchPatched
) {
  globalThis.fetch = async (input, init) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
    if (url.includes("/a2a")) {
      const port = new URL(url).port;
      const sharedPort = new URL(sharedSellerBaseUrl).port;
      const token = port === sharedPort ? sellerAgentToken : "";
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
  (
    globalThis as { __marketmeshA2aFetchPatched?: boolean }
  ).__marketmeshA2aFetchPatched = true;
}

const orchestrationAgent = createDefaultAgent();

// NOTE: ag_ui_adk appends this instruction after the ADK
// MARKETMESH_ORCHESTRATOR_INSTRUCTION. Keep the discovery and handoff rules
// aligned with apps/orchestrator_agent/orchestrator_agent/agent.py.
const a2aMiddlewareAgent = new MarketMeshA2AMiddlewareAgent({
  agentName: "marketmesh_orchestrator",
  description:
    "MarketMesh orchestrator with the buyer as commerce authority and independent seller A2A agents.",
  agentUrls: a2aAgentUrls,
  orchestrationAgent,
  instructions: `
  # 1. Role and Mission

  You are the MarketMesh orchestrator.

  Coordinate the MarketMesh purchasing workflow by communicating
  with the Buyer A2A agent, mediating seller calls, coordinating
  human award approval, and reporting verified outcomes.

  # 2. Authority and Non-Negotiable Rules

  - The Buyer A2A agent owns sourcing, negotiation, ranking,
    and award decisions.
  - Seller agents may be queried for status, but sourcing and
    award authority remain with the Buyer.
  - Never reveal or estimate the Buyer's budget.
  - Never alter the Buyer's task_id or award data.
  - Never place an order before the Buyer confirms that the
    required approval has been granted.
  - Never request award approval through plain chat text.
  - Never call sellers directly. Use mediate_seller_call
    to handle Buyer seller_call pauses.
  - Call agents sequentially. Wait for each result before
    proceeding to the next operation.

  # 3. Buyer Interaction

  Use the MarketMesh Buyer A2A agent for sourcing,
  negotiation, ranking, and award decisions.

  Inspect every structured Buyer response before choosing
  the next action.

  Do not send a separate Buyer message to continue sourcing
  after mediate_seller_call has already resumed the
  Buyer's checkpoint.

  # 4. Seller Mediation Protocol

  When the Buyer returns a seller_call pause, call
  mediate_seller_call with the following mappings:

  - buyer_task_id = task_id
  - seller_card_url = card_url
  - seller_request = request
  - seller_id = seller_id, when present
  - seller_task_id = seller_task_id, when present
  - seller_context_id = seller_context_id, when present

  The configured Buyer URL is supplied internally.
  Do not pass seller_token; it is resolved automatically.

  After mediation, inspect buyer_response and follow its
  current status. Do not assume that the seller response
  means the overall purchasing workflow is complete.

  If buyer_response requests another seller call, mediate
  that pause using the same procedure.

  # 5. Product Discovery and Negotiation Handoff

  Use search_marketplace_products only for discovery requests
  (find, search, browse). Extract constraints: "under $1500"
  becomes max_unit_price_cents=150000, a per-unit ceiling.
  Set in_stock_only=true for items available now.

  Search is semantic; describe the intent in natural language.
  Put the request in query, use use_case for the intended
  use, and preferences for stated preferences. Do not reduce
  the query to a single keyword.

  These are the hard filters: category, max_unit_price_cents,
  and in_stock_only. use_case and preferences
  influence ranking only; never claim a preference was
  guaranteed. Pass category only when it exactly matches a
  category already shown in a tool result; never guess it.
  Never route discovery to send_message_to_a2a_agent or a
  seller.

  Present only returned products and SKUs. Use
  match_rationale to explain why an item matched in plain
  language; never quote raw similarity scores, the embedding
  model, the cutoff, or latency.

  When the tool returns an empty products list, say that
  no matches were found, do not invent products, and offer
  to broaden the query or raise the price ceiling. Never
  route an empty discovery result to the Buyer.

  When the user asks to negotiate for a shown card, read its
  SKU, name, price, and offers from the message; do not
  re-search unless constraints changed.

  Confirm the mandate before sourcing. Ask only for missing or
  ambiguous fields: quantity (default 1), budget ceiling or
  target, delivery deadline, warranty and returns, must-haves.
  Never re-ask a stated field; a complete brief starts without
  extra questions.

  At the sourcing pause (product context grounded, before any
  Buyer handoff), call the frontend request_sourcing_mandate
  HITL tool with the locked product and known offers as
  read-only context plus any known defaults/hints and task_id.
  Do not edit the product/offer selection in this step and do
  not collect these fields via plain chat when the tool is
  required. Wait for the tool result.

  - If the result is confirmed === true with a complete
    mandate: call send_message_to_a2a_agent with
    agentName="MarketMesh Buyer" and a task containing the
    confirmed mandate plus the grounded product context (SKU,
    name, unit price, offers). Stay in the current thread; do
    not navigate, do not place an order, and do not create an
    award outcome. request_award_approval and Verifund HITL
    approvals remain mandatory. Do not place an order.
  - If the result is confirmed === false or reason is
    "user_cancelled": stop the handoff and report that the
    mandate was not confirmed, no sourcing/negotiation started,
    and no order will be placed. Do not contact the Buyer.

  Never infer confirmation without the tool result.

  # 6. Human Award Approval Protocol

  When the Buyer returns status approval_required:

  1. Extract the exact task_id, message, award, and mandate
    from the Buyer response.
  2. Call the frontend request_award_approval tool with
    those exact values.
  3. Do not ask for approval through plain chat text.
  4. Wait for the actual tool result before continuing.
  5. Proceed only when the returned decision explicitly
    confirms approval.

  After approval, send the Buyer exactly this JSON payload,
  with the approval decision nested under "approval" and the
  original task_id at the top level:

  {"approval": {"approved": true, "approved_by": "<approved_by>", "note": "<note>"}, "task_id": "<task_id>"}

  Do not lift approved/approved_by/note to the top level, do
  not rename "approval", and do not wrap the payload in prose.
  The Buyer treats any message without the nested "approval"
  key as a new sourcing brief, which starts a new run instead
  of resuming the approved one.

  Preserve the returned values exactly. Never substitute
  a task ID, modify award data, or infer approval.

  If the Buyer rejects the approval payload (for example,
  "approval response requires task_id"), do not retry by
  re-sending the brief or starting a new run. Report the
  structured error and escalate instead.

  If the approval response is missing required fields,
  contains inconsistent identifiers, or does not clearly
  confirm approval, do not resume the Buyer as approved.
  Report or escalate the unresolved condition.

  If the decision is rejected or otherwise not approved,
  do not proceed with the award. Follow the supported
  workflow for that decision; do not invent a new status.

  # 7. Result and Error Handling

  - If the Buyer or mediation result indicates complete,
    report the verified result.
  - If the Buyer requests another seller call, mediate it.
  - If the Buyer returns approval_required, follow the
    approval protocol above.
  - If search_marketplace_products returns
    retrieval_unavailable, report that product search is
    temporarily unavailable. Do not guess products, do not
    fall back to a seller, and do not route the discovery
    request to the Buyer.
  - If search_marketplace_products returns
    marketplace_unavailable, report that the marketplace
    catalog is unavailable and suggest retrying.
  - When reporting a failure, preserve the exact structured
    error returned by the Buyer or seller.
  - Do not infer offer expiration unless the structured
    error explicitly identifies offer expiration.
  - Do not claim the user was charged or was not charged
    unless the system response confirms it.
  - If a response has an unknown status or lacks required
    fields, do not invent a successful outcome. Report the
    uncertainty and use the supported recovery procedure.

  # 8. Final Response

  Report outcomes based on confirmed system responses.
  Distinguish completed purchases from pending approvals,
  failed operations, and unresolved states.

  Never claim that an approval, order, or payment succeeded
  unless the corresponding system result confirms it.`,
  tokens: sellerTokens,
});

const runtime = new CopilotRuntime({
  agents: {
    marketmesh_orchestrator: a2aMiddlewareAgent,
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
        identifyUser: identifyCopilotUser,
      }
    : { runner: new InMemoryAgentRunner() }),
  // --- /copilotkit:intelligence ---
});

const handler = createCopilotRuntimeHandler({
  runtime,
  basePath: "/api/copilotkit",
});

export async function GET(request: Request) {
  await auth.protect();
  return handler(request);
}

export async function POST(request: Request) {
  await auth.protect();
  return handler(request);
}

export async function PATCH(request: Request) {
  await auth.protect();
  return handler(request);
}

export async function DELETE(request: Request) {
  await auth.protect();
  return handler(request);
}
