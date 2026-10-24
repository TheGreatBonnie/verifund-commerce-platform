import { NextRequest } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
  try {
    const response = await fetch(`${buyer}/api/runs/${encodeURIComponent(runId)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8_000),
    });
    return new Response(await response.text(), {
      status: response.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return Response.json({ error: "Buyer API is unavailable" }, { status: 503 });
  }
}
