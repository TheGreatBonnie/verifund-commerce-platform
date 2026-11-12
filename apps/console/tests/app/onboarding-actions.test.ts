import { beforeEach, describe, expect, it, vi } from "vitest";

const { controlPlaneMock, protectMock } = vi.hoisted(() => ({
  controlPlaneMock: vi.fn(),
  protectMock: vi.fn(),
}));

vi.mock("@clerk/nextjs/server", () => ({
  auth: Object.assign(vi.fn(), { protect: protectMock }),
}));

vi.mock("@/lib/control-plane", () => ({
  controlPlaneForUser: controlPlaneMock,
}));

import { submitVerificationAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

describe("submitVerificationAction", () => {
  beforeEach(() => {
    controlPlaneMock.mockClear();
    protectMock.mockResolvedValue({ userId: "user_1" });
    controlPlaneMock.mockResolvedValue(
      new Response(JSON.stringify({ verification_status: "pending" }), { status: 200 })
    );
  });

  it("sends payout_email in the verification submit body", async () => {
    await submitVerificationAction({ "kyc": "doc" }, "seller@paypal.example");
    const init = controlPlaneMock.mock.calls[0][1];
    expect(JSON.parse(init.body).payout_email).toBe("seller@paypal.example");
  });
});
