import type { ReactNode } from "react";

export function SellerPageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <header className="mm-seller-page-head">
      <div>
        <p className="mm-kicker">{eyebrow}</p>
        <h1>{title}</h1>
        {description ? <p className="mm-seller-page-description">{description}</p> : null}
      </div>
      {actions ? <div className="mm-seller-page-actions">{actions}</div> : null}
    </header>
  );
}
