import { describe, expect, it } from "vitest";

import { sellerEntryPath } from "@/lib/onboarding";

describe("sellerEntryPath", () => {
  it("routes an unverified profile to profile step", () => {
    expect(
      sellerEntryPath(
        { verification_status: "unverified" },
        { current_step: "profile", status: "in_progress" }
      )
    ).toBe("/seller/onboarding/profile");
  });

  it("routes an unverified profile to verification", () => {
    expect(
      sellerEntryPath(
        { verification_status: "unverified" },
        { current_step: "verification", status: "in_progress" }
      )
    ).toBe("/seller/onboarding/verification");
  });

  it("routes a verified profile to the workspace", () => {
    expect(sellerEntryPath({ verification_status: "verified" }, null)).toBe(
      "/seller/dashboard"
    );
  });
});
