import { Status } from "@/components/ui/status";
import { stageLabel } from "@/lib/format";

const TONE: Record<string, "neutral" | "signal" | "error" | "amber"> = {
  ordered: "signal",
  approved: "signal",
  rejected: "error",
  failed: "error",
  order_failed: "error",
  no_award: "error",
};

export function RunStatusBadge({ stage }: { stage?: string }) {
  return <Status tone={TONE[stage ?? ""] ?? "neutral"}>{stageLabel(stage)}</Status>;
}
