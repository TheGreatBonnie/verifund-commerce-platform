import { auth } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

export async function GET(request: NextRequest) {
  await auth.protect();
  const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
  const token = process.env.BUYER_CONSOLE_API_TOKEN ?? "dev-console";
  const target = new URL("/api/marketplace/products", buyer);
  request.nextUrl.searchParams.forEach((value, key) => target.searchParams.set(key, value));

  try {
    const response = await fetch(target, {
      headers: { "x-marketmesh-console-token": token },
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": "application/json", "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "Marketplace catalog is unavailable" }, { status: 503 });
  }
}
