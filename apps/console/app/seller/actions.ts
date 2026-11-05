"use server";
import { auth } from "@clerk/nextjs/server";

import { redirect } from "next/navigation";
import { clearSellerTokens } from "@/lib/seller-api";

export async function signOutAction(): Promise<void> {
  await auth.protect();
  await clearSellerTokens();
  redirect("/seller/dashboard");
}
