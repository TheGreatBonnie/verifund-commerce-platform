import { clerkClient } from "@clerk/nextjs/server";

export type UserRole = "buyer" | "seller";

export async function promoteUserRole(userId: string, role: UserRole): Promise<void> {
  const client = await clerkClient();
  await client.users.updateUserMetadata(userId, { publicMetadata: { role } });
}
