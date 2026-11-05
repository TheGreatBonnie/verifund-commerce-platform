import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { Info } from "lucide-react";
import { SellerPageHeader } from "@/components/seller/seller-page-header";
import { PayoutStatusBadge, TransactionStatusBadge } from "@/components/seller/seller-status-badge";
import { SellerStat, SellerStatGrid } from "@/components/seller/seller-stat";
import { Alert } from "@/components/ui/alert";
import { EmptyState } from "@/components/ui/empty-state";
import { loadSeller } from "@/lib/seller-api";
import { money } from "@/lib/format";
import type { SellerPayoutView } from "@/lib/seller-types";

export const dynamic = "force-dynamic";

export default async function SellerPayoutsPage() {
  await auth.protect();
  const result = await loadSeller<SellerPayoutView>("/seller/payouts");

  if (!result.ok) {
    return (
      <>
        <SellerPageHeader
          eyebrow="Finance"
          title="Payouts"
          description="Payout states for your Verifund transactions."
        />
        <Alert message={result.error} />
      </>
    );
  }

  const { transactions, totals } = result.data;

  return (
    <>
      <SellerPageHeader
        eyebrow="Finance"
        title="Payouts"
        description="Payment capture and seller payout are separate events. A processed buyer payment does not mean funds have been released to you."
      />

      <div className="mm-seller-notice" role="note">
        <Info size={15} aria-hidden="true" />
        <p>
          <strong>Payment processing and seller payout are separate events.</strong>{" "}
          Totals below are computed from payout records only. No funding or
          escrow amounts are implied.
        </p>
      </div>

      <SellerStatGrid>
        <SellerStat
          label="Pending payout"
          value={money(totals.pending_cents)}
          detail="Not yet paid"
          tone={totals.pending_cents ? "amber" : undefined}
        />
        <SellerStat
          label="Paid out"
          value={money(totals.paid_cents)}
          detail="Released to seller"
          tone={totals.paid_cents ? "signal" : undefined}
        />
        <SellerStat
          label="Failed payout"
          value={money(totals.failed_cents)}
          detail="Requires attention"
          tone={totals.failed_cents ? "error" : undefined}
        />
      </SellerStatGrid>

      {transactions.length === 0 ? (
        <EmptyState
          title="No payouts yet"
          body="Payout records appear here once a transaction reaches payout."
        />
      ) : (
        <section className="mm-panel mm-seller-table-panel" aria-label="Transactions">
          <div className="mm-panel-head">
            <div>
              <p className="mm-kicker">Transactions</p>
              <h2>Payout states</h2>
            </div>
          </div>
          <div className="mm-table-scroll">
            <table className="mm-seller-table">
              <thead>
                <tr>
                  <th scope="col">Transaction</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Lifecycle</th>
                  <th scope="col">Payout</th>
                  <th scope="col">
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((entry) => (
                  <tr key={entry.transaction_id}>
                    <th scope="row" className="mm-seller-table-id">
                      <Link
                        href={`/seller/fulfillment/${encodeURIComponent(entry.transaction_id)}`}
                      >
                        {entry.transaction_id}
                      </Link>
                    </th>
                    <td className="mm-numeric">{money(entry.amount_cents)}</td>
                    <td>
                      <TransactionStatusBadge state={entry.state} />
                    </td>
                    <td>
                      <PayoutStatusBadge status={entry.payout?.status} />
                    </td>
                    <td>
                      <Link
                        href={`/seller/fulfillment/${encodeURIComponent(entry.transaction_id)}`}
                        aria-label={`Open ${entry.transaction_id} workspace`}
                        className="mm-seller-row-link"
                      >
                        View
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
