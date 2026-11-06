import { auth } from "@clerk/nextjs/server";
import { CatalogImportPanel } from "@/components/seller-agent/CatalogImportPanel";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { Panel } from "@/components/ui/panel";
import { Alert } from "@/components/ui/alert";
import { loadAgentContext } from "@/lib/agent-context";

export const dynamic = "force-dynamic";

export default async function IntegrationsStepPage() {
  await auth.protect();
  const ctx = await loadAgentContext();

  if (ctx.onboardingUnreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Integrations" title="Couldn't reach the server">
          <Alert message="The Verifund control plane is unreachable. Check that it's running and try again." />
        </Panel>
      </main>
    );
  }

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel
        kicker="Seller onboarding · Integrations"
        title="Import your catalog"
        actions={
          <span style={{ fontSize: 11, color: "var(--muted)" }}>
            Upsert by SKU · max 2&nbsp;MB / 1000 SKUs
          </span>
        }
      >
        <CatalogImportPanel agentId={ctx.agentId} />
      </Panel>
      <Panel kicker="Coming next" title="External sync" className="is-subtle">
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
          Shopify, WooCommerce and ERP sync land in the next milestone. Your imported
          catalog is authoritative for the sandbox profile until then — re-import any
          time to update it.
        </p>
      </Panel>
    </main>
  );
}
