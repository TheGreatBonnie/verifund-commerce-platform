import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { FRONTEND_HITL_TOOL_NAMES } from "@/lib/hitl-tool-names";

const CHAT_SOURCE = path.join(
  __dirname,
  "../../features/chat/chat.tsx",
);

describe("FRONTEND_HITL_TOOL_NAMES", () => {
  it("covers every useHumanInTheLoop registration in the chat", () => {
    const source = readFileSync(CHAT_SOURCE, "utf8");
    const registered = new Set<string>();
    // Each registration declares `name: "..."` inside useHumanInTheLoop({...}).
    const pattern = /useHumanInTheLoop\(\s*\{[\s\S]*?\bname:\s*"([^"]+)"/g;
    for (const match of source.matchAll(pattern)) {
      registered.add(match[1]);
    }

    expect(registered.size).toBeGreaterThan(0);
    expect([...registered].sort()).toEqual([...FRONTEND_HITL_TOOL_NAMES].sort());
  });
});
