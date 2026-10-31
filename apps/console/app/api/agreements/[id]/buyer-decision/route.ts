import type { NextRequest } from "next/server";
import { controlPlaneJson } from "@/lib/control-plane-proxy";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const body = await request.text();
  const token = request.headers.get("x-approval-token") ?? "";
  const idempotencyKey =
    request.headers.get("idempotency-key") ?? crypto.randomUUID();
  return controlPlaneJson(`/agreements/${encodeURIComponent(id)}/buyer-decision`, {
    method: "POST",
    body,
    headers: {
      "content-type": "application/json",
      "Idempotency-Key": idempotencyKey,
      "X-Approval-Token": token,
      "X-Actor-Id": request.headers.get("x-actor-id") ?? "demo-buyer",
      "X-Actor-Type": request.headers.get("x-actor-type") ?? "buyer",
    },
  });
}
