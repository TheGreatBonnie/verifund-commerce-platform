import Link from "next/link";
import { SellerPageHeader } from "@/components/seller/seller-page-header";
import { TransactionStatusBadge } from "@/components/seller/seller-status-badge";
import { Alert } from "@/components/ui/alert";
import { EmptyState } from "@/components/ui/empty-state";
import { loadSeller } from "@/lib/seller-api";
import { transactionProduct } from "@/lib/seller-evidence";
import { money } from "@/lib/format";
import type { SellerTransactionList } from "@/lib/seller-types";

export const dynamic = "force-dynamic";

function stateFilterLabel(state: string): string {
  return state.replaceAll("_", " ").toLowerCase();
}

export default async function SellerOrdersPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const query = await searchParams;
  const state =
    typeof query.state === "string" && query.state ? query.state : undefined;
  const path = state
    ? `/seller/transactions?limit=100&state=${encodeURIComponent(state)}`
    : "/seller/transactions?limit=100";
  const result = await loadSeller<SellerTransactionList>(path);

  if (!result.ok) {
    return (
      <>
        <SellerPageHeader
          eyebrow="Sales"
          title="Orders"
          description="Approved transactions and their fulfillment lifecycle."
        />
        <Alert message={result.error} />
      </>
    );
  }

  const { items, counts_by_state: counts } = result.data;
  const activeStates = Object.entries(counts)
    .filter(([, n]) => n > 0)
    .map(([key]) => key);

  return (
    <>
      <SellerPageHeader
        eyebrow="Sales"
        title="Orders"
        description="Approved transactions and their fulfillment lifecycle."
      />

      <nav className="mm-seller-filter-bar" aria-label="Filter by state">
        <Link
          href="/seller/orders"
          aria-current={!state ? "page" : undefined}
          className={!state ? "is-active" : undefined}
        >
          All
          <span>{items.length}</span>
        </Link>
        {activeStates.map((key) => (
          <Link
            key={key}
            href={`/seller/orders?state=${encodeURIComponent(key)}`}
            aria-current={state === key ? "page" : undefined}
            className={state === key ? "is-active" : undefined}
          >
            {stateFilterLabel(key)}
            <span>{counts[key]}</span>
          </Link>
        ))}
      </nav>

      {items.length === 0 ? (
        <EmptyState
          title={state ? `No orders in ${stateFilterLabel(state)}` : "No orders yet"}
          body={
            state
              ? "No orders are in this state. Clear the filter to see every order."
              : "Approved transactions will appear here once an award is agreed."
          }
          action={
            state ? (
              <Link href="/seller/orders" className="mm-button mm-button-outline">
                View all orders
              </Link>
            ) : (
              <Link href="/seller/dashboard" className="mm-button mm-button-outline">
                Back to dashboard
              </Link>
            )
          }
        />
      ) : (
        <section className="mm-panel mm-seller-table-panel" aria-label="Orders">
          <div className="mm-table-scroll">
            <table className="mm-seller-table">
              <thead>
                <tr>
                  <th scope="col">Transaction</th>
                  <th scope="col">Order</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Evidence</th>
                  <th scope="col">Status</th>
                  <th scope="col">
                    <span className="sr-only">Open</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.transaction_id}>
                    <th scope="row" className="mm-seller-table-id">
                      <Link
                        href={`/seller/fulfillment/${encodeURIComponent(item.transaction_id)}`}
                      >
                        {item.transaction_id}
                      </Link>
                    </th>
                    <td>{transactionProduct(item)}</td>
                    <td className="mm-numeric">{money(item.amount_cents)}</td>
                    <td className="mm-numeric">
                      {item.evidence.submitted}/{item.evidence.required}
                    </td>
                    <td>
                      <TransactionStatusBadge state={item.state} />
                    </td>
                    <td>
                      <Link
                        href={`/seller/fulfillment/${encodeURIComponent(item.transaction_id)}`}
                        aria-label={`Open ${item.transaction_id}`}
                        className="mm-seller-row-link"
                      >
                        Open
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
