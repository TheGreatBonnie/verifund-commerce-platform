"use client";

import { useState, useTransition } from "react";
import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { runTestsAction } from "@/app/(seller-onboarding)/seller/onboarding/actions";
import type { TestCheck } from "@/lib/agent-types";

const CHECK_LABELS: Record<string, string> = {
  auth: "Agent credential verifies",
  catalog: "Catalog returns a known SKU",
  pricing: "Pricing bounds refuse out-of-range offers",
  a2a: "Mediated A2A round trip returns an offer",
  authority: "Actions above your authority escalate",
  revocation: "A revoked credential stops passing",
};

type TestResultsPanelProps = {
  agentId: string;
  latestRun?: {
    passed?: string;
    checks?: TestCheck[];
    created_at?: string;
  } | null;
};

export function TestResultsPanel({ agentId, latestRun }: TestResultsPanelProps) {
  const [checks, setChecks] = useState<TestCheck[] | null>(latestRun?.checks ?? null);
  const [passed, setPassed] = useState<boolean | null>(
    latestRun?.passed != null ? latestRun.passed === "1" : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const run = () => {
    setError(null);
    startTransition(async () => {
      const result = await runTestsAction(agentId);
      if (result.ok) {
        setChecks(result.data.checks);
        setPassed(result.data.passed);
      } else {
        setError(result.error);
      }
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <p style={{ margin: 0, color: "var(--muted)", fontSize: 12 }}>
        Real checks against the sandbox profile, not placeholders. Activation stays
        blocked until all six pass on the current policy and card.
      </p>

      <div>
        <Button onClick={run} loading={pending}>
          {checks ? "Run all checks again" : "Run all checks"}
        </Button>
      </div>

      {error ? (
        <p role="alert" style={{ margin: 0, color: "var(--danger, #b91c1c)", fontSize: 12 }}>
          {error}
        </p>
      ) : null}

      {passed !== null && !error ? (
        <p
          role="status"
          style={{
            margin: 0,
            fontSize: 12,
            color: passed ? "var(--signal-deep)" : "var(--danger, #b91c1c)",
          }}
        >
          {passed
            ? "All six checks pass. Activation is unblocked."
            : "At least one check failed — fix it below and re-run."}
        </p>
      ) : null}

      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {(checks ?? Object.keys(CHECK_LABELS).map((name) => ({ name, passed: false, detail: "Not run yet" }))).map((check) => {
          const hasRun = checks != null;
          const Icon = !hasRun ? CircleDashed : check.passed ? CheckCircle2 : XCircle;
          const color = !hasRun
            ? "var(--muted)"
            : check.passed
              ? "var(--signal-deep)"
              : "var(--danger, #b91c1c)";
          return (
            <li
              key={check.name}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: 10,
                padding: "8px 10px",
                border: "1px solid var(--rule-strong)",
              }}
            >
              <Icon size={15} aria-hidden="true" style={{ color, flexShrink: 0, marginTop: 1 }} />
              <span style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ fontSize: 12, fontWeight: 600 }}>
                  {CHECK_LABELS[check.name] ?? check.name}
                </span>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>{check.detail}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
