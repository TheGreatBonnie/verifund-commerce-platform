import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { formatDate, labelize } from "../shared/format";

type VerificationRecord = {
  status?: string;
  reasons?: string[];
  checked_at?: string;
  [key: string]: any;
};

export function VerificationPanel({
  verification,
}: {
  verification?: VerificationRecord | VerificationRecord[] | null;
}) {
  const records: VerificationRecord[] = Array.isArray(verification)
    ? verification
    : verification && typeof verification === "object"
      ? [verification]
      : [];

  if (records.length === 0) {
    return (
      <section className="mm-panel" aria-label="Verification">
        <h2>Verification</h2>
        <p className="mm-muted">No verification results yet.</p>
      </section>
    );
  }

  return (
    <section className="mm-panel" aria-label="Verification">
      <h2>Verification</h2>
      <div className="mm-buyer-section-stack">
        {records.map((record, index) => {
          const status = typeof record?.status === "string" ? record.status : null;
          const reasons = Array.isArray(record?.reasons) ? record.reasons : [];
          return (
            <div className="mm-buyer-verification" key={index}>
              {status ? (
                <BuyerStatusPill value={status} label={labelize(status)} />
              ) : null}
              {reasons.length > 0 ? (
                <ul className="mm-buyer-reason-list">
                  {reasons.map((reason, i) => (
                    <li key={i}>{String(reason)}</li>
                  ))}
                </ul>
              ) : null}
              {typeof record?.checked_at === "string" ? (
                <p className="mm-muted">Checked {formatDate(record.checked_at)}</p>
              ) : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
