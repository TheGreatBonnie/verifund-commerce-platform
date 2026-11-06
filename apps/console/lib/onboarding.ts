const STEPS = [
  "profile",
  "verification",
  "integrations",
  "agent_setup",
  "policies",
  "testing",
  "activation",
] as const;

export function sellerEntryPath(
  profile: { verification_status: string } | null,
  onboarding: { current_step: string } | null
) {
  if (!profile) return "/seller/onboarding";
  if (profile.verification_status === "verified") return "/seller/dashboard";
  const step = onboarding?.current_step ?? "profile";
  return (STEPS as readonly string[]).includes(step)
    ? `/seller/onboarding/${step}`
    : "/seller/onboarding/profile";
}
