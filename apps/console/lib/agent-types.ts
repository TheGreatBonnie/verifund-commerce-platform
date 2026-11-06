/**
 * Types for the seller-agent onboarding console feature.
 * Mirrors the control-plane contracts (see
 * docs/superpowers/specs/2026-11-06-single-shared-a2a-endpoint-design.md,
 * Appendix B). All fields the CP does not always return are optional.
 */
export type AgentStatus =
  | "draft"
  | "configuring"
  | "testing"
  | "active"
  | "suspended"
  | "revoked";

export type AgentSnapshot = {
  agent_id: string;
  status: AgentStatus;
  config_version: number;
  policy_version: number;
  policy_hash: string;
  card_hash?: string | null;
  tool_allowlist?: string[];
  instructions?: string;
  max_discount_bps?: number;
  autonomy_mode?: "read_only" | "assisted" | "policy_bounded" | string;
  name?: string;
  tagline?: string;
};

export type AgentStatusResponse = {
  agent_id: string;
  status: AgentStatus;
  name?: string | null;
  tagline?: string | null;
  policy_version?: string | number | null;
  policy_hash?: string | null;
  policy_drift?: boolean;
  card_hash?: string | null;
  config_version?: number | null;
  tool_allowlist?: string[];
  instructions?: string;
  max_discount_bps?: number | null;
  autonomy_mode?: string | null;
  runtime_unreachable?: boolean;
  latest_test_run?: {
    passed?: string;
    checks?: Array<{ name: string; passed: boolean; detail: string }>;
    created_at?: string;
  } | null;
};

export type AgentConfigPatch = Partial<{
  name: string;
  tagline: string;
  instructions: string;
  tool_allowlist: string[];
  max_discount_bps: number;
  autonomy_mode: "read_only" | "assisted" | "policy_bounded";
  expected_config_version: number;
}>;

export type AgentPoliciesPatch = {
  autonomy_mode?: "read_only" | "assisted" | "policy_bounded";
  max_discount_bps?: number;
  expected_config_version?: number;
};

export type CatalogImportErrorEntry = {
  row: number | null;
  field: string | null;
  message: string;
};

export type CatalogImportResult = {
  inserted: number;
  updated: number;
  replaced: number;
  errors: CatalogImportErrorEntry[];
};

export type TestCheck = { name: string; passed: boolean; detail: string };

export type TestRun = {
  passed: boolean;
  checks: TestCheck[];
  run_id: string;
};

export type AgentCardPreview = {
  card_json: Record<string, unknown>;
  card_hash: string | null;
  card_url: string;
};

export type AgentCreateResponse = {
  agent_id: string;
  status: AgentStatus;
  config_version?: number;
  policy_version?: number;
  policy_hash?: string;
};

/**
 * The CP anchors the public agent id to the globally unique seller_id
 * (decision O3): `agent_<seller_id>`. The console derives it the same way
 * instead of trusting anything from the browser.
 */
export function sellerAgentId(profile: { seller_id?: string | null } | null | undefined): string | null {
  const sellerId = profile?.seller_id?.trim();
  return sellerId ? `agent_${sellerId}` : null;
}
