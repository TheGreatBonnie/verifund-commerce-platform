import type { Blocker } from "@/lib/seller-types";

function ownerLabel(owner?: string | null): string {
  switch (owner) {
    case "seller":
      return "Seller action";
    case "reviewer":
      return "Reviewer";
    case "buyer":
      return "Buyer";
    case "system":
      return "System";
    case "none":
      return "No action";
    default:
      return owner ? owner.replaceAll("_", " ") : "Action required";
  }
}

export function BlockersPanel({ blockers }: { blockers: Blocker[] }) {
  if (!blockers?.length) return null;
  return (
    <section className="mm-panel" aria-label="Blockers">
      <div className="mm-panel-head">
        <div>
          <p className="mm-kicker">Release readiness</p>
          <h2>Blockers</h2>
        </div>
        <span className="mm-status is-amber">{blockers.length} open</span>
      </div>
      <ul className="mm-seller-submissions">
        {blockers.map((blocker, idx) => (
          <li key={`${blocker.code}-${blocker.requirement_id ?? idx}`}>
            <div className="mm-seller-submission-main">
              <span className="mm-seller-submission-type">{blocker.code}</span>
              <span className="mm-seller-submission-name">{blocker.message}</span>
              <span className="mm-seller-submission-meta">
                {ownerLabel(blocker.action_owner)}
                {blocker.requirement_id ? ` · ${blocker.requirement_id}` : ""}
                {blocker.severity ? ` · ${blocker.severity}` : ""}
              </span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
