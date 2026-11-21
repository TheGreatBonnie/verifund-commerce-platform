import { auth } from "@clerk/nextjs/server";
import { adminAccess } from "@/lib/admin-access";

export const dynamic = "force-dynamic";

export async function GET() {
  await auth.protect();
  const admin = await adminAccess();
  return Response.json({ admin }, { headers: { "Cache-Control": "no-store" } });
}
