"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Chat } from "@/features/chat/chat";
import { ConversationHistory } from "@/features/deal-room/components/conversation-history";
import { shortId, stageLabel } from "@/lib/format";
import { config } from "@/lib/config";
import { RunDetailWorkspace } from "./components/run-detail-workspace";
import { StageStepper } from "./components/stage-stepper";
import { useRunDetail } from "./hooks/use-run-detail";

export function RunDetail({
  runId,
  showNegotiationTimeline = true,
  showStageStepper = true,
  fillViewport = false,
}: {
  runId: string;
  showNegotiationTimeline?: boolean;
  showStageStepper?: boolean;
  fillViewport?: boolean;
}) {
  const router = useRouter();
  const detail = useRunDetail(runId);

  const handleNewRun = () => {
    if (detail.isRunning) return;
    const nextRunId = crypto.randomUUID();
    detail.resetForRun(nextRunId);
    router.push(`/runs/${nextRunId}`);
  };

  return (
    <div className={`mm-run-detail${fillViewport ? " mm-run-detail-fill" : ""}`}>
      <header className="mm-run-detail-header">
        <div className="mm-run-detail-title">
          <Link href="/runs" className="mm-run-back-link">
            <ArrowLeft size={13} aria-hidden="true" /> Runs
          </Link>
          <p className="mm-kicker">Buyer workspace · {stageLabel(detail.stage)}</p>
          <h1>Sourcing run <span>{shortId(runId, 12)}</span></h1>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleNewRun}
          disabled={detail.isRunning}
          leftIcon={<RefreshCcw size={13} aria-hidden="true" />}
        >
          New run
        </Button>
      </header>

      {showStageStepper ? <StageStepper stage={detail.stage} /> : null}

      <RunDetailWorkspace
        state={detail.state}
        runId={runId}
        showNegotiationTimeline={showNegotiationTimeline}
        isReady={detail.isReady}
        isRunning={detail.isRunning}
        onRunSample={() => void detail.startRun()}
        conversation={
          <>
            <ConversationHistory activeThreadId={runId} />
            <Chat
            variant="embedded"
            threadId={runId}
            onRunSample={() => void detail.startRun()}
            isRunning={detail.isRunning}
            isReady={detail.isReady}
            onBuyerStateUpdate={detail.onBuyerStateUpdate}
            verifundMode={config.verifundMode}
            onVerifundAction={() => void detail.refreshRun?.()}
          />
          </>
        }
        runError={detail.runError}
        onClearRunError={detail.clearRunError}
        sellerFilter={detail.sellerFilter}
        onSellerFilterChange={detail.setSellerFilter}
        onViewWire={detail.onViewWire}
        events={detail.events}
        traceError={detail.traceError}
        registry={detail.registry}
        registryLoading={detail.registryLoading}
        registryError={detail.registryError}
        onRefreshRegistry={() => void detail.refreshRegistry()}
      />
    </div>
  );
}
