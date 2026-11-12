export function BlockersPanel({
  blockers,
}: {
  blockers: Array<{ code: string; message?: string; owner?: string }>;
}) {
  if (!blockers?.length) return null;
  return (
    <section className="mm-panel mm-panel-warning" aria-label="Blockers">
      <h2>Blockers</h2>
      <ul>
        {blockers.map((b, i) => (
          <li key={`${b.code}-${i}`}>
            <strong>{b.code}</strong>
            {b.owner ? ` (${b.owner})` : ""}: {b.message ?? "Action required"}
          </li>
        ))}
      </ul>
    </section>
  );
}
