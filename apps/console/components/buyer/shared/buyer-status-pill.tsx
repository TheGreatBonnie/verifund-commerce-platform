import { cn } from "@/lib/cn";

export type BuyerStatusTone = "amber" | "signal" | "danger" | "neutral";

const AMBER = /REVIEW|WAIT|AWAIT|PENDING|INSPECT|VERIF|PROCESS|SUBMIT/i;
const SIGNAL = /PAID|COMPLETE|FUND|RELEASE|CONFIRM|DELIVER|RESOLV/i;
const DANGER = /ISSUE|DISPUT|FAIL|REJECT|CANCEL|EXPIR|OVERDUE/i;

export function toneForStatus(value: string): BuyerStatusTone {
  if (DANGER.test(value)) return "danger";
  if (SIGNAL.test(value)) return "signal";
  if (AMBER.test(value)) return "amber";
  return "neutral";
}

export function BuyerStatusPill({
  value,
  label,
  tone,
  className,
}: {
  value: string;
  label?: string;
  tone?: BuyerStatusTone;
  className?: string;
}) {
  const resolved = tone ?? toneForStatus(value);
  return (
    <span className={cn("mm-buyer-status-pill", `is-${resolved}`, className)}>
      {label ?? value}
    </span>
  );
}
