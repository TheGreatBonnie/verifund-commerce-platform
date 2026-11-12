"use client";

import { useState, useTransition } from "react";
import { CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  createAgentAction,
  saveConfigAction,
} from "@/app/(seller-onboarding)/seller/onboarding/actions";

type AgentIdentityPanelProps = {
  agentId: string | null;
  status?: string | null;
  initialName?: string;
  cardUrl?: string | null;
  configVersion?: number | null;
};

export function AgentIdentityPanel({
  agentId,
  status,
  initialName,
  cardUrl,
  configVersion,
}: AgentIdentityPanelProps) {
  const [displayName, setDisplayName] = useState(initialName ?? "");
  const [version, setVersion] = useState(configVersion ?? null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<number | null>(null);
  const [pending, startTransition] = useTransition();

  // Onboarding is complete only when the agent is active.
  const onboardingComplete = status === "active";

  if (agentId && onboardingComplete) {
    // Read-only once active
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div className="mm-seller-field" style={{ margin: 0 }}>
            <span>Agent ID</span>
            <code style={{ fontSize: 12 }}>{agentId}</code>
          </div>
          <Badge>{status}</Badge>
        </div>
        {displayName ? (
          <div className="mm-seller-field" style={{ margin: 0 }}>
            <span>Display name</span>
            <span>{displayName}</span>
          </div>
        ) : null}
        {cardUrl ? (
          <a className="mm-button mm-button-outline mm-button-sm" href={cardUrl} target="_blank" rel="noreferrer" style={{ alignSelf: "flex-start", textDecoration: "none" }}>
            Open public agent card
          </a>
        ) : null}
      </div>
    );
  }

  if (agentId) {
    // Agent exists but onboarding is not complete: keep the display name field visible/editable.
    return (
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setError(null);
          const name = displayName.trim();
          if (!name) {
            setError("Display name is required.");
            return;
          }
          startTransition(async () => {
            const result = await saveConfigAction(agentId, {
              name,
              ...(version != null ? { expected_config_version: version } : {}),
            });
            if (result.ok) {
              setVersion(result.data.config_version);
              setSaved(result.data.config_version);
            } else {
              setError(result.error);
            }
          });
        }}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
      >
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
          <div className="mm-seller-field" style={{ margin: 0 }}>
            <span>Agent ID</span>
            <code style={{ fontSize: 12 }}>{agentId}</code>
          </div>
          <Badge>{status ?? "draft"}</Badge>
        </div>
        <label className="mm-seller-field" style={{ margin: 0 }}>
          <span>Display name</span>
          <input
            type="text"
            maxLength={128}
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="e.g. Acme Industrial Sales"
          />
        </label>
        {error ? (
          <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
            {error}
          </p>
        ) : null}
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Button type="submit" loading={pending} disabled={!displayName.trim()}>
            Save display name
          </Button>
          {saved != null ? (
            <span style={{ fontSize: 11, color: "var(--muted)" }}>Saved · config v{saved}</span>
          ) : null}
        </div>
        {cardUrl ? (
          <a className="mm-button mm-button-outline mm-button-sm" href={cardUrl} target="_blank" rel="noreferrer" style={{ alignSelf: "flex-start", textDecoration: "none" }}>
            Open public agent card
          </a>
        ) : null}
      </form>
    );
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        const name = displayName.trim();
        startTransition(async () => {
          const result = await createAgentAction(name || undefined);
          if (!result.ok) setError(result.error);
        });
      }}
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
        Creating your seller agent provisions a machine identity on the Verifund
        network. Nothing is visible to buyers until you activate it.
      </p>
      <label className="mm-seller-field" style={{ margin: 0 }}>
        <span>Display name (optional)</span>
        <input
          type="text"
          maxLength={128}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
          placeholder="e.g. Acme Industrial Sales"
        />
      </label>
      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}
      <div>
        <Button type="submit" loading={pending} leftIcon={<CheckCircle2 size={13} aria-hidden="true" />}>
          Create seller agent
        </Button>
      </div>
    </form>
  );
}
