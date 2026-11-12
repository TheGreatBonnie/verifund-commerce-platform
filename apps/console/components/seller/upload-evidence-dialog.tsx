"use client";

import { useRef } from "react";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { EvidenceItem, Requirement } from "@/lib/seller-types";
import { UploadEvidenceForm } from "./upload-evidence-form";

export function UploadEvidenceDialog({
  transactionId,
  agreementVersion,
  requirements,
  evidenceItems = [],
  defaultRequirementId,
  label = "Upload evidence",
  compact = false,
}: {
  transactionId: string;
  agreementVersion: number;
  requirements: Requirement[];
  evidenceItems?: EvidenceItem[];
  defaultRequirementId?: string;
  label?: string;
  compact?: boolean;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const titleId = `upload-evidence-${transactionId}-${defaultRequirementId ?? "all"}`;

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size={compact ? "sm" : "md"}
        leftIcon={<Plus size={13} aria-hidden="true" />}
        onClick={() => dialogRef.current?.showModal()}
      >
        {label}
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
              <p className="mm-kicker">Evidence intake</p>
              <h2 id={titleId}>Submit evidence</h2>
              <p>
                Transaction {transactionId} · Agreement version {agreementVersion}
              </p>
            </div>
            <button
              type="button"
              className="mm-seller-dialog-close"
              onClick={() => dialogRef.current?.close()}
              aria-label="Close upload dialog"
            >
              <X size={17} aria-hidden="true" />
            </button>
          </header>
          <UploadEvidenceForm
            transactionId={transactionId}
            agreementVersion={agreementVersion}
            requirements={requirements}
            evidenceItems={evidenceItems}
            defaultRequirementId={defaultRequirementId}
            onSuccess={() => dialogRef.current?.close()}
          />
        </div>
      </dialog>
    </>
  );
}
