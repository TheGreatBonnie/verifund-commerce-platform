"use client";

import { useRef, useState } from "react";
import { submitBuyerEvidence } from "@/lib/buyer-transaction-api";

export function BuyerEvidenceDialog({
  transactionId,
  requirements,
  onSubmitted,
}: {
  transactionId: string;
  requirements: any[];
  onSubmitted: () => Promise<void> | void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [requirementId, setRequirementId] = useState("");
  const [viewLabel, setViewLabel] = useState("");
  const [agreementVersion, setAgreementVersion] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const buyerRequirements = requirements.filter(
    (r) => r?.owner === "buyer" || r?.buyer_actionable || r?.source === "buyer_evidence",
  );
  const options = buyerRequirements.length ? buyerRequirements : requirements;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file || !requirementId) {
      setError("Requirement and file are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.set("requirement_id", requirementId);
      if (viewLabel) fd.set("view_label", viewLabel);
      if (agreementVersion) fd.set("agreement_version", agreementVersion);
      fd.set("file", file);
      await submitBuyerEvidence(transactionId, fd);
      await onSubmitted();
      ref.current?.close();
      setFile(null);
    } catch (err: any) {
      setError(err?.message ?? "Evidence upload failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <button type="button" onClick={() => ref.current?.showModal()}>
        Submit buyer evidence
      </button>
      <dialog ref={ref} aria-label="Submit buyer evidence">
        <form onSubmit={submit} style={{ display: "grid", gap: 8, minWidth: 320 }}>
          <h3>Submit buyer evidence</h3>
          <label>
            Requirement
            <select value={requirementId} onChange={(e) => setRequirementId(e.target.value)} required>
              <option value="">Select requirement</option>
              {options.map((r) => (
                <option key={r.requirement_id ?? r.id} value={r.requirement_id ?? r.id}>
                  {r.title ?? r.requirement_id ?? r.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            View label
            <input value={viewLabel} onChange={(e) => setViewLabel(e.target.value)} placeholder="e.g. front, back, screen" />
          </label>
          <label>
            Agreement version
            <input value={agreementVersion} onChange={(e) => setAgreementVersion(e.target.value)} placeholder="Agreement version" />
          </label>
          <label>
            File
            <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
          </label>
          {error ? <p role="alert">{error}</p> : null}
          <div style={{ display: "flex", gap: 8 }}>
            <button type="submit" disabled={busy}>{busy ? "Uploading…" : "Upload evidence"}</button>
            <button type="button" onClick={() => ref.current?.close()}>Cancel</button>
          </div>
        </form>
      </dialog>
    </>
  );
}
