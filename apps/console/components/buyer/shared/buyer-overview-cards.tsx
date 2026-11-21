import { labelize } from "./format";

export { labelize };

export function BuyerOverviewCards({
  aggregates,
  emptyMessage = "Aggregate counts unavailable.",
  label = "Overview",
}: {
  aggregates?: Record<string, number> | null;
  emptyMessage?: string;
  label?: string;
}) {
  const entries = aggregates ? Object.entries(aggregates) : [];

  return (
    <div className="mm-buyer-overview-grid" aria-label={label}>
      {entries.length === 0 ? (
        <p className="mm-muted">{emptyMessage}</p>
      ) : (
        entries.map(([key, value]) => (
          <div className="mm-buyer-stat" key={key}>
            <span className="mm-buyer-stat-label">{labelize(key)}</span>
            <span className="mm-buyer-stat-value">{value}</span>
          </div>
        ))
      )}
    </div>
  );
}
