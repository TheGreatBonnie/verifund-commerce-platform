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
    const detail = await decisionErrorDetail(decisionRes);
    return await reconcileConflict(id, version, hash, decisionRes, detail);
  }
  return { decisionRecorded: true };
}

// The HITL card renders from the agent's cached view, which can lag the
// control plane. A conflict therefore may mean the decision was already
// recorded (e.g. on the review page) rather than that it failed. Verify
// against the live agreement before deciding whether to resume the run.
async function reconcileConflict(
  id: string,
  version: number,
  hash: string,
  response: Response,
  detail: string,
): Promise<AgreementDecisionResult> {
  if (response.status !== 409 || !/invalid_state|terminal|PENDING_BUYER/.test(detail)) {
    return { error: detail, decisionRecorded: false };
  }
  try {
    const viewRes = await controlPlaneForUser(
      `/agreements/${encodeURIComponent(id)}`,
    );
    if (viewRes.ok) {
      const view = (await viewRes.json()) as {
        status?: unknown;
        current_version?: unknown;
        version?: { agreement_hash?: unknown };
      };
      const status = typeof view.status === "string" ? view.status : "";
      const viewHash =
        typeof view.version?.agreement_hash === "string"
          ? view.version.agreement_hash
          : "";
      if (
        status === "AGREED" &&
        view.current_version === version &&
        viewHash === hash
      ) {
        return { decisionRecorded: true };
      }
      if (status) {
        return {
          error: `${detail} (agreement is ${status})`,
          decisionRecorded: false,
        };
      }
    }
  } catch {
    // Keep the original control plane detail when the view cannot be read.
  }
  return { error: detail, decisionRecorded: false };
}

async function errorDetail(
  response: Response,
  fallback = `orchestrator returned ${response.status}`,
): Promise<string> {
  const text = await response.text();
  try {
    const body = JSON.parse(text) as {
      detail?: unknown;
      error?: { message?: unknown; code?: unknown };
    };
    if (typeof body.error?.message === "string" && body.error.message) {
      return body.error.message;
    }
    if (typeof body.error?.code === "string" && body.error.code) {
      return body.error.code;
    }
    if (typeof body.detail === "string" && body.detail) return body.detail;
  } catch {
    // Keep the raw body when the orchestrator does not return JSON.
  }
  return text || fallback;
}

async function decisionErrorDetail(response: Response): Promise<string> {
  return errorDetail(response, "decision_failed");
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
