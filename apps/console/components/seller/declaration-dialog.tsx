"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, X } from "lucide-react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { Requirement } from "@/lib/seller-types";

function fieldLabel(checkId: string): string {
  return checkId.replaceAll("_", " ");
}

function defaultValueFor(checkId: string): string {
  if (checkId.includes("locks") || checkId.includes("disabled") || checkId.includes("cleared")) {
    return "true";
  }
  return "";
}

export function DeclarationDialog({
  transactionId,
  requirement,
  compact = false,
}: {
  transactionId: string;
  requirement: Requirement;
  compact?: boolean;
}) {
  const router = useRouter();
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = `declare-${transactionId}-${requirement.requirement_id}`;

  const initialValues = useMemo(() => {
    const values: Record<string, string> = {};
    for (const check of requirement.checks ?? []) {
      values[check.check_id] = defaultValueFor(check.check_id);
    }
    if (Object.keys(values).length === 0) {
      values.statement = "true";
    }
    return values;
  }, [requirement.checks]);

  const [values, setValues] = useState<Record<string, string>>(initialValues);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const onSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    setSuccess(null);
    try {
      const response = await fetch(
        `/api/seller/transactions/${encodeURIComponent(transactionId)}/requirements/${encodeURIComponent(requirement.requirement_id)}/declare`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ values }),
        },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message =
          body?.error?.message || body?.detail || `Declaration failed (${response.status})`;
        throw new Error(message);
      }
      setSuccess("Declaration submitted.");
      router.refresh();
      setTimeout(() => dialogRef.current?.close(), 300);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Declaration failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button
        type="button"
        variant={compact ? "outline" : "primary"}
        size={compact ? "sm" : "md"}
        leftIcon={<FileText size={13} aria-hidden="true" />}
        onClick={() => dialogRef.current?.showModal()}
      >
        Declare
      </Button>
      <dialog
        ref={dialogRef}
        className="mm-seller-dialog"
        aria-labelledby={titleId}
        onClick={(event) => {
          if (event.target === event.currentTarget) dialogRef.current?.close();
        }}
      >
        <div className="mm-seller-dialog-card">
          <header className="mm-seller-dialog-head">
            <div>
              <p className="mm-kicker">Declaration</p>
              <h2 id={titleId}>{requirement.title}</h2>
              <p>Submit structured values for this declaration requirement.</p>
            </div>
            <button
              type="button"
              className="mm-seller-dialog-close"
              onClick={() => dialogRef.current?.close()}
              aria-label="Close declaration dialog"
            >
              <X size={17} aria-hidden="true" />
            </button>
          </header>

          <form className="mm-seller-upload-form" onSubmit={onSubmit}>
            {Object.entries(values).map(([key, value]) => (
              <label className="mm-seller-field" key={key}>
                <span>{fieldLabel(key)}</span>
                <input
                  type="text"
                  value={value}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [key]: event.target.value }))
                  }
                  placeholder={key.includes("battery") ? "e.g. 85 or 85%" : "Value"}
                />
              </label>
            ))}
            <div className="mm-seller-upload-actions">
              <Button type="submit" loading={submitting}>
                Submit declaration
              </Button>
            </div>
            {error ? <Alert message={error} /> : null}
            {success ? <p className="mm-seller-upload-success" role="status">{success}</p> : null}
          </form>
        </div>
      </dialog>
    </>
  );
}
