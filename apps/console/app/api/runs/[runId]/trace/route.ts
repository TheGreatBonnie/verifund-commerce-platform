import { NextRequest } from "next/server";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const after = request.nextUrl.searchParams.get("after_seq") ?? "0";
  try {
    const response = await fetch(
      `${process.env.BUYER_API_URL ?? "http://127.0.0.1:9100"}` +
        `/api/runs/${encodeURIComponent(runId)}/trace?after_seq=${encodeURIComponent(after)}`,
      { cache: "no-store", signal: AbortSignal.timeout(8_000) },
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
