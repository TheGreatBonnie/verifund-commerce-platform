"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { saveProfileAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

type Props = { initialDisplayName: string };

export function ProfileForm({ initialDisplayName }: Props) {
  const router = useRouter();
  const [displayName, setDisplayName] = useState(initialDisplayName);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        const name = displayName.trim();
        if (!name) {
          setError("Display name is required.");
          return;
        }
        startTransition(async () => {
          const result = await saveProfileAction(name);
          if (!result.ok) {
            setError(result.error);
            return;
          }
          router.push("/seller/onboarding/verification");
          router.refresh();
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 520 }}
    >
      <label className="mm-seller-field" style={{ margin: 0 }}>
        <span>Display name</span>
        <input
          type="text"
          maxLength={128}
          required
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="e.g. Acme Industrial"
        />
      </label>
      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" disabled={pending || !displayName.trim()}>
          {pending ? "Saving…" : "Save and continue"}
        </Button>
      </div>
    </form>
  );
}
