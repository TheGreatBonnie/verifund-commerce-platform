import { auth } from "@clerk/nextjs/server";
import { ActivationPanel } from "@/components/seller-agent/ActivationPanel";
import { AgentCardPreview } from "@/components/seller-agent/AgentCardPreview";
import { LockedHint } from "@/components/seller-agent/LockedHint";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { Panel } from "@/components/ui/panel";
import { Alert } from "@/components/ui/alert";
import { loadAgentContext } from "@/lib/agent-context";

export const dynamic = "force-dynamic";

export default async function ActivationStepPage() {
  await auth.protect();
  const ctx = await loadAgentContext();

  if (ctx.onboardingUnreachable || ctx.statusUnreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Activation" title="Couldn't reach the server">
          <Alert message="The Verifund services are unreachable right now. Check that the control plane and seller runtime are running, then reload." />
        </Panel>
      </main>
    );
  }

  const { agentId, status, card } = ctx;
  const verified = ctx.onboarding.profile?.verification_status === "verified";
  const latest = status?.latest_test_run ?? null;
  const testPassed = latest ? latest.passed === "1" : null;

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel kicker="Seller onboarding · Activation" title="Make it live">
        {agentId ? (
          <ActivationPanel
            agentId={agentId}
            verified={verified}
            testPassed={testPassed}
            hasCard={card != null}
          />
        ) : (
          <LockedHint step="agent_setup" label="Agent setup" />
        )}
      </Panel>
      {agentId ? (
        <Panel kicker="Discovery" title="Public card preview">
          <AgentCardPreview
            card={card?.card_json ?? null}
            cardUrl={card?.card_url ?? null}
            cardHash={card?.card_hash ?? null}
          />
        </Panel>
      ) : null}
    </main>
  );
}
