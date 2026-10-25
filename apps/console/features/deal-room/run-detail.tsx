"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, RefreshCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Chat } from "@/features/chat/chat";
import { shortId, stageLabel } from "@/lib/format";
import { ApprovalCard } from "./components/approval-card";
import { RunDetailWorkspace } from "./components/run-detail-workspace";
import { StageStepper } from "./components/stage-stepper";
import { useRunDetail } from "./hooks/use-run-detail";

export function RunDetail({ runId }: { runId: string }) {
  const router = useRouter();
  const detail = useRunDetail(runId);
  const approvalElement =
    detail.state.status === "approval_required" ? (
      <ApprovalCard
        award={detail.award}
        mandate={detail.mandate}
        message={detail.state.message}
        onApprove={(note) => detail.sendApproval(true, note)}
        onReject={(note) => detail.sendApproval(false, note)}
      />
    ) : null;

  const handleNewRun = () => {
    if (detail.isRunning) return;
    const nextRunId = crypto.randomUUID();
    detail.resetForRun(nextRunId);
    router.push(`/runs/${nextRunId}`);
  };

  return (
    <div className="mm-run-detail">
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

      <StageStepper stage={detail.stage} />

      <div className="mm-run-detail-grid">
        <aside className="mm-chat-rail" aria-label="Buyer chat">
          <Chat
            onRunSample={() => void detail.startRun()}
            isRunning={detail.isRunning}
            isReady={detail.isReady}
            onBuyerStateUpdate={detail.onBuyerStateUpdate}
          />
          {approvalElement ? (
            <div className="mm-chat-approval">{approvalElement}</div>
          ) : null}
        </aside>

        <RunDetailWorkspace
          state={detail.state}
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
    </div>
  );
}
