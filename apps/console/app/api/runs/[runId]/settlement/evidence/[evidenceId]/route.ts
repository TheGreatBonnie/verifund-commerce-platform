import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { buyerBinary } from "@/lib/buyer-proxy";
import { consoleSession } from "@/lib/console-session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string; evidenceId: string }> },
) {
  await auth.protect();
  const { orgId } = await consoleSession();
  const { runId, evidenceId } = await params;
  return buyerBinary(
    `/api/runs/${encodeURIComponent(runId)}/settlement/evidence/${encodeURIComponent(evidenceId)}`,
    10_000,
    orgId,
  );
}
