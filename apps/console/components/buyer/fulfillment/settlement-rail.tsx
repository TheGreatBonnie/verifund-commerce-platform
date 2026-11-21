import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { formatDate, labelize } from "../shared/format";

function eventField(event: Record<string, any>, ...keys: string[]): string | null {
  for (const key of keys) {
    if (typeof event?.[key] === "string") return event[key];
  }
  return null;
}

export function SettlementRail({
  events,
  nextAction,
}: {
  events?: Array<Record<string, any>> | null;
  nextAction?: string | null;
}) {
  const items = Array.isArray(events) ? events : [];

  if (items.length === 0 && !nextAction) {
    return <p className="mm-muted">No settlement activity yet.</p>;
  }

  return (
    <ol className="mm-buyer-settlement-rail" aria-label="Settlement timeline">
      {items.map((event, index) => {
        const type = eventField(event, "type", "event_type", "kind") ?? "event";
        const status = eventField(event, "status", "state");
        const at = eventField(event, "at", "created_at", "timestamp");
        return (
          <li className="mm-buyer-settlement-node" key={`${type}-${index}`}>
            <span className="mm-buyer-settlement-marker" aria-hidden="true" />
            <div className="mm-buyer-settlement-body">
              <span className="mm-buyer-settlement-title">{labelize(type)}</span>
              {status ? <BuyerStatusPill value={status} /> : null}
              {at ? (
                <time className="mm-muted" dateTime={at}>
                  {formatDate(at)}
                </time>
              ) : null}
            </div>
          </li>
        );
      })}
      {nextAction ? (
        <li className="mm-buyer-settlement-node is-next">
          <span className="mm-buyer-settlement-marker" aria-hidden="true" />
          <div className="mm-buyer-settlement-body">
            <span className="mm-buyer-settlement-title">
              Next: {labelize(nextAction)}
            </span>
          </div>
        </li>
      ) : null}
    </ol>
  );
}
