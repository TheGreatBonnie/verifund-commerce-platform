"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { EvidenceReceipt, Requirement } from "@/lib/seller-types";

const FORMAT_LABELS: Record<string, string> = {
  "image/jpeg": "JPG",
  "image/png": "PNG",
  "image/webp": "WEBP",
  "video/mp4": "MP4",
  "video/quicktime": "MOV",
  "video/webm": "WEBM",
  "text/csv": "CSV",
  "text/plain": "TXT",
  "application/pdf": "PDF",
  "application/json": "JSON",
};

function formatLabel(mediaType: string): string {
  return FORMAT_LABELS[mediaType.toLowerCase()] ?? mediaType.toUpperCase();
}

function sellerRequirements(requirements: Requirement[]): Requirement[] {
  return requirements.filter((requirement) => requirement.owner === "seller");
}

export function UploadEvidenceForm({
  transactionId,
  agreementVersion,
  requirements,
  defaultRequirementId,
  onSuccess,
}: {
  transactionId: string;
  agreementVersion: number;
  requirements: Requirement[];
  defaultRequirementId?: string;
  onSuccess?: () => void;
}) {
  const router = useRouter();
  const uploadable = useMemo(
    () => sellerRequirements(requirements),
    [requirements],
  );
  const initial = useMemo(() => {
    return (
      uploadable.find(
        (requirement) => requirement.requirement_id === defaultRequirementId,
      ) ?? uploadable[0]
    );
  }, [defaultRequirementId, uploadable]);

  const [requirementId, setRequirementId] = useState(
    initial?.requirement_id ?? "",
  );
  const [referenceType, setReferenceType] = useState(
    initial?.kind === "shipment_manifest" ? "tracking" : "url",
  );
  const [capturedAt, setCapturedAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [receipt, setReceipt] = useState<EvidenceReceipt | null>(null);

  const selected = uploadable.find(
    (requirement) => requirement.requirement_id === requirementId,
  );

  if (!uploadable.length) {
    return (
      <p className="mm-empty">
        No seller-owned requirements are available for this order yet.
      </p>
    );
  }

  const onRequirementChange = (value: string) => {
    setRequirementId(value);
    const next = uploadable.find(
      (requirement) => requirement.requirement_id === value,
    );
    setReferenceType(next?.kind === "shipment_manifest" ? "tracking" : "url");
    setReceipt(null);
    setError(null);
  };

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
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

    if (selected.source === "reference") {
      formData.delete("file");
      const reference = String(formData.get("reference") ?? "").trim();
      if (!reference) {
        setError("Enter a reference value or URL.");
        setSubmitting(false);
        return;
      }
      formData.set("reference", reference);
      formData.set("reference_type", referenceType);
    } else {
      formData.delete("reference");
      formData.delete("reference_type");
      const file = formData.get("file");
      if (!(file instanceof File) || file.size === 0) {
        setError("Choose a file to upload.");
        setSubmitting(false);
        return;
      }
    }

    formData.set("requirement_id", selected.requirement_id);
    formData.set("agreement_version", String(agreementVersion));

    try {
      const response = await fetch(
        `/api/seller/transactions/${encodeURIComponent(transactionId)}/evidence`,
        { method: "POST", body: formData },
      );
      const body = (await response.json()) as
        | EvidenceReceipt
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
      setReceipt(body as EvidenceReceipt);
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
      <div className="mm-seller-field-grid">
        <label className="mm-seller-field">
          <span>Requirement</span>
          <select
            name="requirement_id"
            value={requirementId}
            onChange={(event) => onRequirementChange(event.target.value)}
          >
            {uploadable.map((requirement) => (
              <option
                key={requirement.requirement_id}
                value={requirement.requirement_id}
              >
                {requirement.title} ({requirement.requirement_id})
              </option>
            ))}
          </select>
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

      {selected ? (
        <div className="mm-seller-format-row" aria-label="Accepted formats">
          <span className="mm-kicker">
            {selected.source === "reference"
              ? "Reference accepted"
              : "Accepted formats"}
          </span>
          {selected.source === "reference" ? (
            <span className="mm-seller-format-chip">
              {selected.kind === "shipment_manifest"
                ? "Carrier tracking number"
                : "Reference or URL"}
            </span>
          ) : (
            selected.accepted_formats.map((mediaType) => (
              <span className="mm-seller-format-chip" key={mediaType}>
                {formatLabel(mediaType)}
              </span>
            ))
          )}
        </div>
      ) : null}

      {selected?.source === "reference" ? (
        <div className="mm-seller-field-grid">
          <label className="mm-seller-field">
            <span>{selected.kind === "shipment_manifest" ? "Tracking number" : "Reference or URL"}</span>
            <input
              type="text"
              name="reference"
              placeholder={
                selected.kind === "shipment_manifest"
                  ? "1Z999AA10123456784"
                  : "https://example.com/document"
              }
              required
            />
          </label>
          <label className="mm-seller-field">
            <span>Reference type</span>
            <select
              name="reference_type"
              value={referenceType}
              onChange={(event) => setReferenceType(event.target.value)}
            >
              <option value="tracking">Tracking number</option>
              <option value="url">URL</option>
            </select>
          </label>
        </div>
      ) : selected ? (
        <label className="mm-seller-field">
          <span>File</span>
          <input
            type="file"
            name="file"
            accept={selected.accepted_formats.join(",")}
            required
          />
        </label>
      ) : null}

      <label className="mm-seller-field">
        <span>Description</span>
        <textarea
          name="note"
          rows={3}
          placeholder="What is this evidence, and what does it show?"
        />
      </label>

      <div className="mm-seller-upload-actions">
        <Button type="submit" loading={submitting}>
          Upload evidence
        </Button>
        <span className="mm-mono-note">
          Evidence is hashed on receipt; the server returns the submission id.
        </span>
      </div>

      {error ? <Alert message={error} /> : null}
      {receipt ? (
        <p className="mm-seller-upload-success" role="status">
          Uploaded {receipt.receipt_id} · attempt {receipt.attempt} ·{" "}
          {receipt.scan_status}
        </p>
      ) : null}
    </form>
  );
}
