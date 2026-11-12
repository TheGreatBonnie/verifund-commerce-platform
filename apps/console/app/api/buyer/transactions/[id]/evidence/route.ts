import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneBuyer, passthroughUpstream } from "@/lib/buyer-control-plane";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  const formData = await request.formData();
  return passthroughUpstream(
    await controlPlaneBuyer(`/buyer/transactions/${encodeURIComponent(id)}/evidence`, {
      method: "POST",
      body: formData,
    }),
  );
}
