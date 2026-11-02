/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";
import nextConfig from "@/next.config";

describe("next.config", () => {
  it("allows the CopilotKit Intelligence realtime gateway in connect-src", async () => {
    const headerSets = await nextConfig.headers?.();
    const csp = headerSets
      ?.flatMap(({ headers }) => headers)
      .find(({ key }) => key.toLowerCase() === "content-security-policy")?.value;

    expect(csp).toBeDefined();

    const connectSrc = csp
      ?.split(";")
      .map((directive) => directive.trim())
      .find((directive) => directive.startsWith("connect-src "));

    expect(connectSrc).toContain("wss://realtime.intelligence.copilotkit.ai");
  });
});
