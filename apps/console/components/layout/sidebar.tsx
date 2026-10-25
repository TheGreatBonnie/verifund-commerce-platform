"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ArrowRight, Bot, LayoutDashboard, History, MessageCircle, Store, Settings, HelpCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchRegistry } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";

const NAV = [
  { href: "/", label: "Home", icon: LayoutDashboard },
  { href: "/runs", label: "Runs", icon: History },
  { href: "/sellers", label: "Sellers", icon: Store },
  { href: "/settings", label: "Settings", icon: Settings },
  { href: "/help", label: "Help", icon: HelpCircle },
];

const model =
  process.env.NEXT_PUBLIC_MARKETMESH_LLM_MODE === "live"
    ? "DeepSeek V4.1 Flash"
    : "Scripted demo";

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [healthy, setHealthy] = useState<number | null>(null);
  const [total, setTotal] = useState<number>(0);

  const openAgent = () => {
    const threadId = crypto.randomUUID();
    try {
      window.sessionStorage.removeItem("marketmesh:pendingBrief");
    } catch {
      // A fresh agent workspace can still open when session storage is unavailable.
    }
    router.push(`/agents/${threadId}`);
  };

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const sellers = await fetchRegistry();
        if (cancelled) return;
        setHealthy(sellers.filter((s) => s.healthy).length);
        setTotal(sellers.length || 3);
      } catch {
        if (!cancelled) setHealthy(null);
      }
    };
    void load();
    const t = window.setInterval(load, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(t);
    };
  }, []);

  return (
    <aside className="mm-sidebar" aria-label="Primary navigation">
      <div className="mm-brand">
        <svg viewBox="0 0 32 32" className="mm-brand-mark" aria-hidden="true">
          <circle cx="7" cy="8" r="3.2" />
          <circle cx="25" cy="7" r="2.4" />
          <circle cx="22" cy="25" r="3.2" />
          <circle cx="7" cy="23" r="2.4" />
          <path d="M10 9.3 21.5 7.9M9.4 10.5l11.4 12M23.5 9.2l-1.2 12.5M9.3 21.7l-1.2-11" />
        </svg>
        <div>
          <span className="mm-wordmark">MarketMesh</span>
          <span className="mm-wordmark-sub">open agent exchange</span>
        </div>
      </div>

      <nav>
        <ul>
          {NAV.map(({ href, label, icon: Icon }) => {
            const active =
              pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <li key={href}>
                <Link
                  href={href}
                  className={cn("mm-nav-item", active && "is-active")}
                  aria-current={active ? "page" : undefined}
                >
                  <Icon size={15} aria-hidden="true" /> {label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <section className="mm-sidebar-promo" aria-labelledby="sidebar-promo-title">
        <div className="mm-sidebar-promo-head">
          <span className="mm-sidebar-promo-icon" aria-hidden="true">
            <Bot size={18} strokeWidth={1.7} />
          </span>
          <span className="mm-sidebar-promo-status">Buyer agent</span>
        </div>
        <h2 id="sidebar-promo-title">Your personal shopping agent is always on.</h2>
        <p>Find products, negotiate offers, and keep every purchase protected.</p>
        <Button
          size="sm"
          className="mm-sidebar-promo-button mm-button-signal"
          onClick={openAgent}
          leftIcon={<MessageCircle size={13} aria-hidden="true" />}
        >
          Chat with Agent <ArrowRight size={12} aria-hidden="true" />
        </Button>
      </section>

      <div className="mm-sidebar-footer">
        <span className="mm-registry-status" aria-live="polite">
          <span
            className={`mm-health-dot ${
              healthy === null ? "is-down" : healthy ? "is-live" : ""
            }`}
            aria-hidden="true"
          />
          {healthy === null
            ? "Registry offline"
            : `${healthy}/${total} sellers live`}
        </span>
        <span className="mm-model-badge">
          <span>Model</span> {model}
        </span>
      </div>
    </aside>
  );
}
