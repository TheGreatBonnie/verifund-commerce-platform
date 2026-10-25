"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  Box,
  Copy,
  ExternalLink,
  RefreshCw,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useRegistry } from "@/features/sellers/use-registry";
import { fetchSellerDashboard } from "@/lib/api";
import { formatDateTime, shortId } from "@/lib/format";

function currency(cents: number, code = "USD") {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: code,
  }).format(cents / 100);
}

function Section({
  title,
  eyebrow,
  action,
  children,
}: {
  title: string;
  eyebrow?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="mm-panel mm-seller-detail-section">
      <header className="mm-panel-head">
        <div>
          {eyebrow ? <p className="mm-kicker">{eyebrow}</p> : null}
          <h2>{title}</h2>
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

export default function SellerDetailPage() {
  const params = useParams();
  const sellerId = typeof params?.sellerId === "string" ? params.sellerId : "";
  const { sellers, isLoading: registryLoading, error: registryError, refresh: refreshRegistry } = useRegistry();
  const seller = sellers.find((item) => item.seller_id === sellerId);
  const dashboardQuery = useQuery({
    queryKey: ["seller-dashboard", sellerId],
    queryFn: () => fetchSellerDashboard(sellerId),
    enabled: Boolean(sellerId),
    staleTime: 10_000,
  });
  const dashboard = dashboardQuery.data;
  const supportedInterfaces = seller?.card_json?.supportedInterfaces ?? [];
  const skills = seller?.card_json?.skills ?? [];
  const securitySchemes = Object.keys(seller?.card_json?.securitySchemes ?? {});

  const refreshAll = async () => {
    await Promise.all([refreshRegistry(), dashboardQuery.refetch()]);
  };

  const copyCardUrl = async () => {
    if (!seller) return;
    await navigator.clipboard.writeText(seller.card_url);
  };

  if (!seller && registryLoading) {
    return <div className="mm-seller-detail-loading" aria-busy="true">Loading seller details…</div>;
  }

  if (!seller) {
    return (
      <div className="mm-seller-detail-page">
        <Link href="/sellers" className="mm-run-back-link"><ArrowLeft size={13} aria-hidden="true" /> Sellers</Link>
        <section className="mm-seller-detail-empty" role={registryError ? "alert" : "status"}>
          <h1>{registryError ? "Seller registry unavailable" : "Seller not found"}</h1>
          <p>{registryError ?? `No registered seller matches “${sellerId}”.`}</p>
          <Button variant="outline" size="sm" onClick={() => void refreshRegistry()} leftIcon={<RefreshCw size={13} aria-hidden="true" />}>
            Retry registry
          </Button>
        </section>
      </div>
    );
  }

  const commerceExtension = seller.card_json?.capabilities?.extensions?.find((item) => item.uri?.includes("/commerce/"));

  return (
    <div className="mm-seller-detail-page">
      <Link href="/sellers" className="mm-run-back-link"><ArrowLeft size={13} aria-hidden="true" /> Sellers</Link>

      <header className="mm-seller-detail-header">
        <div>
          <p className="mm-kicker">Seller profile · Agent Card index</p>
          <h1>{seller.name}</h1>
          <p className="mm-seller-detail-id">{seller.seller_id}</p>
        </div>
        <div className="mm-seller-detail-actions">
          <span className={`mm-seller-health-pill ${seller.healthy ? "is-healthy" : "is-unhealthy"}`}>
            <span className={`mm-health-dot ${seller.healthy ? "is-live" : "is-down"}`} aria-hidden="true" />
            {seller.healthy ? "Available" : "Unavailable"}
          </span>
          <Button type="button" variant="outline" size="sm" onClick={() => void refreshAll()} disabled={dashboardQuery.isFetching} leftIcon={<RefreshCw size={13} className={dashboardQuery.isFetching ? "is-spinning" : ""} aria-hidden="true" />}>
            Refresh details
          </Button>
        </div>
      </header>

      {seller.last_error ? <p className="mm-sellers-alert" role="status">Last health check: {seller.last_error}</p> : null}

      <div className="mm-seller-detail-grid">
        <div className="mm-seller-detail-main">
          <Section title="Pricing & product" eyebrow="Current catalog">
            {dashboard ? (
              <>
                <div className="mm-seller-price-highlight">
                  <div><span>Listed unit price</span><strong>{currency(dashboard.pricing.list_unit_price_cents, dashboard.pricing.currency)}</strong></div>
                  <div><span>Product</span><strong>{dashboard.pricing.product_name}</strong></div>
                  <div><span>SKU</span><strong>{dashboard.pricing.sku}</strong></div>
                </div>
                <dl className="mm-seller-detail-facts">
                  <div><dt>Base warranty</dt><dd>{dashboard.pricing.base_warranty_months} months</dd></div>
                  <div><dt>Returns</dt><dd>{dashboard.pricing.returns_days} days</dd></div>
                  <div><dt>Standard delivery</dt><dd>{dashboard.pricing.delivery_days} days</dd></div>
                  <div><dt>Rating</dt><dd>{dashboard.pricing.rating.toFixed(1)} / 5</dd></div>
                </dl>
                <div className="mm-seller-warranty-options">
                  <span className="mm-kicker">Warranty options</span>
                  <div>{Object.entries(dashboard.pricing.warranty_addons_cents).map(([months, addon]) => <span key={months}>{months} mo · {addon ? `+${currency(addon, dashboard.pricing.currency)}` : "included"}</span>)}</div>
                </div>
                {dashboard.products.length > 1 ? (
                  <div className="mm-seller-catalog-list">
                    <span className="mm-kicker">Full catalog · {dashboard.products.length} products</span>
                    {dashboard.products.map((product) => (
                      <div key={product.sku}>
                        <span><strong>{product.product_name}</strong><small>{product.sku} · {product.stock.on_hand} in stock</small></span>
                        <strong>{currency(product.list_unit_price_cents, product.currency)}</strong>
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : <DashboardSectionState loading={dashboardQuery.isLoading} error={dashboardQuery.error} onRetry={() => void dashboardQuery.refetch()} />}
          </Section>

          <Section title="Recent offers" eyebrow="Negotiation activity">
            {!dashboard ? <DashboardSectionState loading={dashboardQuery.isLoading} error={dashboardQuery.error} onRetry={() => void dashboardQuery.refetch()} /> : dashboard.recent_offers.length ? (
              <div className="mm-seller-table-scroll">
                <table className="mm-seller-data-table">
                  <thead><tr><th>Offer</th><th>Product / quantity</th><th>Total</th><th>Status</th><th>Created</th></tr></thead>
                  <tbody>{dashboard.recent_offers.map(({ offer, created_at }) => (
                    <tr key={offer.offer_id}>
                      <td className="mm-seller-mono">{shortId(offer.offer_id, 14)}</td>
                      <td>{offer.line_items.map((line) => `${line.quantity} × ${line.name}`).join(", ")}</td>
                      <td>{currency(offer.total_cents, offer.currency)}</td>
                      <td><span className="mm-seller-status-tag">{offer.status}</span></td>
                      <td>{formatDateTime(created_at)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : <p className="mm-seller-no-activity">No offers recorded yet.</p>}
          </Section>

          <Section title="Recent orders" eyebrow="Fulfillment">
            {!dashboard ? <DashboardSectionState loading={dashboardQuery.isLoading} error={dashboardQuery.error} onRetry={() => void dashboardQuery.refetch()} /> : dashboard.recent_orders.length ? (
              <div className="mm-seller-table-scroll">
                <table className="mm-seller-data-table">
                  <thead><tr><th>Order</th><th>Quantity</th><th>Total</th><th>Fulfillment</th><th>ETA</th></tr></thead>
                  <tbody>{dashboard.recent_orders.map(({ order }) => (
                    <tr key={order.order_id}>
                      <td className="mm-seller-mono">{shortId(order.order_id, 14)}</td>
                      <td>{order.quantity}</td>
                      <td>{currency(order.total_cents, order.currency)}</td>
                      <td><span className="mm-seller-status-tag">{order.fulfillment.status}</span></td>
                      <td>{formatDateTime(order.eta)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            ) : <p className="mm-seller-no-activity">No orders recorded yet.</p>}
          </Section>
        </div>

        <aside className="mm-seller-detail-rail">
          <Section title="Availability" eyebrow="Live inventory">
            {dashboard ? (
              <div className="mm-seller-stock-grid">
                <div><Box size={15} aria-hidden="true" /><span>On hand</span><strong>{dashboard.stock.on_hand}</strong></div>
                <div><Truck size={15} aria-hidden="true" /><span>Incoming</span><strong>{dashboard.stock.incoming}</strong></div>
                <p>{dashboard.stock.incoming_days == null ? "No incoming shipment scheduled." : `Incoming stock expected in ${dashboard.stock.incoming_days} days.`}</p>
              </div>
            ) : <DashboardSectionState loading={dashboardQuery.isLoading} error={dashboardQuery.error} onRetry={() => void dashboardQuery.refetch()} />}
          </Section>

          <Section title="Categories & capabilities" eyebrow="Discovery profile">
            <div className="mm-seller-detail-categories">{seller.categories.map((category) => <span key={category}>{category}</span>)}</div>
            <dl className="mm-seller-detail-facts mm-seller-capability-facts">
              <div><dt>Card version</dt><dd>{seller.card_json?.version ?? "—"}</dd></div>
              <div><dt>Protocol</dt><dd>{supportedInterfaces.find((item) => item.protocolVersion)?.protocolVersion ?? "—"}</dd></div>
              <div><dt>Streaming</dt><dd>{seller.card_json?.capabilities?.streaming ? "Supported" : "Not supported"}</dd></div>
              <div><dt>Last seen</dt><dd>{formatDateTime(seller.last_seen_at)}</dd></div>
            </dl>
            {commerceExtension ? <div className="mm-seller-extension-note"><ShieldCheck size={13} aria-hidden="true" /><span>Commerce extension verified{commerceExtension.required ? " · required" : ""}</span></div> : null}
            <div className="mm-seller-skills">
              <span className="mm-kicker">Agent skills</span>
              {skills.length ? <ul>{skills.map((skill) => <li key={skill.id ?? skill.name}>{skill.name ?? skill.id}<small>{skill.description}</small></li>)}</ul> : <p>No skills declared in the Agent Card.</p>}
            </div>
          </Section>

          <Section title="Agent Card" eyebrow="Connection details">
            <dl className="mm-seller-detail-facts mm-seller-card-facts">
              <div><dt>Card URL</dt><dd className="mm-seller-break">{seller.card_url}</dd></div>
              <div><dt>Card hash</dt><dd className="mm-seller-mono mm-seller-break">{seller.card_hash}</dd></div>
              <div><dt>Security schemes</dt><dd>{securitySchemes.length ? securitySchemes.join(", ") : "None declared"}</dd></div>
            </dl>
            <div className="mm-seller-card-actions">
              <Button type="button" variant="outline" size="sm" onClick={() => void copyCardUrl()} leftIcon={<Copy size={12} aria-hidden="true" />}>Copy URL</Button>
              <a href={`/api/registry/sellers/${encodeURIComponent(seller.seller_id)}/card`} target="_blank" rel="noreferrer" className="mm-button mm-button-outline mm-button-sm">
                Open card <ExternalLink size={12} aria-hidden="true" />
              </a>
            </div>
            <p className="mm-seller-detail-description">{seller.card_json?.description ?? "No Agent Card description provided."}</p>
            <p className="mm-seller-provider">Provider: {seller.card_json?.provider?.organization ?? seller.name}</p>
          </Section>
        </aside>
      </div>
    </div>
  );
}

function DashboardSectionState({
  loading,
  error,
  onRetry,
}: {
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
}) {
  if (loading) return <p className="mm-seller-section-state" aria-busy="true">Loading seller data…</p>;
  if (error) {
    return (
      <div className="mm-seller-section-error" role="alert">
        <p>{error.message || "Seller data is unavailable."}</p>
        <button type="button" className="mm-text-button" onClick={onRetry}>Retry</button>
      </div>
    );
  }
  return <p className="mm-seller-section-state">Seller data is not available.</p>;
}
