import Link from "next/link";

export function TransactionReference({ transactionId }: { transactionId: string }) {
  return (
    <div className="mm-panel" aria-label="Transaction reference">
      <p className="mm-kicker">Transaction</p>
      <p>
        <Link href={`/transactions/${encodeURIComponent(transactionId)}`}>
          View transaction {transactionId}
        </Link>
      </p>
    </div>
  );
}
