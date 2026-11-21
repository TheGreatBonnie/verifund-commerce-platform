"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { BuyerFilters } from "@/components/buyer/shared/buyer-filters";
import { BuyerOverviewCards } from "@/components/buyer/shared/buyer-overview-cards";
import {
  BuyerErrorState,
  BuyerPageSkeleton,
} from "@/components/buyer/shared/buyer-page-states";
import { TransactionList } from "@/components/buyer/transactions/transaction-list";
import {
  type ApiError,
  listBuyerTransactions,
} from "@/lib/buyer-transaction-api";
import { distinctOptions, filterParamsFromSearch } from "@/lib/buyer-list-filters";
import type { BuyerTransactionListResponse } from "@/lib/buyer-transaction-types";

export default function TransactionsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const [data, setData] = useState<BuyerTransactionListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const filters = useMemo(
    () => filterParamsFromSearch(searchParams),
    [searchParams],
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await listBuyerTransactions(filters));
    } catch (e) {
      setError((e as ApiError)?.message ?? "Failed to load transactions");
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    void load();
  }, [load]);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams.toString());
    if (value) next.set(key, value);
    else next.delete(key);
    const query = next.toString();
    router.replace(query ? `${pathname}?${query}` : pathname);
  };

  if (loading) return <BuyerPageSkeleton label="Loading transactions" />;
  if (error) return <BuyerErrorState message={error} onRetry={() => void load()} />;

  return (
    <main className="mm-page" aria-label="Transactions">
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Buyer workspace</p>
          <h1>Transactions</h1>
          <p className="mm-muted">
            Commercial and financial records for your purchases.
          </p>
        </div>
      </header>

      {data ? (
        <>
          <section className="mm-panel" aria-label="Overview">
            <div className="mm-buyer-panel-head">
              <h2>Overview</h2>
            </div>
            <BuyerOverviewCards aggregates={data.aggregates} />
          </section>

          <section className="mm-panel" aria-label="Transaction list">
            <div className="mm-buyer-panel-head">
              <h2>Transactions</h2>
            </div>
            <BuyerFilters
              values={filters}
              onChange={setFilter}
              fields={[
                {
                  key: "status",
                  label: "Status",
                  options: distinctOptions(data.items.map((i) => i.transaction_status)),
                },
                {
                  key: "payment_status",
                  label: "Payment",
                  options: distinctOptions(data.items.map((i) => i.payment_status)),
                },
                {
                  key: "fulfillment_status",
                  label: "Fulfillment",
                  options: distinctOptions(data.items.map((i) => i.fulfillment_status)),
                },
              ]}
            />
            <TransactionList items={data.items} />
          </section>
        </>
      ) : null}
    </main>
  );
}
