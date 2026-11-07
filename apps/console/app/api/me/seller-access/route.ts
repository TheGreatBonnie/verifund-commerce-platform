import { auth } from "@clerk/nextjs/server";
import { consoleSession } from "@/lib/console-session";
import { sellerAccess } from "@/lib/seller-access";

export const dynamic = "force-dynamic";

export async function GET() {
  await auth.protect();
  const { orgId } = await consoleSession();
  const access = await sellerAccess(orgId);
  return Response.json({ access, orgId }, { headers: { "Cache-Control": "no-store" } });
}
