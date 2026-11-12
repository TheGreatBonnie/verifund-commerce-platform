export const SELLER_IDS = [
  "northwind-audio",
  "circuitforge",
  "aurora-supply",
  "summit-tech",
] as const;

/** Remove trailing slashes so prefixes join cleanly. */
export function normalizeAgentBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

export function sellerAgentUrls(sharedBaseUrl: string): string[] {
  const base = normalizeAgentBaseUrl(sharedBaseUrl);
  return SELLER_IDS.map((sellerId) => `${base}/${sellerId}`);
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
