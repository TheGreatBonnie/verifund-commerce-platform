import { auth } from "@clerk/nextjs/server";
import { LockedHint } from "@/components/seller-agent/LockedHint";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { TestResultsPanel } from "@/components/seller-agent/TestResultsPanel";
import { Panel } from "@/components/ui/panel";
import { Alert } from "@/components/ui/alert";
import { loadAgentContext } from "@/lib/agent-context";

export const dynamic = "force-dynamic";

export default async function TestingStepPage() {
  await auth.protect();
  const ctx = await loadAgentContext();

  if (ctx.onboardingUnreachable || ctx.statusUnreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Testing" title="Couldn't reach the server">
          <Alert message="The Verifund services are unreachable right now. Check that the control plane and seller runtime are running, then reload." />
        </Panel>
      </main>
    );
  }

  const { agentId, status } = ctx;

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel kicker="Seller onboarding · Testing" title="Run the six checks">
        {agentId ? (
          <TestResultsPanel agentId={agentId} latestRun={status?.latest_test_run ?? null} />
        ) : (
          <LockedHint step="agent_setup" label="Agent setup" />
        )}
      </Panel>
    </main>
  );
}
