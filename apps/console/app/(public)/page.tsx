"use client";

import { useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  CircleDollarSign,
  Handshake,
  Search,
  ShieldCheck,
  ShoppingBag,
  Truck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { orders } from "@/lib/data";
import { fetchMarketplaceProducts } from "@/lib/api";
import type { MarketplaceProduct } from "@/lib/types";
import { useRuns } from "@/features/runs/use-runs";
import { RunSummaryCard } from "@/features/runs/run-summary-card";

const SAMPLE_BRIEF =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

type HomeProduct = {
  id: string;
  name: string;
  category: string;
  desc: string;
  emoji: string;
  tag: string;
  color: string;
  price: number;
  original: number;
  rating: string;
  reviews: string;
  seller: string;
};

function toHomeProduct(product: MarketplaceProduct): HomeProduct {
  const offer = product.offers?.[0];
  return {
    id: product.id,
    name: product.name,
    category: product.category,
    desc: product.description,
    emoji: product.image_emoji ?? "📦",
    tag: product.tag ?? "Available",
    color: product.color ?? "#eef2ed",
    price: Math.round((product.unit_price_cents ?? 0) / 100),
    original: Math.round((product.original_unit_price_cents ?? 0) / 100),
    rating: String(product.rating ?? ""),
    reviews: String(product.reviews ?? ""),
    seller: product.seller ?? offer?.seller_name ?? "",
  };
}

const capabilities = [
  {
    title: "Agentic discovery",
    body: "Search seller agents using the requirements you actually care about.",
    icon: Search,
    tone: "discovery",
  },
  {
    title: "Private negotiation",
    body: "Compare structured offers and negotiate terms directly with sellers.",
    icon: Handshake,
    tone: "negotiation",
  },
  {
    title: "Protected payment",
    body: "Keep funds in escrow until the agreed conditions are met.",
    icon: ShieldCheck,
    tone: "escrow",
  },
  {
    title: "Order tracking",
    body: "Follow delivery and fulfillment from award through completion.",
    icon: Truck,
    tone: "delivery",
  },
];

export default function Home() {
  const router = useRouter();
  const { isSignedIn, orgId } = useAuth();
  const { runs } = useRuns({ enabled: isSignedIn === true });
  const recent = runs.slice(0, 3);

  const sellerAccessQuery = useQuery({
    queryKey: ["seller-access", orgId ?? "no-org"],
    queryFn: () =>
      fetch("/api/me/seller-access", { cache: "no-store" }).then(async (r) => {
        if (!r.ok) throw new Error(`seller-access ${r.status}`);
        return (await r.json()) as { access: string; orgId: string | null };
      }),
    enabled: isSignedIn === true && !!orgId,
    staleTime: 30_000,
    retry: false,
  });
  const sellerAccess = sellerAccessQuery.data?.access;
  const isSeller = sellerAccess === "workspace" || sellerAccess === "read_only";
  const isOnboarding = sellerAccess === "onboarding";

  const catalogQuery = useQuery({
    queryKey: ["marketplace-products"],
    queryFn: fetchMarketplaceProducts,
    staleTime: 15_000,
  });
  const products = (catalogQuery.data ?? []).map(toHomeProduct);
  const categories = Array.from(new Set(products.map((product) => product.category)));

  const runSample = () => {
    const threadId = crypto.randomUUID();
    try {
      window.sessionStorage.setItem("marketmesh:pendingBrief", SAMPLE_BRIEF);
    } catch {
      // ignore
    }
    router.push(`/runs/${threadId}`);
  };

  const runProductBrief = (product: (typeof products)[number]) => {
    const brief = [
      `Find and negotiate the best terms for one ${product.name}.`,
      `Product details: ${product.desc}.`,
      `Use the listed price of $${product.price.toLocaleString("en-US")} as my target budget.`,
      "Compare sellers, delivery, warranty, and returns. Do not place an order without my approval.",
    ].join(" ");

    try {
      window.sessionStorage.setItem("marketmesh:pendingBrief", brief);
    } catch {
      // Open the fresh agent run even if session storage is unavailable.
    }
    router.push(`/agents/${crypto.randomUUID()}`);
  };

  return (
    <div className="mm-home mm-home-dashboard">
      <Panel className="mm-dashboard-hero">
        <div className="mm-dashboard-hero-copy">
          <p className="mm-kicker">Agentic Commerce</p>
          <h1 className="mm-home-title">
            Shop Smarter with <em>AI Agents</em>
          </h1>
          <p className="mm-deal-lede">
            Your personal shopping agent finds the best deals, negotiates for
            you, and ensures secure payments through Verifund.
          </p>
          <div className="mm-home-actions">
            <Button onClick={runSample} leftIcon={<ArrowRight size={14} aria-hidden="true" />}>
              Start Shopping
            </Button>
            {isSeller && (
              <Button
                variant="outline"
                onClick={() => router.push("/seller/dashboard")}
                leftIcon={<ShieldCheck size={14} aria-hidden="true" />}
              >
                Open seller dashboard
              </Button>
            )}
            {isOnboarding && (
              <Button
                variant="outline"
                onClick={() => router.push("/seller/onboarding")}
                leftIcon={<ShieldCheck size={14} aria-hidden="true" />}
              >
                Continue seller onboarding
              </Button>
            )}
            <Button variant="outline" onClick={() => router.push("/help")}>
              How It Works
            </Button>
          </div>
        </div>
        <svg
          className="mm-dashboard-illustration"
          viewBox="0 0 480 240"
          role="img"
          aria-labelledby="hero-illustration-title"
          xmlns="http://www.w3.org/2000/svg"
        >
          <title id="hero-illustration-title">
            A buyer agent finds a product, negotiates an offer, and secures payment
          </title>
          <defs>
            <linearGradient id="agent-shell" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="var(--panel)" />
              <stop offset="1" stopColor="var(--paper-green, var(--panel-green))" />
            </linearGradient>
          </defs>

          {/* Soft orbit and glints frame the agent without adding a new palette. */}
          <circle cx="246" cy="111" r="94" fill="none" stroke="var(--rule)" strokeDasharray="3 7" />
          <circle cx="246" cy="111" r="75" fill="none" stroke="var(--rule-strong)" strokeOpacity=".45" />
          <path d="m83 52 4 9 9 4-9 4-4 9-4-9-9-4 9-4 4-9ZM391 42l3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7ZM415 137l3 7 7 3-7 3-3 7-3-7-7-3 7-3 3-7Z" fill="var(--acid)" />

          {/* Offset backing gives the product-and-offer panel a little depth. */}
          <rect x="95" y="97" width="288" height="108" rx="4" fill="var(--paper-deep)" stroke="var(--rule)" />
          <rect x="89" y="91" width="288" height="108" rx="4" fill="var(--panel)" stroke="var(--rule-strong)" />
          <rect x="100" y="102" width="94" height="83" rx="3" fill="var(--panel-green)" stroke="var(--rule)" />
          <text x="147" y="113" fill="var(--muted)" fontFamily="var(--font-spline-sans-mono), monospace" fontSize="5.5" letterSpacing=".6" textAnchor="middle">MATCHED ITEM</text>
          {/* More defined shoe silhouette with layered upper, laces, and sole. */}
          <path d="M108 158c7-2 13-7 18-15l7-12 10 2 9 11c4 5 10 8 18 10l9 7c2 2 1 5-2 6h-57c-8 0-13-3-13-7v-2Z" fill="var(--signal)" />
          <path d="m132 135 5-8 9 2 9 11-10-2-6 6-8-4Z" fill="var(--signal-deep)" />
          <path d="m141 131 8 3m-11 1 8 3m-11 1 7 3" stroke="var(--acid)" strokeWidth="1.5" strokeLinecap="round" />
          <path d="M110 162c13 4 39 4 69 0" fill="none" stroke="var(--acid)" strokeWidth="2" strokeLinecap="round" />
          <path d="M113 169h54" stroke="var(--rule-strong)" strokeLinecap="round" />

          {/* Compact offer summary with consistent check rows. */}
          <text x="211" y="104" fill="var(--muted)" fontFamily="var(--font-spline-sans-mono), monospace" fontSize="5.5" letterSpacing=".6">OFFER CHECK</text>
          <circle cx="211" cy="112" r="5" fill="var(--signal)" />
          <path d="m209 112 2 2 4-5" fill="none" stroke="var(--panel)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="224" y="109" width="103" height="5" rx="2.5" fill="var(--rule-strong)" />
          <circle cx="211" cy="139" r="5" fill="var(--signal)" />
          <path d="m209 139 2 2 4-5" fill="none" stroke="var(--panel)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="224" y="136" width="82" height="5" rx="2.5" fill="var(--rule-strong)" />
          <circle cx="211" cy="166" r="5" fill="var(--acid)" stroke="var(--signal)" />
          <rect x="224" y="163" width="94" height="5" rx="2.5" fill="var(--rule)" />

          {/* Agent head and headset. */}
          <path d="M205 75a41 41 0 0 1 82 0v11h-11V75a30 30 0 0 0-60 0v11h-11V75Z" fill="var(--signal)" />
          <rect x="197" y="72" width="16" height="34" rx="8" fill="var(--signal-deep)" />
          <rect x="279" y="72" width="16" height="34" rx="8" fill="var(--signal-deep)" />
          <circle cx="246" cy="76" r="36" fill="url(#agent-shell)" stroke="var(--signal)" strokeWidth="2" />
          <path d="M225 71c0-7 5-12 12-12h20c7 0 12 5 12 12v11c0 7-5 12-12 12h-20c-7 0-12-5-12-12V71Z" fill="var(--signal)" />
          <circle cx="239" cy="77" r="2.5" fill="var(--panel)" />
          <circle cx="254" cy="77" r="2.5" fill="var(--panel)" />
          <path d="M240 85c3 3 8 3 11 0" fill="none" stroke="var(--panel)" strokeWidth="1.8" strokeLinecap="round" />

          {/* Offer conversation bubble. */}
          <path d="M325 42h89a7 7 0 0 1 7 7v20a7 7 0 0 1-7 7h-21l-11 9v-9h-57a7 7 0 0 1-7-7V49a7 7 0 0 1 7-7Z" fill="var(--panel)" stroke="var(--signal)" strokeWidth="1.5" />
          <path d="M337 56h62M337 64h43" stroke="var(--rule-strong)" strokeWidth="2.5" strokeLinecap="round" />

          {/* Escrow shield. */}
          <path d="m380 111 20 7v16c0 14-9 23-20 29-11-6-20-15-20-29v-16l20-7Z" fill="var(--signal)" />
          <path d="m371 134 6 6 12-13" fill="none" stroke="var(--panel)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />

          {/* Connectors sit behind the stage markers to show the process flow. */}
          <path d="M126 205h57m29 0h58m29 0h58" fill="none" stroke="var(--rule-strong)" strokeWidth="1.2" strokeDasharray="2 4" />
          <path d="m180 202 3 3-3 3m87-6 3 3-3 3m87-6 3 3-3 3" fill="none" stroke="var(--signal)" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />

          {/* Four labeled stages echo the reference illustration. */}
          <g fill="var(--panel)" stroke="var(--rule-strong)">
            <circle cx="111" cy="205" r="14" /><circle cx="198" cy="205" r="14" />
            <circle cx="285" cy="205" r="14" /><circle cx="372" cy="205" r="14" />
          </g>
          <g fill="none" stroke="var(--signal)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="110" cy="204" r="6" /><path d="m115 209 4 4" />
            <path d="M192 202h12M192 206h8M192 210h10" />
            <path d="M279 205h12l-2-6h-8l-2 6Zm0 0 2 5h9" /><circle cx="283" cy="213" r="1" /><circle cx="289" cy="213" r="1" />
            <path d="m372 197 7 3v6c0 5-3 8-7 10-4-2-7-5-7-10v-6l7-3Z" /><path d="m369 206 2 2 4-4" />
          </g>
          <g fill="var(--ink-soft)" fontFamily="var(--font-spline-sans-mono), monospace" fontSize="8" textAnchor="middle">
            <text x="111" y="234">Find</text><text x="198" y="234">Negotiate</text>
            <text x="285" y="234">Buy</text><text x="372" y="234">Secure</text>
          </g>
        </svg>
      </Panel>

      <section className="mm-capabilities" aria-label="How MarketMesh works">
        {capabilities.map(({ title, body, icon: Icon, tone }) => (
          <article className={`mm-capability-card is-${tone}`} key={title}>
            <span className="mm-capability-icon"><Icon size={17} aria-hidden="true" /></span>
            <h2>{title}</h2>
            <p>{body}</p>
          </article>
        ))}
      </section>

      <section className="mm-dashboard-section" aria-labelledby="featured-title">
        <header className="mm-section-head mm-dashboard-section-head">
          <div>
            <p className="mm-kicker">From the sample catalog</p>
            <h2 id="featured-title">Featured products</h2>
          </div>
          <span className="mm-dashboard-section-note">Live seller catalogs</span>
        </header>
        {catalogQuery.isLoading ? (
          <div className="mm-product-grid">
            <div className="mm-marketplace-empty" aria-busy="true">Loading live seller catalogs…</div>
          </div>
        ) : catalogQuery.error ? (
          <div className="mm-product-grid">
            <div className="mm-marketplace-empty" role="alert">
              <h3>Marketplace catalog unavailable</h3>
              <p>{catalogQuery.error.message}</p>
              <Button type="button" variant="outline" size="sm" onClick={() => void catalogQuery.refetch()}>Retry</Button>
            </div>
          </div>
        ) : (
        <div className="mm-product-grid">
          {products.slice(0, 5).map((product) => (
            <article className="mm-product-card" key={product.id}>
              <div className="mm-product-art" style={{ backgroundColor: product.color }} aria-hidden="true">
                <span>{product.emoji}</span>
                <small>{product.tag}</small>
              </div>
              <div className="mm-product-info">
                <p className="mm-product-category">{product.category}</p>
                <h3>{product.name}</h3>
                <p className="mm-product-description">{product.desc}</p>
                <div className="mm-product-price">
                  <strong>${product.price.toLocaleString("en-US")}</strong>
                  <del>${product.original.toLocaleString("en-US")}</del>
                </div>
                <div className="mm-product-meta">
                  <span className="mm-rating"><span aria-hidden="true">★</span> {product.rating} <span>({product.reviews})</span></span>
                  <span>{product.seller}</span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  className="mm-product-action mm-button-signal"
                  onClick={() => runProductBrief(product)}
                  leftIcon={<Handshake size={13} aria-hidden="true" />}
                >
                  Ask agent to negotiate
                </Button>
              </div>
            </article>
          ))}
        </div>
        )}
      </section>

      <section className="mm-dashboard-section" aria-labelledby="categories-title">
        <header className="mm-section-head mm-dashboard-section-head">
          <div>
            <p className="mm-kicker">Browse the catalog</p>
            <h2 id="categories-title">Popular categories</h2>
          </div>
        </header>
        <div className="mm-category-grid">
          {categories.map((category) => {
            const count = products.filter((product) => product.category === category).length;
            return (
              <article className="mm-category-card" key={category}>
                <span className="mm-category-icon"><ShoppingBag size={17} aria-hidden="true" /></span>
                <span>{category}</span>
                <small>{count} products</small>
              </article>
            );
          })}
        </div>
      </section>

      {isSignedIn === true ? (
        <section className="mm-dashboard-section" aria-labelledby="activity-title">
        <header className="mm-section-head mm-dashboard-section-head">
          <div>
            <p className="mm-kicker">Your marketplace</p>
            <h2 id="activity-title">Recent activity</h2>
          </div>
          <button className="mm-text-action" type="button" onClick={() => router.push("/runs")}>
            All runs <ArrowRight size={13} aria-hidden="true" />
          </button>
        </header>
        {recent.length > 0 ? (
          <div className="mm-runs-grid">
            {recent.map((run) => <RunSummaryCard key={run.run_id} run={run} />)}
          </div>
        ) : (
          <div className="mm-activity-list">
            {orders.map((order) => (
              <article className="mm-activity-row" key={order.id}>
                <span className="mm-activity-icon"><CircleDollarSign size={15} aria-hidden="true" /></span>
                <div className="mm-activity-copy">
                  <h3>{order.status === "Delivered" ? "Order delivered" : "Payment secured"}</h3>
                  <p>{order.product} <span>· Order #{order.id}</span></p>
                </div>
                <time>{order.date}</time>
                <span className={`mm-order-status ${order.status === "Delivered" ? "is-delivered" : "is-escrow"}`}>
                  {order.status === "Delivered" ? <Check size={12} aria-hidden="true" /> : <ShieldCheck size={12} aria-hidden="true" />}
                  {order.status}
                </span>
              </article>
            ))}
          </div>
        )}
        </section>
      ) : null}
    </div>
  );
}
