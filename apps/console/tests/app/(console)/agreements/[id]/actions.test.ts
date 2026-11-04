import { beforeEach, describe, expect, it, vi } from "vitest";

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

function fetchMock() {
  return vi.mocked(fetch);
}

describe("agreement review actions", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("resumes the orchestrator with the exact decision after approval", async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ buyer_id: "demo-buyer" }))
      .mockResolvedValueOnce(jsonResponse({ token: "approval-token" }))
      .mockResolvedValueOnce(jsonResponse({ status: "AGREED", version: 1 }))
      .mockResolvedValueOnce(
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
    expect(fetchMock()).toHaveBeenCalledTimes(4);
    const [url, init] = fetchMock().mock.calls[3];
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

  it("issues the approval token as the agreement's buyer", async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ buyer_id: "buyer-001" }))
      .mockResolvedValueOnce(jsonResponse({ token: "approval-token" }))
      .mockResolvedValueOnce(jsonResponse({ status: "AGREED", version: 1 }))
      .mockResolvedValueOnce(
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

    expect(result).toMatchObject({ decisionRecorded: true });
    const tokenCall = fetchMock().mock.calls.find(([url]) =>
      String(url).endsWith("/approval-token"),
    );
    expect(tokenCall).toBeDefined();
    const headers = tokenCall?.[1]?.headers as Record<string, string>;
    expect(headers["X-Actor-Id"]).toBe("buyer-001");
    expect(headers["X-Actor-Type"]).toBe("buyer");
  });

  it("keeps the recorded decision when the orchestrator resume fails", async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ buyer_id: "demo-buyer" }))
      .mockResolvedValueOnce(jsonResponse({ token: "approval-token" }))
      .mockResolvedValueOnce(jsonResponse({ status: "REJECTED", version: 1 }))
      .mockResolvedValueOnce(
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
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ buyer_id: "demo-buyer" }))
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
    expect(fetchMock()).toHaveBeenCalledTimes(3);
  });
});
