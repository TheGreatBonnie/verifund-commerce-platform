"use client";

import { evidenceCounts } from "@/lib/format";
import type { SettlementProjection } from "@/lib/types";

export function EvidenceSummaryLines({
  projection,
}: {
  projection: Partial<SettlementProjection> | null;
}) {
  if (!projection) return null;
  const counts = evidenceCounts(projection.evidence);
  const reasons = (projection.verification?.reasons ?? []) as string[];
  return (
    <div className="mm-evidence-summary">
      <p>
        {counts
          ? `${counts.received}/${counts.required} required evidence items received`
          : "No evidence has been reported."}
      </p>
      {projection.verification ? (
        <p>
          Verification: {projection.verification.status}
          {reasons.length ? ` · ${reasons.join(", ")}` : ""}
        </p>
      ) : null}
    </div>
  );
}
