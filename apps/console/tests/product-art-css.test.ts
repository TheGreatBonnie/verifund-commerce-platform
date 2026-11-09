/**
 * @vitest-environment node
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

function readRule(selector: string): string {
  const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
  const match = css.match(
    new RegExp(
      `${selector.replace(/[.*+?^${"{}"}()|[\]\\]/g, "\\$&")}\\s*\\{([^}]*)\\}`,
    ),
  );
  return match?.[1] ?? "";
}

describe("chat product card art", () => {
  it("gives recommendation images a photo-friendly aspect ratio", () => {
    const rule = readRule(
      ".mm-product-search-card .mm-product-search-art",
    );
    // A 72px-tall band inside a ~340px-wide card is ~4.5:1, so
    // object-fit: cover keeps only a thin central slice of the photo.
    expect(rule).toContain("aspect-ratio: 16 / 10");
    expect(rule).not.toContain("min-height: 72px");
  });
});

describe("chat recommendation track", () => {
  it("lays cards out horizontally and scrolls one at a time", () => {
    const grid = readRule(".mm-product-search .mm-product-grid");
    // The shared .mm-product-grid rule sets 5 explicit columns; combined with
    // grid-auto-flow: column the cards squeezed into one narrow column and
    // stacked in implicit rows. A flex row avoids that interaction.
    expect(grid).toContain("display: flex");
    expect(grid).toContain("overflow-x: auto");
    expect(grid).toContain("scroll-snap-type: x mandatory");
    expect(grid).not.toContain("grid-auto-flow");
    expect(grid).not.toContain("grid-template-columns");

    const card = readRule(".mm-product-search-card");
    expect(card).toContain("flex: 0 0 260px");
    expect(card).toContain("scroll-snap-align: start");
    expect(card).not.toContain("max-width: 340px");
  });
});
