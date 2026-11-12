import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  const { id } = await params;
  const response = await controlPlaneForUser(
    `/agreements/${encodeURIComponent(id)}/versions`,
    { method: "GET" },
  );
  return new Response(await response.text(), {
    status: response.status,
    headers: { "content-type": "application/json" },
  });
}
