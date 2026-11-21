import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { labelize } from "../shared/format";

export function DisputesPanel({
  disputes,
}: {
  disputes?: Array<Record<string, any>> | null;
}) {
  const items = Array.isArray(disputes) ? disputes : [];
  if (items.length === 0) return null;

  return (
    <section className="mm-panel" aria-label="Disputes">
      <h2>Disputes</h2>
      <ul className="mm-buyer-dispute-list">
        {items.map((dispute, index) => {
          const reason =
            typeof dispute?.reason_code === "string" ? dispute.reason_code : null;
          const status = typeof dispute?.status === "string" ? dispute.status : null;
          return (
            <li key={dispute?.dispute_id ?? dispute?.id ?? index}>
              <span className="mm-buyer-dispute-claim">
                {dispute?.claim ?? "No claim text provided"}
              </span>
              {reason ? (
                <BuyerStatusPill value={reason} label={labelize(reason)} />
              ) : null}
              {status ? (
                <BuyerStatusPill value={status} label={labelize(status)} />
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
