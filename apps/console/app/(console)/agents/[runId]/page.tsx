"use client";

import { useParams } from "next/navigation";
import { RunDetail } from "@/features/deal-room/run-detail";

export default function AgentRunPage() {
  const params = useParams();
  const runId = params?.runId;

  if (typeof runId !== "string") return null;

  return (
    <RunDetail
      runId={runId}
      showNegotiationTimeline={false}
      showStageStepper={false}
    />
  );
}
