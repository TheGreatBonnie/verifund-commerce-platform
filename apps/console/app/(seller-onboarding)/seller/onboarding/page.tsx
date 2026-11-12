import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { controlPlaneForUser } from "@/lib/control-plane";
import { sellerEntryPath } from "@/lib/onboarding";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";

export const dynamic = "force-dynamic";

export default async function OnboardingEntryPage() {
  await auth.protect();

  let response: Response;
  try {
    response = await controlPlaneForUser("/v1/seller/onboarding");
  } catch (err) {
    console.error("onboarding entry: control plane unreachable", err);
    return (
      <main className="mm-seller-main">
        <Panel kicker="Seller onboarding" title="Couldn't reach the server">
          <p style={{ margin: 0, color: "var(--muted)" }}>
            The Verifund control plane is unreachable. Check that it's running and try again.
          </p>
        </Panel>
      </main>
    );
  }

  if (response.status === 404) {
    // No onboarding record yet — start one automatically.
    let start: Response;
    try {
      start = await controlPlaneForUser("/v1/seller/onboarding", { method: "POST" });
    } catch (err) {
      console.error("onboarding entry: failed to start onboarding", err);
      return (
        <main className="mm-seller-main">
          <Panel kicker="Seller onboarding" title="Couldn't start onboarding">
            <p style={{ margin: 0, color: "var(--muted)" }}>
              Failed to create your onboarding record. Please try again.
            </p>
          </Panel>
        </main>
      );
    }
    if (!start.ok) {
      console.error("onboarding entry: start onboarding failed", start.status, await start.text().catch(() => ""));
      return (
        <main className="mm-seller-main">
          <Panel kicker="Seller onboarding" title="Couldn't start onboarding">
            <p style={{ margin: 0, color: "var(--muted)" }}>
              The server rejected the onboarding request ({start.status}). Please try again.
            </p>
          </Panel>
        </main>
      );
    }
    const body = await start.json();
    redirect(sellerEntryPath(body.profile, body.onboarding));
  }

  if (!response.ok) {
    console.error("onboarding entry: unexpected status", response.status);
    return (
      <main className="mm-seller-main">
        <Panel kicker="Seller onboarding" title="Something went wrong">
          <p style={{ margin: 0, color: "var(--muted)" }}>
            Unexpected response ({response.status}). Please try again.
          </p>
        </Panel>
      </main>
    );
  }

  const body = await response.json();
  redirect(sellerEntryPath(body.profile, body.onboarding));
}
