import { NextResponse } from "next/server";

const BUYER = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
const CONSOLE_TOKEN =
  process.env.BUYER_CONSOLE_API_TOKEN ?? "dev-console";
const INTERNAL_TOKEN = process.env.BUYER_INTERNAL_TOKEN ?? "";

/**
 * Internal service-auth boundary between the console server (Clerk-protected)
 * and the buyer agent. User auth is verified at the console route
 * (`auth.protect()` + `consoleSession()` org) before proxying; this token is
 * the server-to-server credential, not a user token. Organization scoping is
 * enforced in the buyer agent when `organization_id` is supplied.
 */
function headers(extra?: HeadersInit, organizationId?: string | null): Headers {
  const value = new Headers(extra);
  value.set("x-marketmesh-console-token", CONSOLE_TOKEN);
  if (INTERNAL_TOKEN) {
    value.set("x-verifund-internal-token", INTERNAL_TOKEN);
  }
  if (organizationId) {
    value.set("x-buyer-organization-id", organizationId);
  }
  return value;
}

function withOrg(path: string, organizationId?: string | null): string {
  if (!organizationId) return path;
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}organization_id=${encodeURIComponent(organizationId)}`;
}

export async function buyerJson(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10_000,
  organizationId?: string | null,
): Promise<Response> {
  try {
    const response = await fetch(`${BUYER}${withOrg(path, organizationId)}`, {
      ...init,
      cache: "no-store",
      headers: headers(init.headers, organizationId),
      signal: AbortSignal.timeout(timeoutMs),
    });
    const contentType =
      response.headers.get("content-type") ?? "application/json";
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": contentType },
    });
  } catch {
    return NextResponse.json(
      { error: "Buyer API is unavailable" },
      { status: 503 },
    );
  }
}

export async function buyerBinary(
  path: string,
  timeoutMs = 10_000,
  organizationId?: string | null,
): Promise<Response> {
  try {
    const response = await fetch(`${BUYER}${withOrg(path, organizationId)}`, {
      cache: "no-store",
      headers: headers(undefined, organizationId),
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!response.ok) {
      return new Response(await response.text(), {
        status: response.status,
        headers: {
          "content-type":
            response.headers.get("content-type") ?? "application/json",
        },
      });
    }
    const output = new Headers();
    output.set(
      "content-type",
      response.headers.get("content-type") ?? "application/octet-stream",
    );
    const disposition = response.headers.get("content-disposition");
    if (disposition) output.set("content-disposition", disposition);
    return new Response(await response.arrayBuffer(), {
      status: response.status,
      headers: output,
    });
  } catch {
    return NextResponse.json(
      { error: "Buyer API is unavailable" },
      { status: 503 },
    );
  }
}
