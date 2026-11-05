import { auth } from "@clerk/nextjs/server";
import { type NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  await auth.protect();
  const { runId } = await params;
  const body = await request.text();
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}/settlement/cancel`,
    { method: "POST", body, headers: { "content-type": "application/json" } },
  );
}
