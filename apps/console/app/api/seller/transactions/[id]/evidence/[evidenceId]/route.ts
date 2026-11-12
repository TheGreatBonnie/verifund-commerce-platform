import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

import { controlPlaneForUser } from "@/lib/control-plane";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string; evidenceId: string }> },
) {
  await auth.protect();
  const { id, evidenceId } = await params;
  try {
    const upstream = await controlPlaneForUser(
      `/seller/transactions/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`,
    );
    if (!upstream.ok) {
      const text = await upstream.text();
      return new Response(text, {
        status: upstream.status,
        headers: {
          "content-type":
            upstream.headers.get("content-type") ?? "application/json",
        },
      });
    }
    const bytes = await upstream.arrayBuffer();
    return new Response(bytes, {
      status: 200,
      headers: {
        "content-type":
          upstream.headers.get("content-type") ?? "application/octet-stream",
        "content-disposition":
          upstream.headers.get("content-disposition") ?? "inline",
      },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: {
          message:
            error instanceof Error ? error.message : "Evidence download failed",
        },
      },
      { status: 503 },
    );
  }
}
