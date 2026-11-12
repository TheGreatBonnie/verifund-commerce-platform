"use client";

import { useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { saveConfigAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

export const CAPABILITIES = [
  { id: "commerce.catalog.search", label: "Product discovery", description: "Search the seller's catalog" },
  { id: "commerce.inventory.check", label: "Inventory checking", description: "Check availability in real time" },
  { id: "commerce.quote", label: "Quotation generation", description: "Return seller-approved quotations" },
  { id: "commerce.negotiate", label: "Price negotiation", description: "Respond to offers and counteroffers within policy" },
  { id: "commerce.agreement.review", label: "Agreement preparation", description: "Prepare proposed agreements against stored offers" },
  { id: "commerce.order", label: "Order management", description: "Create idempotent orders — recommended off until policies are settled" },
] as const;

type CapabilityGridProps = {
  agentId: string;
  initialAllowlist?: string[] | null;
  configVersion?: number | null;
};

export function CapabilityGrid({
  agentId,
  initialAllowlist,
  configVersion,
}: CapabilityGridProps) {
  // O14: every capability defaults ON. Never saved yet -> all checked.
  const [selected, setSelected] = useState<Record<string, boolean>>(() => {
    const base: Record<string, boolean> = {};
    for (const capability of CAPABILITIES) {
      base[capability.id] = initialAllowlist
        ? initialAllowlist.includes(capability.id)
        : true;
    }
    return base;
  });
  const [version, setVersion] = useState(configVersion ?? null);
  const [saved, setSaved] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const toggle = (id: string) =>
    setSelected((current) => ({ ...current, [id]: !current[id] }));

  const enabledCount = Object.values(selected).filter(Boolean).length;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        const allowlist = CAPABILITIES.filter((c) => selected[c.id]).map((c) => c.id);
        startTransition(async () => {
          const result = await saveConfigAction(agentId, {
            tool_allowlist: allowlist,
            ...(version != null ? { expected_config_version: version } : {}),
          });
          if (result.ok) {
            setVersion(result.data.config_version);
            setSaved(result.data.config_version);
          } else {
            if (result.status === 409) {
              setError("Someone else saved this agent first. Reload and try again.");
            } else {
              setError(result.error);
            }
          }
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
          What your agent is allowed to do. Everything is on by default, and every
          advertised card skill derives from these grants.
        </p>
        <span style={{ fontFamily: "var(--font-spline-sans-mono), monospace", fontSize: 9, color: "var(--muted)" }}>
          {enabledCount}/{CAPABILITIES.length} enabled
        </span>
      </div>

      <div
        role="group"
        aria-label="Agent capabilities"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))",
          gap: 8,
        }}
      >
        {CAPABILITIES.map((capability) => {
          const checked = selected[capability.id];
          return (
            <label
              key={capability.id}
              className="mm-capability-card"
              style={{
                cursor: "pointer",
                display: "flex",
                gap: 12,
                alignItems: "flex-start",
                padding: 12,
                opacity: checked ? 1 : 0.55,
                border: "1px solid var(--rule-strong)",
              }}
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(capability.id)}
                style={{ marginTop: 2, accentColor: "var(--signal)" }}
              />
              <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <strong style={{ fontSize: 12 }}>{capability.label}</strong>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>{capability.description}</span>
                <code style={{ fontSize: 9, color: "var(--muted)" }}>{capability.id}</code>
              </span>
            </label>
          );
        })}
      </div>

      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Button type="submit" loading={pending}>
          Save capabilities
        </Button>
        {saved != null ? (
          <span style={{ fontSize: 11, color: "var(--muted)" }}>Saved · config v{saved}</span>
        ) : null}
      </div>
    </form>
  );
}
