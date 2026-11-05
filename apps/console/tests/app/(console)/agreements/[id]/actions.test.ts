import { beforeEach, describe, expect, it, vi } from "vitest";

const { controlPlaneForUserMock, protectMock } = vi.hoisted(() => ({
  controlPlaneForUserMock: vi.fn(),
  protectMock: vi.fn(),
}));

vi.mock("@/lib/control-plane", () => ({
  controlPlaneForUser: controlPlaneForUserMock,
}));

vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect: protectMock }),
}));

import {
  approveAgreement,
  rejectAgreement,
  requestChangesAgreement,
} from "@/app/(console)/agreements/[id]/actions";

const HASH = "a".repeat(64);
const HANDLE = {
  task_id: "vf-task-1",
  context_id: "vf-context-1",
  run_id: "run-1",
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe("agreement review actions", () => {
  beforeEach(() => {
    controlPlaneForUserMock.mockClear();
    protectMock.mockClear();
    vi.stubGlobal("fetch", vi.fn());
    protectMock.mockResolvedValue({ userId: "user_1" });
  });

  it("resumes the orchestrator with the exact decision after approval", async () => {
    controlPlaneForUserMock
      .mockResolvedValueOnce(jsonResponse({ token: "approval-token" }))
      .mockResolvedValueOnce(jsonResponse({ status: "AGREED", version: 1 }));
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({
        status: "approval_required",
        checkpoint: "funding_approval_required",
      }),
    );

    const result = await approveAgreement(
      "agr_1",
      1,
      HASH,
      "looks good",
      "buyer-decision:vf_1:1",
      HANDLE,
    );

    expect(result).toEqual({
      decisionRecorded: true,
      resume: {
        status: "approval_required",
        checkpoint: "funding_approval_required",
      },
    });
    expect(controlPlaneForUserMock).toHaveBeenCalledTimes(2);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(protectMock).toHaveBeenCalled();
    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(String(url)).toMatch(/\/verifund\/resume-agreement$/);
    expect(init).toMatchObject({ method: "POST" });
    expect(JSON.parse(String(init?.body))).toEqual({
      task_id: "vf-task-1",
      context_id: "vf-context-1",
      run_id: "run-1",
      decision: {
        agreement_version: 1,
        agreement_hash: HASH,
        decision: "APPROVE",
        note: "looks good",
        idempotency_key: "buyer-decision:vf_1:1",
      },
    });
  });

  it("forwards the Clerk session token without actor headers", async () => {
    controlPlaneForUserMock
      .mockResolvedValueOnce(jsonResponse({ token: "approval-token" }))
      .mockResolvedValueOnce(jsonResponse({ status: "AGREED", version: 1 }));
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ status: "approval_required" }),
    );

    const result = await approveAgreement(
      "agr_1",
      1,
      HASH,
      "looks good",
      "buyer-decision:vf_1:1",
      HANDLE,
    );

    expect(result).toMatchObject({ decisionRecorded: true });
    const tokenCall = controlPlaneForUserMock.mock.calls.find(([url]) =>
      String(url).endsWith("/approval-token"),
    );
    expect(tokenCall).toBeDefined();
    const headers = tokenCall?.[1]?.headers as Record<string, string>;
    expect(headers["X-Actor-Id"]).toBeUndefined();
    expect(headers["Idempotency-Key"]).toBe("buyer-decision:vf_1:1");
  });

  it("keeps the recorded decision when the orchestrator resume fails", async () => {
    controlPlaneForUserMock
      .mockResolvedValueOnce(jsonResponse({ token: "approval-token" }))
      .mockResolvedValueOnce(jsonResponse({ status: "REJECTED", version: 1 }));
    vi.mocked(fetch).mockResolvedValueOnce(
      jsonResponse({ detail: "agreement is not agreed" }, 409),
    );

    const result = await rejectAgreement(
      "agr_1",
      1,
      HASH,
      "not the right terms",
      "buyer-decision:vf_1:1",
      HANDLE,
    );

    expect(result).toMatchObject({
      decisionRecorded: true,
      resumeError: expect.stringContaining("agreement is not agreed"),
    });
  });

  it("does not pretend to resume when the review link has no handle", async () => {
    controlPlaneForUserMock
      .mockResolvedValueOnce(jsonResponse({ token: "approval-token" }))
      .mockResolvedValueOnce(jsonResponse({ status: "CHANGES_REQUESTED", version: 1 }));

    const result = await requestChangesAgreement(
      "agr_1",
      1,
      HASH,
      "please extend the warranty",
      "buyer-decision:vf_1:1",
      null,
    );

    expect(result).toEqual({
      decisionRecorded: true,
      resumeError: "missing_handle",
    });
    expect(controlPlaneForUserMock).toHaveBeenCalledTimes(2);
    expect(fetch).not.toHaveBeenCalled();
  });
});
