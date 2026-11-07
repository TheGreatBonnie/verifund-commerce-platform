"use server";

import { auth } from "@clerk/nextjs/server";
import { controlPlaneForUser } from "@/lib/control-plane";

const ORCHESTRATOR =
  process.env.ORCHESTRATOR_URL ??
  process.env.ORCHESTRATOR_AGUI_URL ??
  "http://127.0.0.1:9000";

export type Decision = "APPROVE" | "REJECT" | "REQUEST_CHANGES";

export type ResumeHandle = {
  task_id: string;
  context_id: string;
  run_id: string;
};

export type AgreementDecisionResult = {
  decisionRecorded: boolean;
  error?: string;
  resume?: unknown;
  resumeError?: string;
};

async function recordDecision(
  id: string,
  version: number,
  hash: string,
  decision: Decision,
  note: string,
  idempotencyKey: string,
): Promise<AgreementDecisionResult> {
  const decisionRes = await controlPlaneForUser(
    `/agreements/${encodeURIComponent(id)}/buyer-decision`,
    {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({
        agreement_version: version,
        agreement_hash: hash,
        decision,
        note,
        idempotency_key: idempotencyKey,
      }),
    },
  );
  if (!decisionRes.ok) {
    return { error: "decision_failed", decisionRecorded: false };
  }
  return { decisionRecorded: true };
}

async function errorDetail(response: Response): Promise<string> {
  const text = await response.text();
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Keep the raw body when the orchestrator does not return JSON.
  }
  return text || `orchestrator returned ${response.status}`;
}

async function resumeOrchestrator(
  version: number,
  hash: string,
  decision: Decision,
  note: string,
  idempotencyKey: string,
  handle?: ResumeHandle | null,
): Promise<Pick<AgreementDecisionResult, "resume" | "resumeError">> {
  if (!handle?.task_id || !handle.context_id || !handle.run_id) {
    return { resumeError: "missing_handle" };
  }
  try {
    const response = await fetch(`${ORCHESTRATOR}/verifund/resume-agreement`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        task_id: handle.task_id,
        context_id: handle.context_id,
        run_id: handle.run_id,
        decision: {
          agreement_version: version,
          agreement_hash: hash,
          decision,
          note,
          idempotency_key: idempotencyKey,
        },
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
    if (!response.ok) {
      return { resumeError: await errorDetail(response) };
    }
    return { resume: await response.json() };
  } catch (error) {
    return {
      resumeError:
        error instanceof Error ? error.message : "orchestrator_resume_failed",
    };
  }
}

async function decide(
  id: string,
  version: number,
  hash: string,
  decision: Decision,
  note: string,
  idempotencyKey: string,
  handle?: ResumeHandle | null,
): Promise<AgreementDecisionResult> {
  const recorded = await recordDecision(
    id,
    version,
    hash,
    decision,
    note,
    idempotencyKey,
  );
  if (!recorded.decisionRecorded) return recorded;
  return {
    decisionRecorded: true,
    ...(await resumeOrchestrator(
      version,
      hash,
      decision,
      note,
      idempotencyKey,
      handle,
    )),
  };
}

export async function approveAgreement(
  id: string,
  version: number,
  hash: string,
  note: string,
  idempotencyKey: string,
  handle?: ResumeHandle | null,
) {
  await auth.protect();
  return decide(id, version, hash, "APPROVE", note, idempotencyKey, handle);
}

export async function rejectAgreement(
  id: string,
  version: number,
  hash: string,
  note: string,
  idempotencyKey: string,
  handle?: ResumeHandle | null,
) {
  await auth.protect();
  return decide(id, version, hash, "REJECT", note, idempotencyKey, handle);
}

export async function requestChangesAgreement(
  id: string,
  version: number,
  hash: string,
  note: string,
  idempotencyKey: string,
  handle?: ResumeHandle | null,
) {
  await auth.protect();
  return decide(
    id,
    version,
    hash,
    "REQUEST_CHANGES",
    note,
    idempotencyKey,
    handle,
  );
}

/**
 * Retry a resume after the decision was recorded but the orchestrator call
 * failed. The control plane remains the source of truth.
 */
export async function resumeAgreement(
  version: number,
  hash: string,
  decision: Decision,
  note: string,
  idempotencyKey: string,
  handle?: ResumeHandle | null,
) {
  await auth.protect();
  return resumeOrchestrator(
    version,
    hash,
    decision,
    note,
    idempotencyKey,
    handle,
  );
}
