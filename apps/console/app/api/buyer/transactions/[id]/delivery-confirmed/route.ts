import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  const body = await request.text();
  return passthroughUpstream(
    await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/delivery-confirmed`, {
      method: "POST",
      headers: { "content-type": request.headers.get("content-type") ?? "application/json" },
      body: body || "{}",
    }),
  );
}
