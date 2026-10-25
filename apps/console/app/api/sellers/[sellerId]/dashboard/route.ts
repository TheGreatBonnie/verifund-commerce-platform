import { NextResponse, type NextRequest } from "next/server";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ sellerId: string }> },
) {
  const { sellerId } = await params;
  const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
  const token = process.env.BUYER_CONSOLE_API_TOKEN ?? "dev-console";

  try {
    const response = await fetch(
      `${buyer}/api/sellers/${encodeURIComponent(sellerId)}/dashboard`,
      {
        headers: { "x-marketmesh-console-token": token },
        cache: "no-store",
        signal: AbortSignal.timeout(10_000),
      },
    );
    const body = await response.text();
    return new Response(body, {
      status: response.status,
      headers: { "content-type": "application/json" },
    });
  } catch {
    return NextResponse.json(
      { error: "Seller data is unavailable" },
      { status: 503 },
    );
  }
}
