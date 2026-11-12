import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  return passthroughUpstream(
    await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}`),
  );
}
