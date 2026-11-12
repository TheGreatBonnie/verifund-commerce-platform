import { describe, expect, it } from "vitest";

import { invitationRedirect } from "@/lib/invitation";

describe("invitationRedirect", () => {
  it("preserves the token through sign-in", () => {
    expect(invitationRedirect("tok_1")).toBe(
      "/sign-in?redirect_url=%2Fseller%2Fonboarding%3Finvitation%3Dtok_1"
    );
  });
});
