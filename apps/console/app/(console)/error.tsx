"use client";

import { Alert } from "@/components/ui/alert";

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mm-page-error">
      <Alert message={error?.message ?? "Something went wrong"} onDismiss={undefined} />
      <button type="button" className="mm-button mm-button-outline" onClick={reset}>
        Try again
      </button>
    </div>
  );
}
