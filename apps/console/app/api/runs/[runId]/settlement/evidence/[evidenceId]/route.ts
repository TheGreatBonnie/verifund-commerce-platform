import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { buyerBinary } from "@/lib/buyer-proxy";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string; evidenceId: string }> },
) {
  await auth.protect();
  const { runId, evidenceId } = await params;
  return buyerBinary(
    `/api/runs/${encodeURIComponent(runId)}/settlement/evidence/${encodeURIComponent(evidenceId)}`,
  );
}
