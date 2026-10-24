import { Check } from "lucide-react";

const STEPS = ["Brief", "Discover", "RFQ", "Negotiate", "Approve", "Order"] as const;

const STAGE_INDEX: Record<string, number> = {
  new: 0,
  needs_clarification: 0,
  brief_ready: 0,
  sellers_discovered: 1,
  failed: 1,
  sourcing_planned: 2,
  negotiating: 3,
  awaiting_approval: 4,
  approved: 4,
  rejected: 4,
  ordering: 5,
  ordered: 5,
  order_failed: 5,
  no_award: 4,
};

type StageStepperProps = {
  stage?: string;
};

export function StageStepper({ stage = "new" }: StageStepperProps) {
  const current = STAGE_INDEX[stage] ?? 0;
  const rejected = stage === "rejected" || stage === "no_award";

  return (
    <nav className="mm-stepper" aria-label="Sourcing stages">
      <ol>
        {STEPS.map((label, index) => {
          const complete = index < current;
          const active = index === current;
          const status = complete
            ? "complete"
            : active
              ? rejected && index === 4
                ? "stopped"
                : "current"
              : "pending";
          return (
            <li
              key={label}
              className={`mm-step ${status}`}
              aria-current={active ? "step" : undefined}
            >
              <span className="mm-step-mark" aria-hidden="true">
                {complete ? <Check size={12} strokeWidth={2.4} /> : index + 1}
              </span>
              <span className="mm-step-label">{label}</span>
              <span className="sr-only">{status}</span>
            </li>
          );
        })}
      </ol>
      <span className="mm-stepper-state" aria-live="polite">
        {stage === "rejected"
          ? "Award rejected"
          : stage === "ordered"
            ? "Order confirmed"
            : stage === "awaiting_approval"
              ? "Human checkpoint"
              : STEPS[current]}
      </span>
    </nav>
  );
}
