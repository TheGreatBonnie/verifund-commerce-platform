/** The path an A2A agent card is published under. */
export const AGENT_CARD_SUFFIX = "/.well-known/agent-card.json";

/** Remove trailing slashes so prefixes join cleanly. */
export function normalizeAgentBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

/** A seller agent the console can talk to over A2A. */
export type SellerAgent = {
  /** Base URL the A2A client appends `.well-known/agent-card.json` to. */
  url: string;
  /** Display name shown in the orchestrator's agent list. */
  name: string;
};

/** The subset of a registry seller row the console needs. */
export type RegistrySeller = {
  seller_id?: string;
  name?: string;
  /** The card URL the seller published to the registry when it onboarded. */
  card_url?: string;
};

/**
 * Derive the agent base URL from a published agent card URL.
 *
 * A seller publishes its card to the registry when it onboards, and the
 * registry stores that URL verbatim. The A2A client wants the base it
 * appends the card path to, so the card suffix is stripped.
 */
export function agentBaseUrlFromCardUrl(cardUrl: string): string | null {
  const trimmed = cardUrl.trim();
  if (!trimmed.endsWith(AGENT_CARD_SUFFIX)) {
    return null;
  }
  return trimmed.slice(0, -AGENT_CARD_SUFFIX.length) || null;
}

/**
 * Map the registry's seller rows to the agents the console can talk to.
 *
 * The registry is the only source of truth for where a seller lives: the
 * paths are created when the seller onboards. A seller that published no
 * card URL has no agent — its path is never guessed.
 */
export function registrySellerAgents(sellers: RegistrySeller[]): SellerAgent[] {
  const agents: SellerAgent[] = [];
  const seen = new Set<string>();
  for (const seller of sellers) {
    const url = seller.card_url
      ? agentBaseUrlFromCardUrl(seller.card_url)
      : null;
    if (!url || seen.has(url)) {
      continue;
    }
    seen.add(url);
    agents.push({ url, name: seller.name || seller.seller_id || url });
  }
  return agents;
}

function parseUrl(value: string): URL | null {
  try {
    return new URL(value);
  } catch {
    return null;
  }
}

/**
 * Decide whether an A2A URL belongs to the shared seller service.
 *
 * Behind the merged gateway every service shares one origin and port, so the
 * mount path is the only reliable discriminator. The legacy local stack has no
 * path prefix, so fall back to host/port matching there.
 */
export function isSellerAgentUrl(url: string, sharedBaseUrl: string): boolean {
  const base = normalizeAgentBaseUrl(sharedBaseUrl);
  if (url === base || url.startsWith(`${base}/`)) {
    return true;
  }

  const baseUrl = parseUrl(base);
  const target = parseUrl(url);

  if (!baseUrl || !target) {
    return false;
  }

  const hasPathPrefix = normalizeAgentBaseUrl(baseUrl.pathname) !== "";
  if (hasPathPrefix) {
    return false;
  }

  return baseUrl.hostname === target.hostname && baseUrl.port === target.port;
}
