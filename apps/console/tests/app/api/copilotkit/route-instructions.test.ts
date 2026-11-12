import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const routePath = path.resolve(
  __dirname,
  "../../../../app/api/copilotkit/[[...slug]]/route.ts",
);
const source = fs.readFileSync(routePath, "utf8");

describe("orchestrator sourcing mandate instructions", () => {
  it("requires the request_sourcing_mandate HITL gate before Buyer handoff", () => {
    expect(source).toContain("request_sourcing_mandate");
    expect(source).toMatch(/confirmed\s*===?\s*true|confirmed.*true/i);
    expect(source).toMatch(/confirmed\s*===?\s*false|user_cancelled/i);
  });

  it("states cancel stops handoff with no sourcing and no order", () => {
    expect(source).toMatch(/no sourcing/i);
    expect(source).toMatch(/no order/i);
    expect(source).toMatch(/do not contact the Buyer|without contacting the Buyer/i);
  });

  it("keeps mandate context read-only and forbids order placement", () => {
    expect(source).toMatch(/read-only/i);
    expect(source).toMatch(/Do not place an order|do not place an order/);
  });
});
