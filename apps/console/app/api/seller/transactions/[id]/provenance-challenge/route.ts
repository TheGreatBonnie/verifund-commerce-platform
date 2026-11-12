import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

import { controlPlaneForUser } from "@/lib/control-plane";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  try {
    const upstream = await controlPlaneForUser(
      `/seller/transactions/${encodeURIComponent(id)}/provenance-challenge`,
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
      { error: { message: error instanceof Error ? error.message : "Failed to load provenance challenge" } },
      { status: 503 },
    );
  }
}

export async function POST(
  _request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  try {
    const upstream = await controlPlaneForUser(
      `/seller/transactions/${encodeURIComponent(id)}/provenance-challenge`,
      { method: "POST" },
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
      { error: { message: error instanceof Error ? error.message : "Failed to issue provenance challenge" } },
      { status: 503 },
    );
  }
}
