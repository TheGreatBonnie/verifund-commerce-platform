"use client";

import { useState, type ReactNode } from "react";
import {
  CheckCircle2,
  CircleAlert,
  LockKeyhole,
  ShieldCheck,
  Truck,
} from "lucide-react";
import { ApprovalCard } from "./approval-card";
import { A2AWire } from "./a2a-wire";
import { NegotiationFeed } from "./negotiation-feed";
import { NegotiationSession } from "./negotiation-session";
import { OfferMatrix } from "./offer-matrix";
import { OrderPanel } from "./order-panel";
import { RegistryPanel } from "./registry-panel";
import { SellerLane } from "./seller-lane";
import type { BuyerState, RegistrySeller, TraceEvent } from "@/lib/types";

type RunDetailWorkspaceProps = {
  state: BuyerState;
  runId: string;
  showNegotiationTimeline?: boolean;
  conversation: ReactNode;
  isReady: boolean;
  isRunning: boolean;
  onRunSample: () => void;
  runError: string | null;
  onClearRunError: () => void;
  sellerFilter: string;
  onSellerFilterChange: (sellerId: string) => void;
  onViewWire: (sellerId: string) => void;
  onApprove: (note: string) => Promise<void>;
  onReject: (note: string) => Promise<void>;
  events: TraceEvent[];
  traceError: string | null;
  registry: RegistrySeller[];
  registryLoading: boolean;
  registryError: string | null;
  onRefreshRegistry: () => void;
};

function stateError(error: BuyerState["error"]) {
  if (!error) return null;
  if (typeof error === "string") return error;
  return error.message ?? error.code ?? "The run stopped unexpectedly.";
}

function EscrowGuide() {
  return (
    <section className="mm-panel mm-run-escrow-guide" aria-labelledby="run-escrow-title">
      <h2 className="mm-run-rail-title" id="run-escrow-title">How escrow protects the order</h2>
      <ol>
        <li><span><LockKeyhole size={14} aria-hidden="true" /></span><div><strong>Review terms</strong><small>Approve the offer before ordering.</small></div></li>
        <li><span><ShieldCheck size={14} aria-hidden="true" /></span><div><strong>Secure payment</strong><small>Funds remain protected until conditions are met.</small></div></li>
        <li><span><Truck size={14} aria-hidden="true" /></span><div><strong>Confirm delivery</strong><small>Verify the order against the agreement.</small></div></li>
        <li><span><CheckCircle2 size={14} aria-hidden="true" /></span><div><strong>Complete the order</strong><small>Release follows the agreed conditions.</small></div></li>
      </ol>
      <p>This console is a demo and does not create a real escrow transaction.</p>
    </section>
  );
}

export function RunDetailWorkspace({
  state,
  runId,
  showNegotiationTimeline = true,
  conversation,
  isReady,
  isRunning,
  onRunSample,
  runError,
  onClearRunError,
  sellerFilter,
  onSellerFilterChange,
  onViewWire,
  onApprove,
  onReject,
  events,
  traceError,
  registry,
  registryLoading,
  registryError,
  onRefreshRegistry,
}: RunDetailWorkspaceProps) {
  const [showLogs, setShowLogs] = useState(false);
  const award = state.award ?? null;
  const mandate = state.mandate ?? null;
  const negotiations = state.negotiations ?? [];
  const sellers = state.sellers ?? [];
  const stage = state.stage ?? "new";
  const approvalElement = state.status === "approval_required" || stage === "awaiting_approval" ? (
    <ApprovalCard
      award={award}
      mandate={mandate}
      message={state.message}
      onApprove={onApprove}
      onReject={onReject}
    />
  ) : null;

  const logs = (
    <A2AWire
      events={events}
      sellers={negotiations.map((negotiation) => ({
        seller_id: negotiation.seller_id,
        name: negotiation.seller_name,
      }))}
      sellerFilter={sellerFilter}
      onSellerFilterChange={onSellerFilterChange}
      stage={stage}
      error={traceError}
    />
  );

  const handleViewWire = (sellerId: string) => {
    onViewWire(sellerId);
    setShowLogs(true);
    window.setTimeout(() => {
      document.getElementById("a2a-wire")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    }, 0);
  };

  return (
    <div className="mm-negotiation-layout">
      <main className="mm-negotiation-main">
        {runError || stateError(state.error) ? (
          <div className="mm-alert" role="alert">
            <CircleAlert size={16} aria-hidden="true" />
            <span>{runError ?? stateError(state.error)}</span>
            {runError ? <button type="button" onClick={onClearRunError}>Dismiss</button> : null}
          </div>
        ) : null}

        <NegotiationSession
          state={state}
          runId={runId}
          isReady={isReady}
          isRunning={isRunning}
          onRunSample={onRunSample}
          logs={logs}
          showLogs={showLogs}
          onToggleLogs={() => setShowLogs((visible) => !visible)}
        >
          {conversation}
        </NegotiationSession>

        {showNegotiationTimeline ? (
          <NegotiationFeed
            negotiations={negotiations}
            trace={state.trace}
            title="Negotiation timeline"
          />
        ) : null}

        {negotiations.length > 0 ? (
          <OfferMatrix negotiations={negotiations} award={award} />
        ) : null}

        {negotiations.length > 0 ? (
          <section className="mm-lanes" aria-labelledby="seller-lanes-title">
            <header className="mm-section-head">
              <div><p className="mm-kicker">Independent operators</p><h2 id="seller-lanes-title">Seller lanes</h2></div>
              <span className="mm-mono-note">{sellers.length || negotiations.length} Agent Cards · private tasks</span>
            </header>
            <div className="mm-lane-grid">
              {negotiations.map((negotiation) => (
                <SellerLane
                  key={negotiation.seller_id}
                  negotiation={negotiation}
                  mandate={mandate}
                  winner={award?.winner.seller_id === negotiation.seller_id}
                  score={award?.scores?.[negotiation.seller_id]}
                  onViewWire={handleViewWire}
                />
              ))}
            </div>
          </section>
        ) : null}
      </main>

      <aside className="mm-negotiation-sidebar" aria-label="Approval, order, and escrow details">
        {approvalElement ? <div className="mm-deal-approval">{approvalElement}</div> : null}
        <OrderPanel state={state} />
        <EscrowGuide />
        <RegistryPanel
          sellers={registry}
          loading={registryLoading}
          error={registryError}
          onRefresh={onRefreshRegistry}
        />
      </aside>
    </div>
  );
}
