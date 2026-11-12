import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

import { controlPlaneForUser } from "@/lib/control-plane";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; requirementId: string }> },
) {
  await auth.protect();
  const { id, requirementId } = await params;
  try {
    const upstream = await controlPlaneForUser(
      `/seller/transactions/${encodeURIComponent(id)}/requirements/${encodeURIComponent(requirementId)}/declarations`,
    );
    const text = await upstream.text();
    return new Response(text, {
      status: upstream.status,
      headers: {
        "content-type": upstream.headers.get("content-type") ?? "application/json",
      },
    });
  } catch (error) {
    return NextResponse.json(
      { error: { message: error instanceof Error ? error.message : "Failed to load declarations" } },
      { status: 503 },
    );
  }
}
