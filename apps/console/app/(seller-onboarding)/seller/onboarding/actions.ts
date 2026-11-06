"use server";

import { auth } from "@clerk/nextjs/server";
import { revalidatePath } from "next/cache";
import {
  activateAgent,
  createAgent,
  importCatalog,
  runAgentTests,
  saveConfig,
  savePolicies,
  SellerApiError,
} from "@/lib/agent-api";
import type {
  AgentConfigPatch,
  AgentPoliciesPatch,
  CatalogImportErrorEntry,
} from "@/lib/agent-types";

type ActionResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; status?: number; code?: string };

function asFriendlyError(err: unknown): { error: string; status?: number; code?: string } {
  if (err instanceof SellerApiError) {
    return { error: err.message, status: err.status, code: err.code };
  }
  return { error: "Something went wrong. Please try again." };
}

function revalidateAgentPaths() {
  revalidatePath("/seller/onboarding");
  revalidatePath("/seller/agent");
}

export async function createAgentAction(
  displayName?: string,
): Promise<ActionResult<{ agent_id: string; status: string }>> {
  await auth.protect();
  try {
    const data = await createAgent(displayName);
    revalidateAgentPaths();
    return { ok: true, data: { agent_id: data.agent_id, status: data.status } };
  } catch (err) {
    return { ok: false, ...asFriendlyError(err) };
  }
}

export async function saveConfigAction(
  agentId: string,
  patch: AgentConfigPatch,
): Promise<ActionResult<{ config_version: number; policy_hash: string; status?: string }>> {
  await auth.protect();
  try {
    const data = await saveConfig(agentId, patch);
    revalidateAgentPaths();
    return {
      ok: true,
      data: {
        config_version: data.config_version,
        policy_hash: data.policy_hash,
        status: data.status,
      },
    };
  } catch (err) {
    return { ok: false, ...asFriendlyError(err) };
  }
}

export async function savePoliciesAction(
  agentId: string,
  patch: AgentPoliciesPatch,
): Promise<ActionResult<{ config_version: number; policy_hash: string; status?: string }>> {
  await auth.protect();
  try {
    const data = await savePolicies(agentId, patch);
    revalidateAgentPaths();
    return {
      ok: true,
      data: {
        config_version: data.config_version,
        policy_hash: data.policy_hash,
        status: data.status,
      },
    };
  } catch (err) {
    return { ok: false, ...asFriendlyError(err) };
  }
}

export async function importCatalogAction(
  document: string,
  replaceCatalog = false,
): Promise<
  ActionResult<{
    inserted: number;
    updated: number;
    replaced: number;
    errors: Array<{ row: number | null; field: string | null; message: string }>;
  }> & { errors?: Array<{ row: number | null; field: string | null; message: string }> }
> {
  await auth.protect();
  const trimmed = document.trim();
  if (trimmed.length < 2) {
    return { ok: false, error: "Paste the catalog JSON or YAML first.", status: 400 };
  }
  try {
    const data = await importCatalog(trimmed, replaceCatalog);
    revalidateAgentPaths();
    return { ok: true, data };
  } catch (err) {
    if (err instanceof SellerApiError && err.status === 422) {
      const details = (
        err as SellerApiError & {
          details?: { errors?: CatalogImportErrorEntry[] };
        }
      ).details;
      const errors = Array.isArray(details?.errors) ? details.errors : undefined;
      return {
        ok: false,
        error:
          "The catalog could not be imported. Fix the errors below and try again — nothing was saved.",
        status: err.status,
        code: err.code ?? "catalog_invalid",
        errors,
      };
    }
    return { ok: false, ...asFriendlyError(err) };
  }
}

export async function runTestsAction(
  agentId: string,
): Promise<
  ActionResult<{
    passed: boolean;
    checks: Array<{ name: string; passed: boolean; detail: string }>;
    run_id: string;
  }>
> {
  await auth.protect();
  try {
    const data = await runAgentTests(agentId);
    revalidateAgentPaths();
    return { ok: true, data };
  } catch (err) {
    return { ok: false, ...asFriendlyError(err) };
  }
}

export async function activateAgentAction(
  agentId: string,
): Promise<ActionResult<{ status: string; registry_published?: boolean }>> {
  await auth.protect();
  try {
    const data = await activateAgent(agentId);
    revalidateAgentPaths();
    return { ok: true, data };
  } catch (err) {
    if (err instanceof SellerApiError && err.code === "onboarding_incomplete") {
      return {
        ok: false,
        error:
          "Activation is blocked until a passing test run matches the current policy hash and card hash, the seller is verified, and at least one credential is active.",
        status: err.status,
        code: err.code,
      };
    }
    return { ok: false, ...asFriendlyError(err) };
  }
}
