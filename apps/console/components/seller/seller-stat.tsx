import type { ReactNode } from "react";

export function SellerStat({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: number | string;
  detail: string;
  tone?: "signal" | "amber" | "error";
}) {
  return (
    <article className="mm-seller-stat" data-tone={tone}>
      <span className="mm-kicker">{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

export function SellerStatGrid({ children }: { children: ReactNode }) {
  return <div className="mm-seller-stat-grid">{children}</div>;
}
