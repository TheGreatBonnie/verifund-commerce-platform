import { evidencePercent } from "@/lib/seller-status";
import type { SellerEvidenceCount } from "@/lib/seller-types";

export function EvidenceProgress({
  count,
  showLabel = true,
}: {
  count?: SellerEvidenceCount | null;
  showLabel?: boolean;
}) {
  const required = count?.required ?? 0;
  const submitted = count?.submitted ?? 0;
  const percent = evidencePercent(count);
  return (
    <div className="mm-seller-progress">
      {showLabel ? (
        <div className="mm-seller-progress-label">
          <span>
            {submitted}/{required} required inputs submitted
          </span>
          <span>{required === 0 ? "None required" : count?.complete ? "Complete" : "Open"}</span>
        </div>
      ) : null}
      <div
        className="mm-seller-progress-track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
        aria-valuetext={`${submitted} of ${required} required inputs submitted`}
        aria-label="Required evidence submissions"
      >
        <span style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}
