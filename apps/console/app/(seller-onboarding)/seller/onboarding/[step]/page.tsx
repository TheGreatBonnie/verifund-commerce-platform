"use client";

import { useParams } from "next/navigation";

export default function OnboardingStepPage() {
  const params = useParams();
  const step = params.step as string;
  return (
    <main className="mm-seller-main">
      <h1>Seller onboarding: {step}</h1>
      <p>Continue setup to unlock publishing and payouts.</p>
    </main>
  );
}
