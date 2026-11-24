"use server";

import { auth, clerkClient } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";

export async function signOutAction(): Promise<void> {
  const { sessionId } = await auth.protect(); // literal guard required by tests/app/route-guards.test.ts
  if (sessionId) {
    const client = await clerkClient();
    await client.sessions.revokeSession(sessionId);
  }
  redirect("/");
}
