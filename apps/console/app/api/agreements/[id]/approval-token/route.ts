import type { NextRequest } from "next/server";
import { controlPlaneJson } from "@/lib/control-plane-proxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const idempotencyKey =
    request.headers.get("idempotency-key") ?? crypto.randomUUID();
  return controlPlaneJson(`/agreements/${encodeURIComponent(id)}/approval-token`, {
    method: "POST",
    headers: {
      "Idempotency-Key": idempotencyKey,
      "X-Actor-Id": request.headers.get("x-actor-id") ?? "demo-buyer",
      "X-Actor-Type": request.headers.get("x-actor-type") ?? "buyer",
    },
  });
}
