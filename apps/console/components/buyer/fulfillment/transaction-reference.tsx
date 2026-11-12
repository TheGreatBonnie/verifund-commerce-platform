import Link from "next/link";

export function TransactionReference({ transactionId }: { transactionId: string }) {
  return (
    <div className="mm-buyer-transaction-ref" aria-label="Transaction reference">
      <p className="mm-kicker">Transaction</p>
      <Link href={`/transactions/${encodeURIComponent(transactionId)}`}>
        View transaction {transactionId}
      </Link>
    </div>
  );
}
