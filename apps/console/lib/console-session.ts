import { auth } from "@clerk/nextjs/server";

export async function consoleSession() {
  const { userId, orgId, orgRole } = await auth.protect();
  if (!userId) throw new Error("unauthenticated");
  return { userId, orgId: orgId ?? null, orgRole: orgRole ?? null };
}
