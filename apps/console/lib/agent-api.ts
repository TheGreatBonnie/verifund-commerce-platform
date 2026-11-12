import { controlPlaneForUser } from "@/lib/control-plane";
import { SellerApiError } from "@/lib/seller-api";
import type {
  AgentCardPreview,
  AgentConfigPatch,
  AgentCreateResponse,
  AgentPoliciesPatch,
  AgentSnapshot,
  AgentStatusResponse,
  CatalogImportResult,
  TestRun,
} from "@/lib/agent-types";
import { sellerAgentId } from "@/lib/agent-types";

const TIMEOUT_MS = 15_000;

export { SellerApiError, sellerAgentId };

async function failure(response: Response): Promise<SellerApiError> {
  let message = `Control plane responded ${response.status}`;
  let code: string | undefined;
  let details: unknown;
  try {
    const body = (await response.json()) as {
      error?: { message?: string; code?: string; details?: unknown };
      detail?: string;
    };
    message = body?.error?.message ?? body?.detail ?? message;
    code = body?.error?.code;
    details = body?.error?.details;
  } catch {
    // Keep the status-based message when the body is not JSON.
  }
  const err = new SellerApiError(message, response.status, code) as SellerApiError & {
    details?: unknown;
  };
  if (details !== undefined) err.details = details;
  return err;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await controlPlaneForUser(path, {
      ...init,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (err) {
    if (err instanceof SellerApiError) throw err;
    const message =
      err instanceof Error ? err.message : "Control plane is unreachable";
    throw new SellerApiError(message, 503);
  }
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

export async function getAgentStatus(
  agentId: string,
): Promise<AgentStatusResponse | null> {
  const response = await controlPlaneForUser(
    `/v1/agents/${encodeURIComponent(agentId)}/status`,
    { signal: AbortSignal.timeout(TIMEOUT_MS) },
  );
  if (response.status === 404) return null;
  if (!response.ok) throw await failure(response);
  return (await response.json()) as AgentStatusResponse;
}

export async function getAgent(
  agentId: string,
): Promise<AgentSnapshot | null> {
  const status = await getAgentStatus(agentId);
  if (!status) return null;
  return {
    agent_id: status.agent_id,
    status: status.status,
    config_version: status.config_version ?? 0,
    policy_version: Number(status.policy_version ?? 1),
    policy_hash: status.policy_hash ?? "",
    card_hash: status.card_hash,
    name: status.name ?? undefined,
    tagline: status.tagline ?? undefined,
    tool_allowlist: status.tool_allowlist,
    instructions: status.instructions,
    max_discount_bps: status.max_discount_bps ?? undefined,
    autonomy_mode: status.autonomy_mode ?? undefined,
  };
}

export async function createAgent(
  displayName?: string,
): Promise<AgentCreateResponse> {
  const idempotencyKey =
    globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random()}`;
  return request<AgentCreateResponse>("/v1/agents", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "idempotency-key": idempotencyKey,
    },
    body: JSON.stringify(
      displayName ? { display_name: displayName } : {},
    ),
  });
}

export async function saveConfig(
  agentId: string,
  patch: AgentConfigPatch,
): Promise<AgentSnapshot> {
  return request<AgentSnapshot>(
    `/v1/agents/${encodeURIComponent(agentId)}/config`,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
}

export async function savePolicies(
  agentId: string,
  patch: AgentPoliciesPatch,
): Promise<AgentSnapshot> {
  return request<AgentSnapshot>(
    `/v1/agents/${encodeURIComponent(agentId)}/policies`,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch),
    },
  );
}

export async function importCatalog(
  document: string,
  replace = false,
): Promise<CatalogImportResult> {
  return request<CatalogImportResult>("/v1/seller/catalog/import", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ document, replace_catalog: replace }),
  });
}

export async function generateInstructions(
  agentId: string,
): Promise<{ instructions: string; agent_id: string }> {
  return request<{ instructions: string; agent_id: string }>(
    `/v1/agents/${encodeURIComponent(agentId)}/instructions/generate`,
    { method: "POST", headers: { "content-type": "application/json" }, body: "{}" },
  );
}

export async function runAgentTests(agentId: string): Promise<TestRun> {
  return request<TestRun>(
    `/v1/agents/${encodeURIComponent(agentId)}/test`,
    { method: "POST", headers: { "content-type": "application/json" }, body: "{}" },
  );
}

export async function activateAgent(
  agentId: string,
): Promise<{ status: string; registry_published?: boolean }> {
  return request(
    `/v1/agents/${encodeURIComponent(agentId)}/activate`,
    { method: "POST", headers: { "content-type": "application/json" }, body: "{}" },
  );
}

export async function getAgentCard(agentId: string): Promise<AgentCardPreview> {
  const body = await request<{
    card: Record<string, unknown>;
    card_hash: string | null;
    card_url: string;
  }>(`/v1/agents/${encodeURIComponent(agentId)}/card`);
  return {
    card_json: body.card,
    card_hash: body.card_hash ?? null,
    card_url: body.card_url,
  };
}
