const STEPS = [
  // Strict order mirrors control-plane STEP_ORDER (profile → agent → config
  // → catalog → test → verification → activation). Route names differ only
  // for historical reasons: agent_setup=agent, policies=config,
  // integrations=catalog, testing=test.
  "profile",
  "agent_setup",
  "policies",
  "integrations",
  "testing",
  "verification",
  "activation",
] as const;

const STEP_ALIASES: Record<string, string> = {
  agent: "agent_setup",
  config: "policies",
  catalog: "integrations",
  test: "testing",
};

export function sellerEntryPath(
  profile: { verification_status: string } | null,
  onboarding: { current_step: string; status?: string } | null
) {
  if (!profile) return "/seller/onboarding";
  if (profile.verification_status === "verified") return "/seller/dashboard";
  const raw = onboarding?.current_step ?? "profile";
  const step = STEP_ALIASES[raw] ?? raw;
  return (STEPS as readonly string[]).includes(step)
    ? `/seller/onboarding/${step}`
    : "/seller/onboarding/profile";
}
