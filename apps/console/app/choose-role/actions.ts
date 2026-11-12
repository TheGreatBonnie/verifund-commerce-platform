"use server";

import { auth } from "@clerk/nextjs/server";
import { promoteUserRole, type UserRole } from "@/lib/user-role";

export async function setRole(role: UserRole) {
  const { userId } = await auth.protect();
  if (!userId) throw new Error("unauthenticated");
  await promoteUserRole(userId, role);
}
