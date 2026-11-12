import { auth } from "@clerk/nextjs/server";
import { LockedHint } from "@/components/seller-agent/LockedHint";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { PolicyPanel } from "@/components/seller-agent/PolicyPanel";
import { Panel } from "@/components/ui/panel";
import { Alert } from "@/components/ui/alert";
import { loadAgentContext } from "@/lib/agent-context";

export const dynamic = "force-dynamic";

export default async function PoliciesStepPage() {
  await auth.protect();
  const ctx = await loadAgentContext();

  if (ctx.onboardingUnreachable || ctx.statusUnreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Policies" title="Couldn't reach the server">
          <Alert message="The Verifund services are unreachable right now. Check that the control plane and seller runtime are running, then reload." />
        </Panel>
      </main>
    );
  }

  const { agentId, status } = ctx;

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel
        kicker="Seller onboarding · Policies"
        title="Autonomy & caps"
        actions={
          status?.policy_hash ? (
            <span style={{ fontSize: 10, color: "var(--muted)" }}>
              policy v{status.policy_version ?? "1"} · {String(status.policy_hash).slice(0, 12)}…
            </span>
          ) : null
        }
      >
        {agentId ? (
          <PolicyPanel
            agentId={agentId}
            initialMaxDiscountBps={status?.max_discount_bps ?? null}
            initialAutonomyMode={status?.autonomy_mode ?? null}
            configVersion={status?.config_version ?? null}
          />
        ) : (
          <LockedHint step="agent_setup" label="Agent setup" />
        )}
      </Panel>
    </main>
  );
}
