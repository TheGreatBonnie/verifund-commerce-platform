import type { NextRequest } from "next/server";
import { controlPlaneJson } from "@/lib/control-plane-proxy";

export async function GET(request: NextRequest) {
  const transactionId = request.nextUrl.searchParams.get("transaction_id");
  const path = transactionId
    ? `/agreements?transaction_id=${encodeURIComponent(transactionId)}`
    : "/agreements";
  return controlPlaneJson(path, {
    headers: {
      "X-Actor-Id": request.headers.get("x-actor-id") ?? "demo-buyer",
      "X-Actor-Type": request.headers.get("x-actor-type") ?? "buyer",
    },
  });
}
