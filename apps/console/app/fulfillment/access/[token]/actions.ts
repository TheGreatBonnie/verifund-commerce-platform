"use server";

import { redirect } from "next/navigation";
import { invitationRedirect } from "@/lib/invitation";

export type AccessExchangeState = {
  ok: boolean;
  error: string | null;
};

export async function exchangeInvitationAction(
  _previous: AccessExchangeState,
  formData: FormData,
): Promise<AccessExchangeState> {
  const token = String(formData.get("invitation_token") ?? "").trim();
  redirect(invitationRedirect(token));
}
