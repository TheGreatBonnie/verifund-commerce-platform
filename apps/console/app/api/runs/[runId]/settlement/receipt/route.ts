import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  await auth.protect();
  const { runId } = await params;
  return buyerJson(`/api/runs/${encodeURIComponent(runId)}/settlement/receipt`);
}
