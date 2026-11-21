"use server";

import { auth } from "@clerk/nextjs/server";
import { revalidatePath } from "next/cache";
import { controlPlaneForUser } from "@/lib/control-plane";

export async function approvePayout(
  transactionId: string,
  reason: string,
): Promise<void> {
  await auth.protect();
  const response = await controlPlaneForUser(
    `/v1/admin/transactions/${encodeURIComponent(transactionId)}/payout-release`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reason }),
    },
  );
  if (!response.ok) throw new Error(`payout release ${response.status}`);
  revalidatePath("/admin/payouts");
}
