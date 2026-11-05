"use server";

import { redirect } from "next/navigation";
import { clearSellerTokens } from "@/lib/seller-api";

export async function signOutAction(): Promise<void> {
  await clearSellerTokens();
  redirect("/seller/dashboard");
}
