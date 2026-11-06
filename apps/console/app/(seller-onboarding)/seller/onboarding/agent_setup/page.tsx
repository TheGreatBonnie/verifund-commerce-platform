import { auth } from "@clerk/nextjs/server";
import { AgentCardPreview } from "@/components/seller-agent/AgentCardPreview";
import { AgentIdentityPanel } from "@/components/seller-agent/AgentIdentityPanel";
import { CapabilityGrid } from "@/components/seller-agent/CapabilityGrid";
import { InstructionEditor } from "@/components/seller-agent/InstructionEditor";
import { LockedHint } from "@/components/seller-agent/LockedHint";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { Panel } from "@/components/ui/panel";
import { Alert } from "@/components/ui/alert";
import { loadAgentContext } from "@/lib/agent-context";

export const dynamic = "force-dynamic";

export default async function AgentSetupStepPage() {
  await auth.protect();
  const ctx = await loadAgentContext();

  if (ctx.onboardingUnreachable || ctx.statusUnreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Agent setup" title="Couldn't reach the server">
          <Alert message="The Verifund services are unreachable right now. Check that the control plane and seller runtime are running, then reload." />
        </Panel>
      </main>
    );
  }

  const { agentId, status, card } = ctx;
  const cardUrl = card?.card_url ?? null;

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel kicker="Seller onboarding · Agent setup" title="Your seller agent">
        <AgentIdentityPanel
          agentId={agentId}
          status={status?.status ?? null}
          initialName={status?.name ?? ctx.onboarding.profile?.display_name ?? ""}
          cardUrl={cardUrl}
        />
      </Panel>

      <Panel kicker="Agent behavior" title="Instructions">
        {agentId ? (
          <InstructionEditor
            agentId={agentId}
            initialInstructions={status?.instructions ?? ""}
            configVersion={status?.config_version ?? null}
          />
        ) : (
          <LockedHint step="agent_setup" label="Agent setup" />
        )}
      </Panel>

      <Panel kicker="Agent behavior" title="Capabilities">
        {agentId ? (
          <CapabilityGrid
            agentId={agentId}
            initialAllowlist={status?.tool_allowlist ?? null}
            configVersion={status?.config_version ?? null}
          />
        ) : (
          <LockedHint step="agent_setup" label="Agent setup" />
        )}
      </Panel>

      <Panel kicker="Discovery" title="Public card preview">
        <AgentCardPreview card={card?.card_json ?? null} cardUrl={cardUrl} cardHash={card?.card_hash ?? null} />
      </Panel>
    </main>
  );
}
