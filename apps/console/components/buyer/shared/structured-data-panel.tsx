import { RawDataDisclosure } from "./raw-data-disclosure";
import { labelize } from "./format";

export function StructuredDataPanel({
  title,
  data,
  rawLabel,
}: {
  title: string;
  data?: Record<string, any> | null;
  rawLabel: string;
}) {
  const entries =
    data && typeof data === "object"
      ? Object.entries(data).filter(
          ([, value]) => value !== null && typeof value !== "object",
        )
      : [];

  return (
    <section className="mm-panel" aria-label={title}>
      <h2>{title}</h2>
      {entries.length > 0 ? (
        <dl className="mm-buyer-fields">
          {entries.map(([key, value]) => (
            <div className="mm-buyer-field" key={key}>
              <dt>{labelize(key)}</dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="mm-muted">No details available.</p>
      )}
      <RawDataDisclosure label={rawLabel} value={data ?? {}} />
    </section>
  );
}
