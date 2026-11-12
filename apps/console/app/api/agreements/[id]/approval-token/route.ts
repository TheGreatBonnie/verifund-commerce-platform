import { auth } from "@clerk/nextjs/server";
import type { NextRequest } from "next/server";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function POST(
  _request: NextRequest,
  _ctx: { params: Promise<{ id: string }> },
) {
  await auth.protect();
  return new Response(
    JSON.stringify({
      error: {
        code: "gone",
        message:
          "buyer approval tokens are not used; authenticate and submit decision",
      },
    }),
    { status: 410, headers: { "content-type": "application/json" } },
  );
}
