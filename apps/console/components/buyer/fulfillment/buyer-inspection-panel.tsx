import type { BuyerInspection } from "@/lib/buyer-transaction-types";

export function BuyerInspectionPanel({ inspection }: { inspection: BuyerInspection | null }) {
  return (
    <section className="mm-panel" aria-label="Inspection">
      <h2>Inspection</h2>
      {!inspection ? (
        <p className="mm-muted">No inspection record available.</p>
      ) : (
        <dl>
          <div>
            <dt>Status</dt>
            <dd>{inspection.status ?? "unknown"}</dd>
          </div>
          <div>
            <dt>Deadline</dt>
            <dd>{inspection.deadline_at ?? inspection.deadline ?? "—"}</dd>
          </div>
          <div>
            <dt>Outcome</dt>
            <dd>{inspection.outcome ?? "—"}</dd>
          </div>
        </dl>
      )}
    </section>
  );
}
