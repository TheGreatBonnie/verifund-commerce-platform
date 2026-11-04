import type { NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  return buyerJson(`/api/runs/${encodeURIComponent(runId)}/settlement/receipt`);
}
