import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { redirect } from "next/navigation";
import { Bot, KeyRound } from "lucide-react";
import { AgentCardPreview } from "@/components/seller-agent/AgentCardPreview";
import { AgentIdentityPanel } from "@/components/seller-agent/AgentIdentityPanel";
import { CapabilityGrid } from "@/components/seller-agent/CapabilityGrid";
import { InstructionEditor } from "@/components/seller-agent/InstructionEditor";
import { PolicyPanel } from "@/components/seller-agent/PolicyPanel";
import { SellerPageHeader } from "@/components/seller/seller-page-header";
import { Badge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import { Alert } from "@/components/ui/alert";
import { loadAgentContext } from "@/lib/agent-context";

export const dynamic = "force-dynamic";

export default async function SellerAgentPortalPage() {
  await auth.protect();
  const ctx = await loadAgentContext();

  if (ctx.onboarding.profile?.verification_status !== "verified") {
    redirect("/seller/onboarding");
  }

  if (ctx.onboardingUnreachable || ctx.statusUnreachable) {
    return (
      <>
        <SellerPageHeader
          eyebrow="Agent"
          title="Seller agent"
          description="Your agent's identity, behavior, and activation status."
        />
        <Alert message="The Verifund services are unreachable right now. Check that the control plane and seller runtime are running, then reload." />
      </>
    );
  }

  const { agentId, status, card } = ctx;

  if (!agentId) {
    return (
      <>
        <SellerPageHeader
          eyebrow="Agent"
          title="Seller agent"
          description="Your agent's identity, behavior, and activation status."
        />
        <Panel kicker="Setup required" title="Create your agent first">
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
            Your seller profile is verified, but no agent has been configured yet.
          </p>
          <Link href="/seller/onboarding/agent_setup" className="mm-button mm-button-sm" style={{ marginTop: 12, display: "inline-flex" }}>
            Continue onboarding
          </Link>
        </Panel>
      </>
    );
  }

  const latest = status?.latest_test_run ?? null;
  const testPassed = latest ? latest.passed === "1" : null;

  return (
    <>
      <SellerPageHeader
        eyebrow="Agent"
        title="Seller agent"
        description="Edit your agent in place. Changes to instructions, capabilities or policy re-stamp the card hash — re-run the test suite before the registry picks them up."
      />

      <Panel
        kicker="Identity"
        title="Agent identity"
        actions={<Badge>{status?.status ?? "draft"}</Badge>}
      >
        <AgentIdentityPanel
          agentId={agentId}
          status={status?.status ?? null}
          cardUrl={card?.card_url ?? null}
        />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginTop: 12,
            borderTop: "1px solid var(--rule)",
            paddingTop: 12,
            fontSize: 11,
            color: "var(--muted)",
          }}
        >
          <KeyRound size={13} aria-hidden="true" />
          <span>
            Machine credential: managed per agent, never displayed. Status metadata only —
            rotation arrives with the post-activation hardening pass.
          </span>
        </div>
      </Panel>

      <Panel
        kicker="Activation gate"
        title="Test status"
        actions={<Badge>{testPassed === null ? "not run" : testPassed ? "passing" : "failing"}</Badge>}
      >
        <Bot size={13} aria-hidden="true" style={{ color: "var(--muted)" }} />
        <p style={{ margin: "6px 0 0", color: "var(--muted)", fontSize: 12 }}>
          {testPassed === null
            ? "No test run recorded yet. Run the six checks in onboarding."
            : testPassed
              ? "A passing test run matches the current policy hash and card hash."
              : "The latest test run did not pass. Activation is blocked until it does."}
        </p>
        <Link
          href="/seller/onboarding/testing"
          style={{ fontSize: 12, display: "inline-block", marginTop: 8 }}
        >
          Open the test console →
        </Link>
      </Panel>

      <Panel kicker="Behavior" title="Instructions">
        <InstructionEditor
          agentId={agentId}
          initialInstructions={status?.instructions ?? ""}
          configVersion={status?.config_version ?? null}
        />
      </Panel>

      <Panel kicker="Behavior" title="Capabilities">
        <CapabilityGrid
          agentId={agentId}
          initialAllowlist={status?.tool_allowlist ?? null}
          configVersion={status?.config_version ?? null}
        />
      </Panel>

      <Panel
        kicker="Autonomy"
        title="Policy"
        actions={
          status?.policy_hash ? (
            <span style={{ fontSize: 10, color: "var(--muted)" }}>
              policy v{status.policy_version ?? "1"} · {String(status.policy_hash).slice(0, 12)}…
            </span>
          ) : null
        }
      >
        <PolicyPanel
          agentId={agentId}
          initialMaxDiscountBps={status?.max_discount_bps ?? null}
          initialAutonomyMode={status?.autonomy_mode ?? null}
          configVersion={status?.config_version ?? null}
        />
      </Panel>

      <Panel kicker="Discovery" title="Public card">
        <AgentCardPreview
          card={card?.card_json ?? null}
          cardUrl={card?.card_url ?? null}
          cardHash={card?.card_hash ?? null}
        />
      </Panel>
    </>
  );
}
