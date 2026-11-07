"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { submitVerificationAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

export function VerificationSubmitForm() {
  const router = useRouter();
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        if (!confirmed) {
          setError("Please confirm your business details before submitting.");
          return;
        }
        startTransition(async () => {
          const result = await submitVerificationAction({
            confirmed: true,
            note: note.trim() || undefined,
            submitted_via: "seller_onboarding_wizard",
          });
          if (!result.ok) {
            setError(result.error);
            return;
          }
          const status = (result.data as { verification_status?: string }).verification_status;
          if (status === "verified") {
            router.push("/seller/onboarding/agent_setup");
          } else {
            router.refresh();
          }
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 560 }}
    >
      <label style={{ display: "flex", gap: 8, alignItems: "flex-start", fontSize: 12, color: "var(--muted)" }}>
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        <span>I confirm the business information provided for this seller account is accurate.</span>
      </label>
      <label className="mm-seller-field" style={{ margin: 0 }}>
        <span>Reference note (optional)</span>
        <input
          type="text"
          maxLength={500}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional reference for review"
        />
      </label>
      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" disabled={pending || !confirmed}>
          {pending ? "Submitting…" : "Submit for verification"}
        </Button>
      </div>
    </form>
  );
}
