"use client";

import { useState } from "react";
import type { AgreementView } from "@/lib/types";

type Props = {
  agreement?: AgreementView | any;
  version?: number;
  hash?: string;
  agreementVersion?: number;
  agreementHash?: string;
  onApprove?: (note: string) => void | Promise<void>;
  onReject?: (note: string) => void | Promise<void>;
  onRequestChanges?: (note: string) => void | Promise<void>;
  disabled?: boolean;
  stale?: boolean;
  isStale?: boolean;
};

export function ApprovalActions({
  agreement,
  version,
  hash,
  agreementVersion,
  agreementHash,
  onApprove,
  onReject,
  onRequestChanges,
  disabled,
  stale,
  isStale,
}: Props) {
  const [note, setNote] = useState("");
  const a = agreement ?? {};
  const v = version ?? agreementVersion ?? a.current_version ?? a.agreement_version;
  const h = hash ?? agreementHash ?? a.agreement_hash ?? a.version?.agreement_hash;
  const staleFlag = Boolean(stale || isStale || disabled);

  const handle = async (fn?: (n: string) => void | Promise<void>) => {
    if (!fn || staleFlag) return;
    await fn(note);
  };

  return (
    <section data-testid="approval-actions" className="mm-approval-actions">
      <label className="mm-note-field">
        Note
        <textarea value={note} onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="mm-approval-actions">
        <button
          type="button"
          data-testid="approve-button"
          disabled={staleFlag}
          onClick={() => handle(onApprove)}
        >
          Approve
        </button>
        <button
          type="button"
          data-testid="reject-button"
          disabled={staleFlag}
          onClick={() => handle(onReject)}
        >
          Reject
        </button>
        <button
          type="button"
          data-testid="request-changes-button"
          disabled={staleFlag}
          onClick={() => handle(onRequestChanges)}
        >
          Request changes
        </button>
      </div>
      {staleFlag ? (
        <p role="alert" data-testid="stale-digest">
          This agreement version is stale; approval is disabled.
        </p>
      ) : null}
    </section>
  );
}

export default ApprovalActions;
