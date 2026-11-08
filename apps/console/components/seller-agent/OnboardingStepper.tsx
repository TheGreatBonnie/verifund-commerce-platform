"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const STEPS = [
  "profile",
  "agent_setup",
  "policies",
  "integrations",
  "testing",
  "verification",
  "activation",
] as const;

const LABELS: Record<(typeof STEPS)[number], string> = {
  profile: "Profile",
  verification: "Verification",
  integrations: "Integrations",
  agent_setup: "Agent setup",
  policies: "Policies",
  testing: "Testing",
  activation: "Activation",
};

export function OnboardingStepper() {
  const pathname = usePathname();
  const current = STEPS.find((step) => pathname.endsWith(`/${step}`)) ?? null;
  const currentIndex = current ? STEPS.indexOf(current) : -1;

  return (
    <ol
      aria-label="Onboarding steps"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 6,
        listStyle: "none",
        margin: "0 0 18px",
        padding: 0,
      }}
    >
      {STEPS.map((step, index) => {
        const isCurrent = step === current;
        const isDone = currentIndex > -1 && index < currentIndex;
        return (
          <li key={step}>
            <Link
              href={`/seller/onboarding/${step}`}
              aria-current={isCurrent ? "step" : undefined}
              className={cn("mm-seller-format-chip", isCurrent && "is-current")}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 6,
                textDecoration: "none",
                padding: "4px 8px",
                border: "1px solid var(--rule-strong)",
                background: isCurrent
                  ? "var(--ink)"
                  : isDone
                    ? "var(--panel)"
                    : "transparent",
                color: isCurrent ? "var(--paper)" : "var(--ink-soft)",
                fontSize: 10,
              }}
            >
              <span
                aria-hidden="true"
                style={{
                  fontFamily: "var(--font-spline-sans-mono), monospace",
                  opacity: 0.7,
                }}
              >
                {String(index + 1).padStart(2, "0")}
              </span>
              {LABELS[step]}
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
