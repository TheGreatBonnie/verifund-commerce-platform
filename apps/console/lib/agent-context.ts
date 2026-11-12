import { controlPlaneForUser } from "@/lib/control-plane";
import {
  getAgentCard,
  getAgentStatus,
  sellerAgentId,
} from "@/lib/agent-api";
import type { AgentCardPreview, AgentStatusResponse } from "@/lib/agent-types";

export type OnboardingProfile = {
  seller_id?: string | null;
  verification_status?: string | null;
  display_name?: string | null;
  name?: string | null;
};

export type OnboardingState = {
  profile: OnboardingProfile | null;
  currentStep: string | null;
  status: string | null;
};

export type AgentContext = {
  onboarding: OnboardingState;
  agentId: string | null;
  status: AgentStatusResponse | null;
  card: AgentCardPreview | null;
  onboardingUnreachable: boolean;
  statusUnreachable: boolean;
};

/**
 * Load everything the agent-configuration surfaces need, server-side.
 * Never throws: every branch degrades to a renderable state with an
 * `unreachable` flag so pages can show a single coherent error panel.
 */
export async function loadAgentContext(): Promise<AgentContext> {
  let onboarding: OnboardingState = { profile: null, currentStep: null, status: null };
  let onboardingUnreachable = false;
  try {
    const response = await controlPlaneForUser("/v1/seller/onboarding");
    if (response.ok) {
      const body = (await response.json()) as {
        profile?: OnboardingProfile | null;
        onboarding?: { current_step?: string | null; status?: string | null } | null;
      };
      onboarding = {
        profile: body.profile ?? null,
        currentStep: body.onboarding?.current_step ?? null,
        status: body.onboarding?.status ?? null,
      };
    } else if (response.status !== 404) {
      onboardingUnreachable = true;
    }
  } catch {
    onboardingUnreachable = true;
  }

  const agentId = sellerAgentId(onboarding.profile);

  let status: AgentStatusResponse | null = null;
  let statusUnreachable = false;
  if (agentId) {
    try {
      status = await getAgentStatus(agentId);
    } catch {
      statusUnreachable = true;
    }
  }

  let card: AgentCardPreview | null = null;
  if (agentId && status) {
    try {
      card = await getAgentCard(agentId);
    } catch {
      card = null;
    }
  }

  return {
    onboarding,
    agentId,
    status,
    card,
    onboardingUnreachable,
    statusUnreachable,
  };
}
