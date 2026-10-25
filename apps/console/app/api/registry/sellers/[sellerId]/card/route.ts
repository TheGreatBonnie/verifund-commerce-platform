import { NextResponse, type NextRequest } from "next/server";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ sellerId: string }> },
) {
  const { sellerId } = await params;
  const registry = process.env.REGISTRY_URL ?? "http://127.0.0.1:9105";
  try {
    const response = await fetch(
      `${registry}/v1/sellers/${encodeURIComponent(sellerId)}`,
      { cache: "no-store", signal: AbortSignal.timeout(8_000) },
    );
    if (!response.ok) {
      return NextResponse.json({ error: "Agent Card is unavailable" }, { status: response.status });
    }
    const seller = await response.json() as { card_json?: unknown };
    if (!seller.card_json) {
      return NextResponse.json({ error: "Agent Card is unavailable" }, { status: 404 });
    }
    return NextResponse.json(seller.card_json, {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json({ error: "Registry is unavailable" }, { status: 503 });
  }
}
