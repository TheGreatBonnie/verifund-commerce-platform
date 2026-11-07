import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";
import { consoleSession } from "@/lib/console-session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  await auth.protect();
  const { orgId } = await consoleSession();
  const { runId } = await params;
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}`,
    {},
    8_000,
    orgId,
  );
}
