import type { NextRequest } from "next/server";
import { controlPlaneJson } from "@/lib/control-plane-proxy";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const version = request.nextUrl.searchParams.get("version");
  const path = version
    ? `/agreements/${encodeURIComponent(id)}/document?version=${encodeURIComponent(version)}`
    : `/agreements/${encodeURIComponent(id)}/document`;
  return controlPlaneJson(path, {
    headers: {
      "X-Actor-Id": request.headers.get("x-actor-id") ?? "demo-buyer",
      "X-Actor-Type": request.headers.get("x-actor-type") ?? "buyer",
    },
  });
}
