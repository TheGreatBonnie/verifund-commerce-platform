import type { NextRequest } from "next/server";
import { controlPlaneJson } from "@/lib/control-plane-proxy";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  return controlPlaneJson(`/agreements/${encodeURIComponent(id)}`, {
    headers: {
      "X-Actor-Id": request.headers.get("x-actor-id") ?? "demo-buyer",
      "X-Actor-Type": request.headers.get("x-actor-type") ?? "buyer",
    },
  });
}
