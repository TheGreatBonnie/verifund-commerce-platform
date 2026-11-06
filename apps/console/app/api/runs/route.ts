import { auth } from "@clerk/nextjs/server";
import { NextRequest } from "next/server";
import { consoleSession } from "@/lib/console-session";

export async function GET(request: NextRequest) {
  await auth.protect();
  const { orgId } = await consoleSession();
  const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
  const limit = request.nextUrl.searchParams.get("limit") ?? "50";
  try {
    const response = await fetch(
      `${buyer}/api/runs?organization_id=${encodeURIComponent(orgId ?? "")}&limit=${encodeURIComponent(limit)}`,
      {
        headers: {
          "x-verifund-internal-token": process.env.BUYER_INTERNAL_TOKEN ?? "",
        },
        cache: "no-store",
        signal: AbortSignal.timeout(8_000),
      },
    );
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json({ error: "Buyer API is unavailable" }, { status: 503 });
  }
}
