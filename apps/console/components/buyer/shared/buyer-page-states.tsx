import Link from "next/link";
import { type ReactNode } from "react";

import { Skeleton } from "@/components/ui/skeleton";

export function BuyerPageSkeleton({
  label = "Loading",
  cards = 4,
  rows = 3,
}: {
  label?: string;
  cards?: number;
  rows?: number;
}) {
  return (
    <div className="mm-page" role="status" aria-busy="true" aria-live="polite">
      <Skeleton className="mm-buyer-skeleton-title" />
      <p className="mm-muted">{label}…</p>
      <div className="mm-buyer-overview-grid" aria-hidden="true">
        {Array.from({ length: cards }, (_, i) => (
          <Skeleton className="mm-buyer-skeleton-card" key={i} />
        ))}
      </div>
      <div className="mm-panel" aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton className="mm-buyer-skeleton-row" key={i} />
        ))}
      </div>
    </div>
  );
}

function backLabel(href: string): string {
  const segment = href.split("/").filter(Boolean).pop() ?? "transactions";
  const words = segment.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return `Back to ${words}`;
}

export function BuyerErrorState({
  message,
  onRetry,
  notFound = false,
  backHref = "/transactions",
}: {
  message: string;
  onRetry?: () => void;
  notFound?: boolean;
  backHref?: string;
}) {
  if (notFound) {
    return (
      <main className="mm-page mm-page-error">
        <h1>Not found</h1>
        <p role="alert">
          This record does not exist or you no longer have access to it.
        </p>
        <Link href={backHref}>{backLabel(backHref)}</Link>
      </main>
    );
  }

  return (
    <main className="mm-page mm-page-error">
      <p role="alert">{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </main>
  );
}

export function BuyerSuccessMessage({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <p className={className} role="status" aria-live="polite">
      {children}
    </p>
  );
}
