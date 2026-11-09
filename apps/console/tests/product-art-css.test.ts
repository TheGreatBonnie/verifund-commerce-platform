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

describe("chat/app mode toggle", () => {
  it("styles the segmented Chat | App control", () => {
    const toggle = readRule(".mm-mode-toggle");
    expect(toggle).toContain("display: flex");
  });
});

describe("chat threads drawer layout", () => {
  it("reserves the drawer column beside the chat", () => {
    const layout = readRule(".mm-chat-drawer-layout");
    expect(layout).toContain("display: grid");
    expect(layout).toContain(
      "var(--cpk-drawer-reserved-width, 320px)",
    );
  });
});

describe("chat full-viewport flex chain", () => {
  it("fills the container width and viewport height", () => {
    const full = readRule(".mm-chat-full");
    expect(full).toContain("flex: 1");
    expect(full).toContain("min-height: 0");
    expect(full).not.toContain("max-width: 960px");
    expect(full).not.toContain("height: 100dvh");

    const layout = readRule(".mm-chat-drawer-layout");
    expect(layout).toContain("flex: 1");
    expect(layout).not.toContain("height: 100dvh");

    const surface = readRule(".mm-chat-surface");
    expect(surface).toContain("flex: 1");
    expect(surface).toContain("min-height: 0");

    const main = readRule(".mm-console-main.chat-only");
    expect(main).toContain("padding: 0");
  });

  it("pins the chat input: main never scrolls, messages do", () => {
    // .mm-console-main has overflow: auto by default; in chat-only mode it
    // must clip instead, or the whole page scrolls and pushes the input out
    // of the viewport as the agent response grows.
    const main = readRule(".mm-console-main.chat-only");
    expect(main).toContain("min-height: 0");
    expect(main).toContain("overflow: hidden");

    // The message area is the only scrollable region, like the chat rail's
    // internals (max-height + overflow-y: auto on .mm-chat-rail).
    const surface = readRule(".mm-chat-surface");
    expect(surface).toContain("overflow-y: auto");
  });
});

describe("chat-app shell bounds", () => {
  it("keeps the drawer pinned and the shell height bounded in chat-only mode", () => {
    // min-height-only shells grow with content, so the page scrolls and both
    // the input and the drawer drift out of the viewport.
    const shell = readRule(".mm-app-frame:has(.mm-console-main.chat-only)");
    expect(shell).toContain("height: 100dvh");
    expect(shell).toContain("overflow: hidden");

    const drawer = readRule(
      ".mm-chat-drawer-layout > copilotkit-threads-drawer",
    );
    expect(drawer).toContain("position: sticky");
    expect(drawer).toContain("top: 0");
    expect(drawer).toContain("height: 100%");
    expect(drawer).toContain("overflow-y: auto");
  });
});
