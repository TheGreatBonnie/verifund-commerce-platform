import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const APP = path.resolve(__dirname, "../../app");
// Deliberately public: the showcase catalog and the healthy-seller
// projection are readable without a session. Everything else stays protected.
const PUBLIC = new Set([
  "sign-in/[[...sign-in]]/page.tsx",
  "sign-up/[[...sign-up]]/page.tsx",
  "api/webhooks/clerk/route.ts",
  "api/marketplace/products/route.ts",
  "api/registry/sellers/route.ts",
  "fulfillment/access/[token]/page.tsx",
  "fulfillment/access/[token]/actions.ts",
]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = path.join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

function isClientComponent(file: string): boolean {
  return readFileSync(file, "utf8").includes('"use client"');
}

describe("console guards", () => {
  const files = walk(APP);

  it("has no hardcoded demo identities", () => {
    const offenders = files.filter((file) => {
      const text = readFileSync(file, "utf8");
      return text.includes("demo-buyer") || text.includes("demo-user");
    });
    expect(offenders).toEqual([]);
  });

  it("protects every route handler and action", () => {
    const guarded = files.filter((file) => {
      const rel = path.relative(APP, file);
      if (PUBLIC.has(rel)) return false;
      const isRoute = file.endsWith("/route.ts");
      const isAction = file.endsWith("/actions.ts");
      const isPage = file.endsWith("/page.tsx");
      if (isRoute || isAction) return true;
      if (isPage) return !isClientComponent(file);
      return false;
    });
    const offenders = guarded.filter(
      (file) => !readFileSync(file, "utf8").includes("auth.protect()"),
    );
    expect(offenders).toEqual([]);
  });
});
