import Link from "next/link";

export function FulfillmentSummary({
  transactionId,
  fulfillment,
}: {
  transactionId: string;
  fulfillment?: { status?: string | null; next_action?: string | null } | null;
}) {
  return (
    <section className="mm-panel" aria-label="Fulfillment summary">
      <h2>Fulfillment</h2>
      <p>Status: {fulfillment?.status ?? "Unavailable"}</p>
      {fulfillment?.next_action ? <p>Next action: {fulfillment.next_action}</p> : null}
      <Link href={`/fulfillment/${encodeURIComponent(transactionId)}`}>View fulfillment</Link>
    </section>
  );
}
