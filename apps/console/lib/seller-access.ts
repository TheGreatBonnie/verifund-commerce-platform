import { controlPlaneForUser } from "@/lib/control-plane";

export async function sellerAccess(
  orgId: string | null,
): Promise<"onboarding" | "workspace" | "read_only" | "none"> {
  if (!orgId) return "none";
  const response = await controlPlaneForUser("/v1/seller/onboarding");
  if (response.status === 404) return "onboarding";
  if (!response.ok) return "none";
  const body = await response.json();
  if (!body.profile) return "onboarding";
  if (body.profile.verification_status === "suspended") return "read_only";
  return "workspace";
}
