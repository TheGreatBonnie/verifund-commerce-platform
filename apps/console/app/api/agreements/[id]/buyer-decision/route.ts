import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  const body = await request.text();
  const token = request.headers.get("x-approval-token") ?? "";
  const idempotencyKey =
    request.headers.get("idempotency-key") ?? crypto.randomUUID();
  const response = await controlPlaneForUser(
    `/agreements/${encodeURIComponent(id)}/buyer-decision`,
    {
      method: "POST",
      body,
      headers: {
        "content-type": "application/json",
        "Idempotency-Key": idempotencyKey,
        "X-Approval-Token": token,
      },
    },
  );
  return new Response(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
