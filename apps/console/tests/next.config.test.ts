/**
 * @vitest-environment node
 */
import { describe, expect, it } from "vitest";
import nextConfig from "@/next.config";

async function readCsp(): Promise<string> {
  const headerSets = await nextConfig.headers?.();
  const csp = headerSets
    ?.flatMap(({ headers }) => headers)
    .find(({ key }) => key.toLowerCase() === "content-security-policy")?.value;

  expect(csp).toBeDefined();
  return csp as string;
}

function readDirective(csp: string, name: string): string[] {
  const directive = csp
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(`${name} `));

  return directive ? directive.split(/\s+/).slice(1) : [];
}

describe("next.config", () => {
  it("allows the CopilotKit Intelligence realtime gateway in connect-src", async () => {
    const csp = await readCsp();

    expect(readDirective(csp, "connect-src")).toContain(
      "wss://realtime.intelligence.copilotkit.ai",
    );
  });

  it("allows the PayPal v6 SDK origins the embedded checkout needs", async () => {
    const csp = await readCsp();

    expect(readDirective(csp, "script-src")).toEqual(
      expect.arrayContaining([
        "https://www.paypal.com",
        "https://www.sandbox.paypal.com",
        "https://c.paypal.com",
      ]),
    );
    expect(readDirective(csp, "frame-src")).toEqual(
      expect.arrayContaining([
        "https://www.paypal.com",
        "https://www.sandbox.paypal.com",
      ]),
    );
    expect(readDirective(csp, "connect-src")).toEqual(
      expect.arrayContaining([
        "https://www.paypal.com",
        "https://www.sandbox.paypal.com",
        "https://api-m.paypal.com",
        "https://api-m.sandbox.paypal.com",
        "https://c.paypal.com",
      ]),
    );
    expect(readDirective(csp, "img-src")).toEqual(
      expect.arrayContaining(["https://www.paypalobjects.com"]),
    );
  });
});
