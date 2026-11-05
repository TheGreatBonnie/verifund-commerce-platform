import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { cn } from "@/lib/cn";

const TABS = [
  { href: "", label: "Overview" },
  { href: "/evidence", label: "Evidence" },
  { href: "/activity", label: "Activity" },
] as const;

export function FulfillmentTabs({
  transactionId,
  active,
}: {
  transactionId: string;
  active: "overview" | "evidence" | "activity";
}) {
  const base = `/seller/fulfillment/${encodeURIComponent(transactionId)}`;
  return (
    <nav className="mm-seller-tabs" aria-label="Fulfillment workspace">
      {TABS.map((tab) => {
        const key = tab.href === "" ? "overview" : tab.href.slice(1);
        const isActive = key === active;
        return (
          <Link
            key={tab.label}
            href={`${base}${tab.href}`}
            className={cn("mm-seller-tab", isActive && "is-active")}
            aria-current={isActive ? "page" : undefined}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function FulfillmentBackLink() {
  return (
    <Link href="/seller/fulfillment" className="mm-seller-back-link">
      <ArrowLeft size={13} aria-hidden="true" />
      Back to fulfillment tasks
    </Link>
  );
}
