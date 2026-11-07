import { auth } from "@clerk/nextjs/server";
import { NextResponse } from "next/server";

import { controlPlaneForUser } from "@/lib/control-plane";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  let formData: FormData;
  try {
    formData = await request.formData();
  } catch {
    return NextResponse.json(
      { error: { message: "Expected multipart form data" } },
      { status: 400 },
    );
  }
  try {
    const upstream = await controlPlaneForUser(
      `/seller/transactions/${encodeURIComponent(id)}/evidence`,
      { method: "POST", body: formData },
    );
    const text = await upstream.text();
    const contentType = upstream.headers.get("content-type") ?? "application/json";
    return new Response(text, {
      status: upstream.status,
      headers: { "content-type": contentType },
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: {
          message:
            error instanceof Error ? error.message : "Upload failed",
        },
      },
      { status: 503 },
    );
  }
}
