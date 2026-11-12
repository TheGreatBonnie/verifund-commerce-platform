import { auth } from "@clerk/nextjs/server";
import { type NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";
import { consoleSession } from "@/lib/console-session";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  await auth.protect();
  const { orgId } = await consoleSession();
  const { runId } = await params;
  const body = (await request.text()) || JSON.stringify({ action: "refresh" });
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}/settlement/advance`,
    { method: "POST", body, headers: { "content-type": "application/json" } },
    10_000,
    orgId,
  );
}
