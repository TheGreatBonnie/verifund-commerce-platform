import { auth } from "@clerk/nextjs/server";
import { OnboardingStepper } from "@/components/seller-agent/OnboardingStepper";
import { ProfileForm } from "@/components/seller-agent/ProfileForm";
import { Alert } from "@/components/ui/alert";
import { Panel } from "@/components/ui/panel";
import { controlPlaneForUser } from "@/lib/control-plane";

export const dynamic = "force-dynamic";

type SellerOnboardingProfile = {
  display_name?: string | null;
  verification_status?: string | null;
};

export default async function ProfileStepPage() {
  await auth.protect();
  let profile: SellerOnboardingProfile | null = null;
  let unreachable = false;
  try {
    const response = await controlPlaneForUser("/v1/seller/onboarding");
    if (response.ok) {
      const body = (await response.json()) as { profile?: SellerOnboardingProfile | null };
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
        <Panel kicker="Seller onboarding · Profile" title="Couldn't reach the server">
          <Alert message="The Verifund control plane is unreachable. Check that it's running and try again." />
        </Panel>
      </main>
    );
  }

  if (profile?.verification_status === "verified") {
    return (
      <main className="mm-seller-main">
        <OnboardingStepper />
        <Panel kicker="Seller onboarding · Profile" title="Profile verified">
          <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
            Your seller profile is verified. Continue setting up your agent.
          </p>
          <a href="/seller/onboarding/agent_setup" className="mm-button mm-button-sm" style={{ marginTop: 12, display: "inline-flex", textDecoration: "none" }}>
            Continue to agent setup
          </a>
        </Panel>
      </main>
    );
  }

  return (
    <main className="mm-seller-main">
      <OnboardingStepper />
      <Panel kicker="Seller onboarding · Profile" title="Confirm your business profile">
        <p style={{ margin: "0 0 12px", color: "var(--muted)", fontSize: 12 }}>
          Confirm the name buyers and the network will see for this seller account.
        </p>
        <ProfileForm initialDisplayName={profile?.display_name ?? ""} />
      </Panel>
    </main>
  );
}
