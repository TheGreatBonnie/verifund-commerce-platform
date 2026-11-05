import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function GET(request: NextRequest) {
  await auth.protect();
  const transactionId = request.nextUrl.searchParams.get("transaction_id");
  const path = transactionId
    ? `/agreements?transaction_id=${encodeURIComponent(transactionId)}`
    : "/agreements";
  const response = await controlPlaneForUser(path, { method: "GET" });
  return new Response(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
