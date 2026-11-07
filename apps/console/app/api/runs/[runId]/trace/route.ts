import { auth } from "@clerk/nextjs/server";
import { NextRequest } from "next/server";
import { consoleSession } from "@/lib/console-session";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  await auth.protect();
  const { orgId } = await consoleSession();
  const { runId } = await params;
  const after = request.nextUrl.searchParams.get("after_seq") ?? "0";
  try {
    const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
    const org = orgId ? `&organization_id=${encodeURIComponent(orgId)}` : "";
    const response = await fetch(
      `${buyer}` +
        `/api/runs/${encodeURIComponent(runId)}/trace?after_seq=${encodeURIComponent(after)}${org}`,
      {
        headers: {
          "x-marketmesh-console-token": process.env.BUYER_CONSOLE_API_TOKEN ?? "dev-console",
          ...(process.env.BUYER_INTERNAL_TOKEN
            ? { "x-verifund-internal-token": process.env.BUYER_INTERNAL_TOKEN }
            : {}),
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
    return Response.json(
      { error: "Buyer API is unavailable" },
      { status: 503 },
    );
  }
}
