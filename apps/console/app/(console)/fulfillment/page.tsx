"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { FulfillmentList } from "@/components/buyer/fulfillment/fulfillment-list";
import { BuyerFilters } from "@/components/buyer/shared/buyer-filters";
import { BuyerOverviewCards } from "@/components/buyer/shared/buyer-overview-cards";
import {
  BuyerErrorState,
  BuyerPageSkeleton,
} from "@/components/buyer/shared/buyer-page-states";
import {
  type ApiError,
  listBuyerTransactions,
} from "@/lib/buyer-transaction-api";
import {
  deriveFulfillmentCounts,
  distinctOptions,
  filterParamsFromSearch,
} from "@/lib/buyer-list-filters";
import type { BuyerTransactionListResponse } from "@/lib/buyer-transaction-types";

export default function FulfillmentListPage() {
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
      setError((e as ApiError)?.message ?? "Failed to load fulfillment records");
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

  const items = (data?.items ?? []).filter(
    (item) =>
      item.fulfillment_status ||
      item.fulfillment?.status ||
      item.next_action ||
      item.fulfillment?.next_action,
  );

  if (loading) return <BuyerPageSkeleton label="Loading fulfillment records" />;
  if (error) return <BuyerErrorState message={error} onRetry={() => void load()} />;

  return (
    <main className="mm-page" aria-label="Fulfillment">
      <header className="mm-page-header">
        <div>
          <p className="mm-kicker">Buyer workspace</p>
          <h1>Fulfillment</h1>
          <p className="mm-muted">
            Operational progress, evidence, shipment, and inspection for your orders.
          </p>
        </div>
      </header>

      {data ? (
        <>
          <section className="mm-panel" aria-label="Overview">
            <div className="mm-buyer-panel-head">
              <h2>Overview</h2>
            </div>
            <BuyerOverviewCards
              label="Overview"
              aggregates={deriveFulfillmentCounts(data.items)}
            />
          </section>

          <section className="mm-panel" aria-label="Fulfillment list">
            <div className="mm-buyer-panel-head">
              <h2>Fulfillment records</h2>
            </div>
            <BuyerFilters
              values={filters}
              onChange={setFilter}
              fields={[
                {
                  key: "fulfillment_status",
                  label: "Fulfillment",
                  options: distinctOptions(
                    data.items.map(
                      (item) => item.fulfillment_status ?? item.fulfillment?.status,
                    ),
                  ),
                },
                {
                  key: "status",
                  label: "Transaction",
                  options: distinctOptions(data.items.map((i) => i.transaction_status)),
                },
              ]}
            />
            <FulfillmentList items={items} />
          </section>
        </>
      ) : null}
    </main>
  );
}
