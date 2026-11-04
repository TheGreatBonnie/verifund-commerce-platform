import { NextResponse } from "next/server";

const BUYER = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
const CONSOLE_TOKEN =
  process.env.BUYER_CONSOLE_API_TOKEN ?? "dev-console";

function headers(extra?: HeadersInit): Headers {
  const value = new Headers(extra);
  value.set("x-marketmesh-console-token", CONSOLE_TOKEN);
  return value;
}

export async function buyerJson(
  path: string,
  init: RequestInit = {},
  timeoutMs = 10_000,
): Promise<Response> {
  try {
    const response = await fetch(`${BUYER}${path}`, {
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
      { error: "Buyer API is unavailable" },
      { status: 503 },
    );
  }
}

export async function buyerBinary(
  path: string,
  timeoutMs = 10_000,
): Promise<Response> {
  try {
    const response = await fetch(`${BUYER}${path}`, {
      cache: "no-store",
      headers: headers(),
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
