"use client";

import { useActionState } from "react";
import { ShieldCheck } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { exchangeInvitationAction } from "./actions";

export function AccessExchangeForm({ token }: { token: string }) {
  const [state, formAction, pending] = useActionState(
    exchangeInvitationAction,
    { ok: false, error: null as string | null },
  );

  return (
    <form action={formAction} className="mm-seller-access-form">
      <div className="mm-seller-access-token">
        <ShieldCheck size={15} aria-hidden="true" />
        <span>Invitation token detected</span>
        <code>{token.length > 14 ? `${token.slice(0, 14)}…` : token}</code>
      </div>
      <input type="hidden" name="invitation_token" value={token} />
      <Button type="submit" loading={pending} className="mm-seller-access-submit">
        Open my fulfillment workspace
      </Button>
      {state.error ? <Alert message={state.error} /> : null}
      <p className="mm-mono-note">
        Exchanging validates expiry, seller ownership, and transaction scope on
        the server before any workspace access is granted.
      </p>
    </form>
  );
}
