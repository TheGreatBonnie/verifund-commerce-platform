"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { generateInstructionsAction, saveConfigAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

type InstructionEditorProps = {
  agentId: string;
  initialInstructions?: string;
  configVersion?: number | null;
  maxLength?: number;
};

export const INSTRUCTIONS_MAX = 4096;

export function InstructionEditor({
  agentId,
  initialInstructions,
  configVersion,
  maxLength = INSTRUCTIONS_MAX,
}: InstructionEditorProps) {
  const [instructions, setInstructions] = useState(initialInstructions ?? "");
  const [version, setVersion] = useState(configVersion ?? null);
  const [saved, setSaved] = useState<number | null>(null);
  const [generated, setGenerated] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [pending, startTransition] = useTransition();

  const remaining = maxLength - instructions.length;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        setConflict(false);
        startTransition(async () => {
          const result = await saveConfigAction(agentId, {
            instructions,
            ...(version != null ? { expected_config_version: version } : {}),
          });
          if (result.ok) {
            setVersion(result.data.config_version);
            setSaved(result.data.config_version);
          } else {
            if (result.status === 409) setConflict(true);
            setError(result.error);
          }
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 10 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <label htmlFor="agent-instructions" className="mm-kicker">
          Agent instructions
        </label>
        <span
          aria-live="polite"
          style={{
            fontFamily: "var(--font-spline-sans-mono), monospace",
            fontSize: 9,
            color: remaining < 0 ? "var(--danger, #b91c1c)" : "var(--muted)",
          }}
        >
          {remaining} chars left
        </span>
      </div>
      <textarea
        id="agent-instructions"
        rows={9}
        maxLength={maxLength}
        value={instructions}
        onChange={(event) => setInstructions(event.target.value)}
        placeholder="How should your agent present your business, qualify buyers, and negotiate? Be specific — this steers every turn the agent takes."
        style={{
          minHeight: 160,
          padding: 10,
          border: "1px solid var(--rule-strong)",
          background: "var(--panel)",
          color: "var(--ink)",
          font: "inherit",
          fontSize: 12,
          lineHeight: 1.45,
        }}
      />
      <p style={{ margin: 0, color: "var(--muted)", fontSize: 11 }}>
        Stored with your agent config. Policy bounds and catalog floors always win;
        instructions steer tone, qualification, and negotiation posture.
      </p>
      {conflict ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          Someone else saved this agent first. Reload the page to fetch the latest version.
        </p>
      ) : null}
      {error && !conflict ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Button type="submit" loading={pending} disabled={remaining < 0}>
          Save instructions
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          loading={generating}
          onClick={() => {
            setError(null);
            setGenerating(true);
            void (async () => {
              const result = await generateInstructionsAction(agentId);
              setGenerating(false);
              if (result.ok) {
                setInstructions(result.data.instructions);
                setGenerated(true);
                setSaved(null);
              } else {
                setError(result.error);
              }
            })();
          }}
        >
          Auto-generate from catalog
        </Button>
        {generated ? (
          <span style={{ fontSize: 11, color: "var(--muted)" }}>Generated — review, then Save</span>
        ) : null}
        {saved != null ? (
          <span style={{ fontSize: 11, color: "var(--muted)" }}>
            Saved · config v{saved}
          </span>
        ) : null}
      </div>
    </form>
  );
}
