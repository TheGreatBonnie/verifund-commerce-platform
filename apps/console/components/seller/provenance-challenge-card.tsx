"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { formatDateTime } from "@/lib/format";
import type { ProvenanceChallenge } from "@/lib/seller-types";

export function ProvenanceChallengeCard({
  transactionId,
  initialChallenge,
  canIssue,
}: {
  transactionId: string;
  initialChallenge: ProvenanceChallenge | null;
  canIssue: boolean;
}) {
  const router = useRouter();
  const [challenge, setChallenge] = useState<ProvenanceChallenge | null>(initialChallenge);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const issue = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/seller/transactions/${encodeURIComponent(transactionId)}/provenance-challenge`,
        { method: "POST" },
      );
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(body?.error?.message || body?.detail || `Failed (${response.status})`);
      }
      setChallenge(body as ProvenanceChallenge);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to issue challenge");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="mm-panel" aria-label="Provenance challenge">
      <div className="mm-panel-head">
        <div>
          <p className="mm-kicker">Product identity</p>
          <h2>Provenance challenge</h2>
        </div>
        {canIssue ? (
          <Button type="button" variant="outline" size="sm" onClick={issue} loading={loading}>
            {challenge ? "Refresh challenge" : "Issue challenge"}
          </Button>
        ) : null}
      </div>

      {challenge ? (
        <div className="mm-seller-facts">
          <div className="mm-seller-fact">
            <dt>Challenge code</dt>
            <dd className="mm-mono-note"><strong>{challenge.code}</strong></dd>
          </div>
          <div className="mm-seller-fact">
            <dt>Status</dt>
            <dd>{challenge.status ?? "active"}</dd>
          </div>
          {challenge.issued_at ? (
            <div className="mm-seller-fact">
              <dt>Issued</dt>
              <dd>{formatDateTime(challenge.issued_at)}</dd>
            </div>
          ) : null}
          {challenge.expires_at ? (
            <div className="mm-seller-fact">
              <dt>Expires</dt>
              <dd>{formatDateTime(challenge.expires_at)}</dd>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="mm-empty">
          No active provenance challenge. Issue a code, display it on the device, then upload the provenance photo for the matching requirement.
        </p>
      )}
      <p className="mm-mono-note">
        Upload a clear photo showing this code on the device/screen for the <code>provenance</code> requirement. Codes are single-use and time-limited.
      </p>
      {error ? <Alert message={error} /> : null}
    </section>
  );
}
