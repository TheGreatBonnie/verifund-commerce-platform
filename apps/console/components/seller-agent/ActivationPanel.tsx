"use client";

import { useState, useTransition } from "react";
import { CheckCircle2, Circle, Rocket } from "lucide-react";
import { Button } from "@/components/ui/button";
import { activateAgentAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";

type ActivationPanelProps = {
  agentId: string;
  verified: boolean;
  testPassed: boolean | null;
  hasCard: boolean;
};

export function ActivationPanel({
  agentId,
  verified,
  testPassed,
  hasCard,
}: ActivationPanelProps) {
  const [activated, setActivated] = useState<"idle" | "done">("idle");
  const [registryPublished, setRegistryPublished] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const allReady = verified && testPassed === true && hasCard;

  const checklist: Array<{ label: string; done: boolean | null }> = [
    { label: "Organization verified by Verifund", done: verified },
    { label: "Passing test run for the current policy hash and card hash", done: testPassed },
    { label: "At least one active agent credential", done: testPassed },
    { label: "Agent card preview available", done: hasCard },
  ];

  if (activated === "done") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <CheckCircle2 size={22} aria-hidden="true" style={{ color: "var(--signal-deep)" }} />
          <strong style={{ fontSize: 14 }}>Your seller agent is live.</strong>
        </div>
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
          It now appears in Verifund discovery for active buyers.
          {registryPublished ? " The registry projection is published." : " Publication is pending a registry retry."}
        </p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <a className="mm-button mm-button-sm" href="/seller/agent">Open agent portal</a>
          <a className="mm-button mm-button-outline mm-button-sm" href="/marketplace">View marketplace</a>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {checklist.map((item) => {
          const Icon = item.done ? CheckCircle2 : Circle;
          const color = item.done ? "var(--signal-deep)" : "var(--muted)";
          return (
            <li
              key={item.label}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "8px 10px",
                border: "1px solid var(--rule-strong)",
                fontSize: 12,
                color: item.done ? "var(--ink)" : "var(--muted)",
              }}
            >
              <Icon size={15} aria-hidden="true" style={{ color, flexShrink: 0 }} />
              {item.label}
            </li>
          );
        })}
      </ul>

      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}

      <div>
        <Button
          loading={pending}
          disabled={!allReady}
          leftIcon={<Rocket size={13} aria-hidden="true" />}
          onClick={() => {
            setError(null);
            startTransition(async () => {
              const result = await activateAgentAction(agentId);
              if (result.ok) {
                setRegistryPublished(result.data.registry_published ?? null);
                setActivated("done");
              } else {
                setError(result.error);
              }
            });
          }}
        >
          Activate seller agent
        </Button>
      </div>
      {!allReady ? (
        <p style={{ margin: 0, color: "var(--muted)", fontSize: 11 }}>
          Complete the checklist above — activation is disabled until everything is green.
        </p>
      ) : null}
    </div>
  );
}
