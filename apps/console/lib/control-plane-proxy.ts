import { NextResponse } from "next/server";

const CONTROL_PLANE =
  process.env.VERIFUND_CONTROL_PLANE_URL ?? "http://127.0.0.1:9300";
const OPS_TOKEN = process.env.VERIFUND_OPS_TOKEN ?? "dev-verifund-ops";

function headers(extra?: HeadersInit): Headers {
  const value = new Headers(extra);
  value.set("x-verifund-ops-token", OPS_TOKEN);
  return value;
}

export async function controlPlaneJson(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10_000,
): Promise<Response> {
  try {
    const response = await fetch(`${CONTROL_PLANE}${path}`, {
      ...init,
      cache: "no-store",
      headers: headers(init.headers),
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
      { error: "Control plane is unavailable" },
      { status: 503 },
    );
  }
}
