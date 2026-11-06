import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("runs API tenancy", () => {
  it("forwards the session organization with an internal token", () => {
    const route = readFileSync(
      path.resolve(__dirname, "../../app/api/runs/route.ts"),
      "utf8",
    );
    expect(route).toContain("auth.protect()");
    expect(route).toContain("consoleSession()");
    expect(route).toContain("organization_id");
    expect(route).toContain("x-verifund-internal-token");
  });
});
