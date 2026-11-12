import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const stepper = readFileSync(
  path.resolve(__dirname, "../../components/seller-agent/OnboardingStepper.tsx"),
  "utf8",
);
const onboarding = readFileSync(
  path.resolve(__dirname, "../../lib/onboarding.ts"),
  "utf8",
);

function stepOrder(source: string): string[] {
  const block = source.match(/const STEPS = \[([\s\S]*?)\]/)?.[1] ?? "";
  return [...block.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
}

describe("OnboardingStepper order (backend contract)", () => {
  it("renders steps in backend order: profile → agent_setup → policies → integrations → testing → verification → activation", () => {
    expect(stepOrder(stepper)).toEqual(stepOrder(onboarding));
  });
});
