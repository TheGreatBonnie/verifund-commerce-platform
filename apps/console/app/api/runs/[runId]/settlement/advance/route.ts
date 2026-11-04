import { type NextRequest } from "next/server";
import { buyerJson } from "@/lib/buyer-proxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  const { runId } = await params;
  const body = (await request.text()) || JSON.stringify({ action: "refresh" });
  return buyerJson(
    `/api/runs/${encodeURIComponent(runId)}/settlement/advance`,
    { method: "POST", body, headers: { "content-type": "application/json" } },
  );
}
