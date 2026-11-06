import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { consoleSession } from "@/lib/console-session";
import { controlPlaneForUser } from "@/lib/control-plane";
import { sellerEntryPath } from "@/lib/onboarding";

export const dynamic = "force-dynamic";

export default async function OnboardingEntryPage() {
  await auth.protect();
  await consoleSession();
  const response = await controlPlaneForUser("/v1/seller/onboarding");
  if (!response.ok) {
    return (
      <main className="mm-seller-main">
        <h1>Seller onboarding</h1>
        <p>Start onboarding to become a seller.</p>
      </main>
    );
  }
  const body = await response.json();
  redirect(sellerEntryPath(body.profile, body.onboarding));
}
