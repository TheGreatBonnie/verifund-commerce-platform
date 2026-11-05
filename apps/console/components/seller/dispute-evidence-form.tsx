"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { EvidenceItem } from "@/lib/seller-types";

export function DisputeEvidenceForm({
  transactionId,
  onSuccess,
}: {
  transactionId: string;
  onSuccess?: () => void;
}) {
  const router = useRouter();
  const [capturedAt, setCapturedAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<EvidenceItem | null>(null);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    setSubmitting(true);
    setError(null);
    setReceipt(null);

    if (capturedAt) {
      const captured = new Date(capturedAt);
      if (Number.isNaN(captured.getTime())) {
        setError("Captured time is not valid.");
        setSubmitting(false);
        return;
      }
      formData.set("captured_at", captured.toISOString());
    } else {
      formData.delete("captured_at");
    }

    const file = formData.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("Choose a file to upload.");
      setSubmitting(false);
      return;
    }

    try {
      const response = await fetch(
        `/api/seller/transactions/${encodeURIComponent(transactionId)}/dispute-evidence`,
        { method: "POST", body: formData },
      );
      const body = (await response.json()) as
        | EvidenceItem
        | { error?: { message?: string } | string; detail?: string };
      if (!response.ok) {
        const message =
          typeof body === "object" && body && "error" in body
            ? typeof body.error === "string"
              ? body.error
              : body.error?.message
            : undefined;
        throw new Error(message ?? `Upload failed (${response.status})`);
      }
      setReceipt(body as EvidenceItem);
      form.reset();
      setCapturedAt("");
      router.refresh();
      onSuccess?.();
    } catch (uploadError) {
      setError(
        uploadError instanceof Error ? uploadError.message : "Upload failed",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="mm-seller-upload-form" onSubmit={onSubmit}>
      <p className="mm-seller-form-note">
        Dispute evidence is attached to this transaction for the reviewer. It
        does not change the transaction state automatically.
      </p>
      <div className="mm-seller-field-grid">
        <label className="mm-seller-field">
          <span>Evidence file</span>
          <input
            type="file"
            name="file"
            accept="image/jpeg,image/png,image/webp,video/mp4,video/quicktime,video/webm,text/csv,text/plain,application/pdf,application/json"
            required
          />
        </label>
        <label className="mm-seller-field">
          <span>Captured at</span>
          <input
            type="datetime-local"
            value={capturedAt}
            onChange={(event) => setCapturedAt(event.target.value)}
          />
        </label>
      </div>
      <label className="mm-seller-field">
        <span>Description</span>
        <textarea
          name="note"
          rows={3}
          placeholder="Explain how this evidence answers the buyer's claim."
        />
      </label>
      <div className="mm-seller-upload-actions">
        <Button type="submit" loading={submitting}>
          Submit dispute evidence
        </Button>
      </div>
      {error ? <Alert message={error} /> : null}
      {receipt ? (
        <p className="mm-seller-upload-success" role="status">
          Uploaded {receipt.evidence_id} · {receipt.scan_status ?? "received"}
        </p>
      ) : null}
    </form>
  );
}
