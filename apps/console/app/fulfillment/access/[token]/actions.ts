"use server";

import { redirect } from "next/navigation";
import {
  exchangeInvitation,
  saveSellerToken,
  SellerApiError,
} from "@/lib/seller-api";

export type AccessExchangeState = {
  ok: boolean;
  error: string | null;
};

export async function exchangeInvitationAction(
  _previous: AccessExchangeState,
  formData: FormData,
): Promise<AccessExchangeState> {
  const token = String(formData.get("invitation_token") ?? "").trim();
  if (!token) {
    return { ok: false, error: "Invitation token is missing." };
  }
  try {
    const exchanged = await exchangeInvitation(token);
    const transactionId = await saveSellerToken(exchanged.token);
    redirect(
      `/seller/fulfillment/${encodeURIComponent(transactionId)}`,
    );
  } catch (error) {
    if (error instanceof SellerApiError) {
      return { ok: false, error: error.message };
    }
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Invitation exchange failed",
    };
  }
}
