import { Panel } from "@/components/ui/panel";

export function AdminPage({
  kicker,
  title,
  children,
}: {
  kicker: string;
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <main className="mm-dashboard-page">
      <Panel className="mm-dashboard-hero">
        <div className="mm-dashboard-hero-copy">
          <p className="mm-kicker">{kicker}</p>
          <h1 className="mm-home-title">{title}</h1>
          {children}
        </div>
      </Panel>
    </main>
  );
}
