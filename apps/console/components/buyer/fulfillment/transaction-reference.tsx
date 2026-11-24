import Link from "next/link";

import { BuyerStatusPill } from "../shared/buyer-status-pill";
import { labelize } from "../shared/format";

export function TransactionReference({
  transactionId,
  status,
  paymentStatus,
  amount,
}: {
  transactionId: string;
  status?: string | null;
  paymentStatus?: string | null;
  amount?: string | null;
}) {
  return (
    <div className="mm-buyer-transaction-ref" aria-label="Transaction reference">
      <p className="mm-kicker">Transaction</p>
      <Link href={`/transactions/${encodeURIComponent(transactionId)}`}>
        {transactionId}
      </Link>
      {amount ? <p className="mm-buyer-ref-amount">{amount}</p> : null}
      <div className="mm-buyer-inline-actions">
        {status ? <BuyerStatusPill value={status} label={labelize(status)} /> : null}
        {paymentStatus ? (
          <BuyerStatusPill value={paymentStatus} label={labelize(paymentStatus)} />
        ) : null}
      </div>
    </div>
  );
}
