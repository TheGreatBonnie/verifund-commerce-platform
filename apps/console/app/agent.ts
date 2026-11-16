import { HttpAgent } from "@ag-ui/client";

/**
 * Normalise an AG-UI endpoint URL to the path the server actually serves.
 *
 * The orchestrator registers its agent endpoint at the root of its service
 * ("/"), and the merged gateway mounts that service under a prefix, so the
 * served path ends in a slash. Posting to the prefix without it makes
 * Starlette answer 307 and re-send the whole request body — on a 30 KB run
 * input that is a wasted round trip on every single call, and the redirect
 * follow is where the socket has been seen to reset.
 */
export function aguiEndpointUrl(url: string): string {
  const trimmed = url.trim();
  if (!trimmed) return trimmed;
  try {
    const parsed = new URL(trimmed);
    if (!parsed.pathname.endsWith("/")) {
      parsed.pathname = `${parsed.pathname}/`;
    }
    return parsed.toString();
  } catch {
    return trimmed;
  }
}

export function createDefaultAgent(): HttpAgent {
  return new HttpAgent({
    url: aguiEndpointUrl(
      process.env.ORCHESTRATOR_AGUI_URL ?? "http://127.0.0.1:9000",
    ),
  });
}
