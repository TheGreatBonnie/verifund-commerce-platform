"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpRight, RefreshCw, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRegistry } from "@/features/sellers/use-registry";
import { formatDateTime, shortId } from "@/lib/format";

type HealthFilter = "all" | "healthy" | "unhealthy";
type SortOrder = "name" | "status" | "recent";

export default function SellersPage() {
  const { sellers, isLoading, isRefreshing, error, refresh } = useRegistry();
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All categories");
  const [health, setHealth] = useState<HealthFilter>("all");
  const [sort, setSort] = useState<SortOrder>("name");

  const categories = useMemo(
    () => [...new Set(sellers.flatMap((seller) => seller.categories))].sort(),
    [sellers],
  );
  const visibleSellers = useMemo(() => {
    const search = query.trim().toLowerCase();
    return sellers
      .filter((seller) => {
        const matchesQuery = [
          seller.name,
          seller.seller_id,
          seller.card_url,
          ...seller.categories,
        ].join(" ").toLowerCase().includes(search);
        const matchesCategory = category === "All categories" || seller.categories.includes(category);
        const matchesHealth = health === "all" || seller.healthy === (health === "healthy");
        return matchesQuery && matchesCategory && matchesHealth;
      })
      .sort((first, second) => {
        if (sort === "status") return Number(second.healthy) - Number(first.healthy) || first.name.localeCompare(second.name);
        if (sort === "recent") return Date.parse(second.last_seen_at) - Date.parse(first.last_seen_at);
        return first.name.localeCompare(second.name);
      });
  }, [category, health, query, sellers, sort]);

  const healthyCount = sellers.filter((seller) => seller.healthy).length;
  const unavailableCount = sellers.length - healthyCount;

  return (
    <div className="mm-sellers-page">
      <header className="mm-sellers-header">
        <div>
          <p className="mm-kicker">Agent Card index</p>
          <h1>Sellers</h1>
          <p>Browse seller agents, their commerce capabilities, and connection health.</p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void refresh()}
          disabled={isRefreshing}
          leftIcon={<RefreshCw size={13} className={isRefreshing ? "is-spinning" : ""} aria-hidden="true" />}
        >
          Refresh registry
        </Button>
      </header>

      <section className="mm-seller-stats" aria-label="Seller registry summary">
        <div><span>Total sellers</span><strong>{sellers.length}</strong></div>
        <div><span>Available</span><strong className="is-healthy">{healthyCount}</strong></div>
        <div><span>Unavailable</span><strong className={unavailableCount ? "is-unhealthy" : ""}>{unavailableCount}</strong></div>
      </section>

      {error ? <p className="mm-sellers-alert" role="alert">{error}</p> : null}

      <section className="mm-seller-directory" aria-label="Seller directory">
        <div className="mm-seller-directory-toolbar">
          <label className="mm-seller-search">
            <Search size={14} aria-hidden="true" />
            <span className="sr-only">Search seller name, ID, category, or URL</span>
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search sellers, categories, or Agent Card URLs…"
            />
          </label>
          <label className="mm-seller-select">
            <span className="sr-only">Filter by category</span>
            <select value={category} onChange={(event) => setCategory(event.target.value)}>
              <option>All categories</option>
              {categories.map((item) => <option key={item}>{item}</option>)}
            </select>
          </label>
          <label className="mm-seller-select">
            <span className="sr-only">Filter by health status</span>
            <select value={health} onChange={(event) => setHealth(event.target.value as HealthFilter)}>
              <option value="all">All statuses</option>
              <option value="healthy">Available</option>
              <option value="unhealthy">Unavailable</option>
            </select>
          </label>
          <label className="mm-seller-select">
            <span className="sr-only">Sort sellers</span>
            <select value={sort} onChange={(event) => setSort(event.target.value as SortOrder)}>
              <option value="name">Name A–Z</option>
              <option value="status">Available first</option>
              <option value="recent">Recently seen</option>
            </select>
          </label>
        </div>

        <div className="mm-seller-results" aria-live="polite">
          <span>Showing <strong>{visibleSellers.length}</strong> of {sellers.length} sellers</span>
          <span>{isRefreshing ? "Updating registry…" : "Registry data refreshes every 15 seconds"}</span>
        </div>

        {isLoading ? (
          <div className="mm-seller-card-grid" aria-busy="true" aria-label="Loading sellers">
            {Array.from({ length: 3 }).map((_, index) => <div className="mm-seller-card-skeleton" key={index} />)}
          </div>
        ) : visibleSellers.length ? (
          <div className="mm-seller-card-grid">
            {visibleSellers.map((seller) => {
              const protocol = seller.card_json?.supportedInterfaces?.find((item) => item.protocolVersion)?.protocolVersion ?? "Unknown";
              const skillCount = seller.card_json?.skills?.length ?? 0;
              return (
                <Link
                  className="mm-seller-directory-card"
                  href={`/sellers/${encodeURIComponent(seller.seller_id)}`}
                  key={seller.seller_id}
                >
                  <div className="mm-seller-directory-card-head">
                    <span className={`mm-health-dot ${seller.healthy ? "is-live" : "is-down"}`} aria-hidden="true" />
                    <span className={`mm-seller-health-label ${seller.healthy ? "is-healthy" : "is-unhealthy"}`}>
                      {seller.healthy ? "Available" : "Unavailable"}
                    </span>
                    <ArrowUpRight size={14} aria-hidden="true" />
                  </div>
                  <h2>{seller.name}</h2>
                  <p className="mm-seller-directory-id">{seller.seller_id}</p>
                  <div className="mm-seller-category-chips">
                    {seller.categories.map((item) => <span key={item}>{item}</span>)}
                  </div>
                  <dl className="mm-seller-directory-facts">
                    <div><dt>Protocol</dt><dd>A2A {protocol}</dd></div>
                    <div><dt>Skills</dt><dd>{skillCount}</dd></div>
                    <div><dt>Streaming</dt><dd>{seller.card_json?.capabilities?.streaming ? "Enabled" : "Unavailable"}</dd></div>
                    <div><dt>Last seen</dt><dd>{formatDateTime(seller.last_seen_at)}</dd></div>
                  </dl>
                  <p className="mm-seller-directory-url">{shortId(seller.card_url, 48)}</p>
                </Link>
              );
            })}
          </div>
        ) : (
          <div className="mm-seller-directory-empty" role="status">
            <h2>{error ? "Seller registry unavailable" : sellers.length ? "No sellers match these filters" : "No sellers registered yet"}</h2>
            <p>{error ? "Retry the registry request to load registered sellers." : sellers.length ? "Change the search or filters to see more sellers." : "Register an Agent Card to add a seller to the directory."}</p>
          </div>
        )}
      </section>
    </div>
  );
}
