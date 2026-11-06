import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const full = path.join(dir, entry);
    return statSync(full).isDirectory() ? walk(full) : [full];
  });
}

describe("seller cookie removal", () => {
  it("does not use the seller cookie for staff access", () => {
    const root = path.resolve(__dirname, "../../app/seller");
    const files = walk(root);
    const offenders = files.filter((f) =>
      /readSellerSession|SELLER_COOKIE|saveSellerToken/.test(readFileSync(f, "utf8"))
    );
    expect(offenders).toEqual([]);
  });
});
