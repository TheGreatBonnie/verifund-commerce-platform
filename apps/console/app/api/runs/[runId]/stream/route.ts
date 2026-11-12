import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { consoleSession } from "@/lib/console-session";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ runId: string }> },
) {
  await auth.protect();
  const { orgId } = await consoleSession();
  const { runId } = await params;
  const buyer = process.env.BUYER_API_URL ?? "http://127.0.0.1:9100";
  const response = await fetch(
    `${buyer}/api/runs/${encodeURIComponent(runId)}/stream?organization_id=${encodeURIComponent(orgId ?? "")}`,
    {
      headers: {
        "x-verifund-internal-token": process.env.BUYER_INTERNAL_TOKEN ?? "",
      },
      cache: "no-store",
    },
  );
  return new Response(response.body, {
    status: response.status,
    headers: { "content-type": "text/event-stream" },
  });
}
