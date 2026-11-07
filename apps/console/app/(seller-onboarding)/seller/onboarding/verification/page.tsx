import { auth } from "@clerk/nextjs/server";
import Link from "next/link";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { VerificationSubmitForm } from "@/components/seller-agent/VerificationSubmitForm";
import { Alert } from "@/components/ui/alert";
import { Panel } from "@/components/ui/panel";
import { controlPlaneForUser } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

type Profile = { verification_status?: string | null } | null;

export default async function VerificationStepPage() {
  await auth.protect();
  let profile: Profile = null;
  let unreachable = false;
  try {
    const response = await controlPlaneForUser("/v1/seller/onboarding");
    if (response.ok) {
      const body = (await response.json()) as { profile?: Profile };
      profile = body.profile ?? null;
    } else if (response.status !== 404) {
      unreachable = true;
    }
  } catch {
    unreachable = true;
  }

  if (unreachable) {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Verification" title="Couldn't reach the server">
          <Alert message="The Verifund control plane is unreachable. Check that it's running and try again." />
        </Panel>
      </main>
    );
  }

  const status = profile?.verification_status ?? "unverified";

  if (status === "verified") {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Verification" title="Seller verified">
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
            Your seller account is verified. Continue to configure and activate your agent.
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <Link href="/seller/onboarding/agent_setup" className="mm-button mm-button-sm" style={{ textDecoration: "none" }}>
              Continue to agent setup
            </Link>
            <Link href="/seller/agent" className="mm-button mm-button-outline mm-button-sm" style={{ textDecoration: "none" }}>
              Open seller agent
            </Link>
          </div>
        </Panel>
      </main>
    );
  }

  if (status === "pending") {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Verification" title="Verification pending">
          <Alert message="Your verification has been submitted and is awaiting review. Activation remains blocked until the seller account is verified." />
        </Panel>
      </main>
    );
  }

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel kicker="Seller onboarding · Verification" title="Verify your seller account">
        <p style={{ margin: "0 0 12px", color: "var(--muted)", fontSize: 12 }}>
          Submit verification to unlock activation. In sandbox environments, eligible submissions may be verified automatically; otherwise review is completed out of band.
        </p>
        {status === "rejected" ? (
          <Alert message="Your previous verification was rejected. Update any details if needed and submit again." />
        ) : null}
        <div style={{ marginTop: status === "rejected" ? 12 : 0 }}>
          <VerificationSubmitForm />
        </div>
      </Panel>
    </main>
  );
}
