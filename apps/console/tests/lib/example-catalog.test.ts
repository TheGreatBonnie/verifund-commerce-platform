import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const PUBLIC_DIR = path.resolve(__dirname, "../../public");

type Product = {
  sku: string;
  list_unit_price_cents: number;
  initial_unit_price_cents: number;
  floor_unit_price_cents: number;
};

function exampleCatalog(): { products: Product[] } {
  const raw = readFileSync(path.join(PUBLIC_DIR, "example-catalog.json"), "utf8");
  return JSON.parse(raw);
}

describe("bundled example catalog", () => {
  it("parses as JSON with products", () => {
    const parsed = exampleCatalog();
    expect(Array.isArray(parsed.products)).toBe(true);
    expect(parsed.products.length).toBeGreaterThan(0);
  });

  it("enforces floor <= initial <= list for every product", () => {
    for (const product of exampleCatalog().products) {
      expect(
        product.floor_unit_price_cents,
        `${product.sku} floor`,
      ).toBeLessThanOrEqual(product.initial_unit_price_cents);
      expect(
        product.initial_unit_price_cents,
        `${product.sku} initial`,
      ).toBeLessThanOrEqual(product.list_unit_price_cents);
    }
  });

  it("has unique SKUs", () => {
    const skus = exampleCatalog().products.map((p) => p.sku);
    expect(new Set(skus).size).toBe(skus.length);
  });

  it("ships the yaml example and the annotated template", () => {
    const yaml = readFileSync(path.join(PUBLIC_DIR, "example-catalog.yaml"), "utf8");
    expect(yaml).toContain("version: 1");
    expect(yaml).toContain("products:");
    const template = readFileSync(
      path.join(PUBLIC_DIR, "example-catalog-template.yaml"),
      "utf8",
    );
    expect(template).toContain("floor_unit_price_cents <= initial_unit_price_cents <= list_unit_price_cents");
  });
});
