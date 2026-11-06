"use client";

import { useState, useTransition } from "react";
import { ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { savePoliciesAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

const ESCALATION_RULES = [
  "Offers below your configured floor price require human sign-off.",
  "Offers above your discount cap require human sign-off.",
  "Non-standard terms (payment, delivery, warranty overrides) require human sign-off.",
] as const;

const AUTONOMY_MODES = [
  { value: "read_only", label: "Read-only", detail: "Describe products; never negotiate or commit." },
  { value: "assisted", label: "Assisted", detail: "Draft every offer; a human approves each one." },
  { value: "policy_bounded", label: "Policy-bounded", detail: "Negotiate within your caps and floors autonomously." },
] as const;

type PolicyPanelProps = {
  agentId: string;
  initialMaxDiscountBps?: number | null;
  initialAutonomyMode?: string | null;
  configVersion?: number | null;
};

export function PolicyPanel({
  agentId,
  initialMaxDiscountBps,
  initialAutonomyMode,
  configVersion,
}: PolicyPanelProps) {
  const [maxDiscountBps, setMaxDiscountBps] = useState<number>(
    initialMaxDiscountBps ?? 1000,
  );
  const [autonomyMode, setAutonomyMode] = useState<string>(
    initialAutonomyMode ?? "policy_bounded",
  );
  const [version, setVersion] = useState(configVersion ?? null);
  const [saved, setSaved] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const discountPercent = (maxDiscountBps / 100).toFixed(maxDiscountBps % 100 === 0 ? 0 : 1);

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await savePoliciesAction(agentId, {
            max_discount_bps: maxDiscountBps,
            autonomy_mode: autonomyMode as "read_only" | "assisted" | "policy_bounded",
            ...(version != null ? { expected_config_version: version } : {}),
          });
          if (result.ok) {
            setVersion(result.data.config_version);
            setSaved(result.data.config_version);
          } else {
            setError(
              result.status === 409
                ? "Someone else saved this agent first. Reload and try again."
                : result.error,
            );
          }
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 14 }}
    >
      <div className="mm-seller-field-grid">
        <label className="mm-seller-field">
          <span>Max discount cap</span>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input
              type="range"
              min={0}
              max={10000}
              step={50}
              value={maxDiscountBps}
              onChange={(event) => setMaxDiscountBps(Number(event.target.value))}
              aria-label="Maximum discount in basis points"
              style={{ flex: 1, accentColor: "var(--signal)" }}
            />
            <code style={{ minWidth: 56, fontSize: 12 }}>{discountPercent}%</code>
          </div>
          <input
            type="number"
            min={0}
            max={10000}
            step={50}
            value={maxDiscountBps}
            onChange={(event) =>
              setMaxDiscountBps(
                Math.max(0, Math.min(10000, Number(event.target.value) || 0)),
              )
            }
            aria-label="Maximum discount in basis points (exact)"
          />
          <span style={{ textTransform: "none", fontSize: 10, color: "var(--muted)" }}>
            1000 = 10% off list, capped at whatever your catalog floors allow.
          </span>
        </label>

        <fieldset className="mm-seller-field" style={{ border: 0, padding: 0, margin: 0 }}>
          <span id="autonomy-mode-label">Autonomy mode</span>
          <div role="radiogroup" aria-labelledby="autonomy-mode-label" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {AUTONOMY_MODES.map((mode) => (
              <label
                key={mode.value}
                style={{
                  display: "flex",
                  gap: 10,
                  alignItems: "flex-start",
                  padding: 10,
                  border: "1px solid var(--rule-strong)",
                  cursor: "pointer",
                  background:
                    autonomyMode === mode.value ? "var(--panel)" : "transparent",
                }}
              >
                <input
                  type="radio"
                  name="autonomy_mode"
                  value={mode.value}
                  checked={autonomyMode === mode.value}
                  onChange={() => setAutonomyMode(mode.value)}
                  style={{ marginTop: 2, accentColor: "var(--signal)" }}
                />
                <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <strong style={{ fontSize: 12 }}>{mode.label}</strong>
                  <span style={{ fontSize: 11, color: "var(--muted)" }}>{mode.detail}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>

      <div
        style={{
          border: "1px solid var(--rule-strong)",
          padding: 10,
          background: "var(--paper)",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            marginBottom: 6,
            color: "var(--ink-soft)",
          }}
        >
          <ShieldCheck size={14} aria-hidden="true" />
          <span className="mm-kicker" style={{ color: "inherit" }}>
            Always on — human escalation
          </span>
        </div>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 11, color: "var(--muted)" }}>
          {ESCALATION_RULES.map((rule) => (
            <li key={rule}>{rule}</li>
          ))}
        </ul>
      </div>

      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Button type="submit" loading={pending}>
          Save policy
        </Button>
        {saved != null ? (
          <span style={{ fontSize: 11, color: "var(--muted)" }}>Saved · config v{saved}</span>
        ) : null}
      </div>
    </form>
  );
}
