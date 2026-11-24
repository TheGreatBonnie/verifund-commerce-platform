"use server";

import { auth, currentUser } from "@clerk/nextjs/server";
import { promoteUserRole, type UserRole } from "@/lib/user-role";

export async function setRole(role: UserRole) {
  const { userId } = await auth.protect();
  if (!userId) throw new Error("unauthenticated");
  const user = await currentUser();
  if ((user?.publicMetadata?.role as string) === "admin") {
    throw new Error("admin role cannot be changed here");
  }
  await promoteUserRole(userId, role);
}
