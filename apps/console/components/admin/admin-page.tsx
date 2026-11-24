import { Panel } from "@/components/ui/panel";

export function AdminPage({
  kicker,
  title,
  description,
  children,
}: {
  kicker: string;
  title: string;
  description?: string;
  children?: React.ReactNode;
}) {
  return (
    <main className="mm-dashboard-page">
      <Panel className="mm-dashboard-hero">
        <div className="mm-dashboard-hero-copy">
          <p className="mm-kicker">{kicker}</p>
          <h1 className="mm-home-title">{title}</h1>
          {description ? <p className="mm-deal-lede">{description}</p> : null}
        </div>
      </Panel>
      <div className="mm-admin-content">{children}</div>
    </main>
  );
}
