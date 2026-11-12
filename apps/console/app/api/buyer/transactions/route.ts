import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function GET(request: NextRequest) {
  await auth.protect();
  const qs = request.nextUrl.search;
  const upstream = await controlPlaneBuyer(`/buyer/transactions${qs}`);
  return passthroughUpstream(upstream);
}
