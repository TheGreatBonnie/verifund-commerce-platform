import { A2AMiddlewareAgent } from "@ag-ui/a2a-middleware";
import type { RunAgentInput } from "@ag-ui/core";
import { HttpAgent } from "@ag-ui/client";
import { A2AClient } from "@a2a-js/sdk/client";

import {
  normalizeAgentBaseUrl,
  registrySellerAgents,
  type RegistrySeller,
  type SellerAgent,
} from "@/lib/a2a-agents";
import { singleTerminalStream } from "@/lib/single-terminal-stream";

/**
 * MarketMesh sellers expose A2A agent cards at their well-known card path.
 * The installed A2A client defaults to the older `.well-known/agent.json`
 * path, so use the 1.0 path explicitly.
 */
export class MarketMeshA2AClient extends (A2AClient as any) {
  public readonly baseUrl: string;

  constructor(baseUrl: string) {
    super(baseUrl, ".well-known/agent-card.json");
    this.baseUrl = baseUrl;

    // The SDK starts the card fetch in its constructor and keeps the promise.
    // If nothing awaits it and it rejects, Node reports an unhandled
    // rejection and terminates the process — on a serverless platform that
    // kills the in-flight request. Attach a handler unconditionally; callers
    // that await getAgentCard() still observe the rejection themselves.
    const pending = (this as any).agentCardPromise as
      | Promise<unknown>
      | undefined;
    pending?.catch(() => {});
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

/**
 * Whether the process is running as part of a production build.
 *
 * Only a real build phase counts: at runtime (a serverless function, or
 * `next start`) the agent services are reachable and the real cards should
 * be used.
 */
export function isBuildPhase(
  env: Record<string, string | undefined> = process.env,
): boolean {
  return (
    env.NEXT_PHASE === "phase-production-build" ||
    env.NEXT_BUILD_PHASE === "build"
  );
}

/**
 * Resolve the seller agents the console can talk to.
 *
 * Sellers publish their agent card to the registry when they onboard, so the
 * registry is the only source of truth for where a seller lives. When the
 * registry lists no sellers there are none to talk to — inventing paths for
 * sellers that were never created only produces failed lookups.
 */
export async function resolveSellerAgentUrls(options: {
  registryUrl?: string;
  fetchImpl?: typeof fetch;
}): Promise<SellerAgent[]> {
  const registryUrl = options.registryUrl?.replace(/\/+$/, "");
  if (!registryUrl) {
    return [];
  }
  const fetchImpl = options.fetchImpl ?? fetch;
  try {
    const response = await fetchImpl(`${registryUrl}/v1/sellers`, {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      return [];
    }
    const data = (await response.json()) as { sellers?: RegistrySeller[] };
    return registrySellerAgents(data.sellers ?? []);
  } catch (error) {
    console.warn("Failed to resolve seller agents from registry:", error);
    return [];
  }
}

/**
 * The middleware agent wraps the orchestrator with direct A2A access to the
 * buyer and every seller the registry knows about.
 *
 * An agent only exists if it published an agent card. Nothing is invented:
 * a card that cannot be fetched means the agent is simply not available, so
 * it is dropped rather than replaced by a stand-in whose path was never
 * created.
 */
export class MarketMeshA2AMiddlewareAgent extends A2AMiddlewareAgent {
  constructor(config: {
    agentName: string;
    description: string;
    agents: SellerAgent[];
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

    if (isBuildPhase()) {
      // Agent services aren't reachable while the app is being built, and a
      // card must never be fabricated, so no agents are registered.
      this.agentClients = [] as any;
      this.agentCards = Promise.resolve([] as any);
      return;
    }

    const clients = config.agents.map(
      (agent) => new MarketMeshA2AClient(agent.url),
    );
    this.agentClients = clients as any;

    this.agentCards = Promise.all(
      clients.map(async (client, index) => {
        try {
          return { client, card: await client.getAgentCard() };
        } catch (error) {
          console.warn(
            `Failed to fetch agent card for ${config.agents[index].url}:`,
            error,
          );
          return null;
        }
      }),
    ).then((results) => {
      const available = results.filter(
        (result): result is { client: MarketMeshA2AClient; card: any } =>
          result !== null,
      );
      // The base class pairs cards with clients by index, so both lists are
      // narrowed to the agents that are actually available.
      this.agentClients = available.map((result) => result.client) as any;
      return available.map((result) => result.card);
    });
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
