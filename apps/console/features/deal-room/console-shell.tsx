"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  UseAgentUpdate,
  useAgent,
} from "@copilotkit/react-core/v2";
import {
  ArrowDownRight,
  CircleAlert,
  RefreshCcw,
  ShieldCheck,
} from "lucide-react";

import { A2AWire } from "./components/a2a-wire";
import { ApprovalCard } from "./components/approval-card";
import { Chat } from "@/features/chat/chat";
import { NegotiationFeed } from "./components/negotiation-feed";
import { OfferMatrix } from "./components/offer-matrix";
import { OrderPanel } from "./components/order-panel";
import { RegistryPanel } from "./components/registry-panel";
import { SellerLane } from "./components/seller-lane";
import { StageStepper } from "./components/stage-stepper";
import { fetchRegistry, fetchTrace } from "@/lib/api";
import { useRun } from "@/features/runs/use-run";
import { money, scoreLabel, stageLabel } from "@/lib/format";
import type {
  Award,
  BuyerState,
  Mandate,
  Order,
  RegistrySeller,
  TraceEvent,
} from "@/lib/types";

const SAMPLE_BRIEF =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

const TERMINAL = new Set([
  "ordered",
  "rejected",
  "failed",
  "order_failed",
  "no_award",
]);

function useRunTrace(runId: string, active: boolean, terminal: boolean) {
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const afterSeq = useRef(0);

  useEffect(() => {
    afterSeq.current = 0;
    setEvents([]);
    setError(null);
  }, [runId]);

  useEffect(() => {
    if (!active || !runId) return;
    let cancelled = false;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const next = await fetchTrace(runId, afterSeq.current);
        if (cancelled) return;
        if (next.length > 0) {
          afterSeq.current = Math.max(
            afterSeq.current,
            ...next.map((event) => event.seq),
          );
          setEvents((current) => {
            const seen = new Set(current.map((event) => event.id));
            return [
              ...current,
              ...next.filter((event) => !seen.has(event.id)),
            ].sort((a, b) => a.seq - b.seq);
          });
        }
        setError(null);
      } catch {
        if (!cancelled) setError("Trace feed unavailable");
      }
      if (!cancelled && !terminal) {
        timer = window.setTimeout(poll, 1_000);
      }
    };

    void poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [runId, active, terminal]);

  return { events, error };
}

function errorText(error: BuyerState["error"]) {
  if (!error) return null;
  if (typeof error === "string") return error;
  return error.message ?? error.code ?? "The run stopped unexpectedly.";
}

export function ConsoleShell() {
  const routeRunId = useParams()?.runId as string | undefined;
  const { agent, isReady } = useAgent({
    agentId: "a2a_chat",
    updates: [
      UseAgentUpdate.OnMessagesChanged,
      UseAgentUpdate.OnStateChanged,
      UseAgentUpdate.OnRunStatusChanged,
    ],
  });
  const [buyerState, setBuyerState] = useState<BuyerState>({});
  const { run: buyerRun } = useRun(routeRunId ?? "");
  useEffect(() => {
    let latest: BuyerState | null = null;
    for (const message of agent.messages ?? []) {
      const content =
        typeof message.content === "string" ? message.content : "";
      let parsed: unknown = null;
      try {
        parsed = JSON.parse(content);
      } catch {
        continue;
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        continue;
      }
      let candidate = parsed as BuyerState;

      // Check for A2A Task format: { id, status: { message: { parts: [{ text: "{\"status\":\"...\"}" }] } } }
      const taskMessageText =
        (parsed as { status?: { message?: { parts?: Array<{ text?: string }> } } })
          ?.status?.message?.parts?.[0]?.text;
      if (typeof taskMessageText === "string") {
        try {
          const nested = JSON.parse(taskMessageText);
          if (nested && typeof nested === "object" && !Array.isArray(nested)) {
            candidate = nested as BuyerState;
          }
        } catch {
          // keep candidate as parsed
        }
      }

      if (
        candidate &&
        (candidate.task_id ||
          candidate.award ||
          candidate.mandate ||
          candidate.order)
      ) {
        latest = candidate;
      }
    }
    if (latest) setBuyerState(latest);
  }, [agent.messages]);

  // Resume a thread when arriving via /runs/[runId], and auto-start a pending brief.
  useEffect(() => {
    if (routeRunId) {
      agent.threadId = routeRunId;
    }
  }, [agent, routeRunId]);

  const state = useMemo<BuyerState>(() => {
    if (!buyerRun) return buyerState;
    return {
      ...buyerState,
      task_id: buyerRun.run_id ?? buyerState.task_id,
      run_id: buyerRun.run_id ?? buyerState.run_id,
      stage: buyerRun.stage ?? buyerState.stage,
      mandate: (buyerRun.mandate as Mandate | null) ?? buyerState.mandate,
      award: (buyerRun.award as Award | null) ?? buyerState.award,
      order: (buyerRun.order as Order | null) ?? buyerState.order,
      error: buyerRun.error ?? buyerState.error,
    };
  }, [buyerState, buyerRun]);
  const stage = state.stage ?? "new";
  const award = state.award ?? null;
  const mandate = state.mandate ?? null;
  const negotiations = state.negotiations ?? [];
  const sellers = state.sellers ?? [];
  const runId = routeRunId ?? state.task_id ?? state.run_id ?? agent.threadId ?? "";
  const terminal = TERMINAL.has(stage);

  const [isRunning, setIsRunning] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [sellerFilter, setSellerFilter] = useState("all");
  const [registry, setRegistry] = useState<RegistrySeller[]>([]);
  const [registryLoading, setRegistryLoading] = useState(true);
  const [registryError, setRegistryError] = useState<string | null>(null);

  const { events, error: traceError } = useRunTrace(
    runId,
    hasStarted,
    terminal,
  );

  const loadRegistry = useCallback(async () => {
    setRegistryLoading(true);
    try {
      const next = await fetchRegistry();
      setRegistry(next);
      setRegistryError(null);
    } catch {
      setRegistryError("Registry offline — Agent Cards unavailable.");
    } finally {
      setRegistryLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRegistry();
    const timer = window.setInterval(() => void loadRegistry(), 15_000);
    return () => window.clearInterval(timer);
  }, [loadRegistry]);

  const resetRun = useCallback(() => {
    agent.threadId = crypto.randomUUID();
    agent.setMessages([]);
    agent.setState({});
    setBuyerState({});
    setRunError(null);
    setHasStarted(false);
    setSellerFilter("all");
  }, [agent]);

  const startRun = useCallback(
    async (brief: string) => {
      if (isRunning || !isReady) return;
      const threadId = routeRunId ?? crypto.randomUUID();
      agent.threadId = threadId;
      agent.setMessages([]);
      agent.setState({});
      setBuyerState({});
      setRunError(null);
      setHasStarted(true);
      setSellerFilter("all");
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: brief,
      });
      setIsRunning(true);
      try {
        await agent.runAgent();
      } catch (error) {
        setRunError(
          error instanceof Error
            ? error.message
            : "The buyer agent could not start the run.",
        );
      } finally {
        setIsRunning(false);
      }
    },
    [agent, isReady, isRunning, routeRunId],
  );

  useEffect(() => {
    if (!isReady) return;
    const pending = window.sessionStorage.getItem("marketmesh:pendingBrief");
    if (!pending) return;
    window.sessionStorage.removeItem("marketmesh:pendingBrief");
    void startRun(pending);
  }, [isReady, startRun]);

  const sendApproval = useCallback(
    async (approved: boolean, note: string) => {
      const payload = {
        approval: {
          approved,
          approved_by: "Demo Buyer",
          note,
        },
        task_id: buyerState.task_id,
      };
      agent.addMessage({
        id: crypto.randomUUID(),
        role: "user",
        content: `MarketMesh approval response: ${JSON.stringify(payload)}`,
      });
      try {
        await agent.runAgent();
      } catch (error) {
        setRunError(
          error instanceof Error
            ? error.message
            : "The approval could not be submitted.",
        );
      }
    },
    [agent, buyerState.task_id],
  );

  const approvalElement =
    buyerState.status === "approval_required" ? (
      <ApprovalCard
        award={buyerState.award ?? null}
        mandate={buyerState.mandate ?? null}
        message={buyerState.message}
        onApprove={(note) => void sendApproval(true, note)}
        onReject={(note) => void sendApproval(false, note)}
      />
    ) : null;

  const handleNewRun = () => {
    if (isRunning) return;
    resetRun();
  };

  const handleViewWire = (sellerId: string) => {
    setSellerFilter(sellerId);
    document.getElementById("a2a-wire")?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
  };

  const healthyCount = registry.filter((seller) => seller.healthy).length;
  const model =
    process.env.NEXT_PUBLIC_MARKETMESH_LLM_MODE === "live"
      ? "DeepSeek V4.1 Flash"
      : "Scripted demo";

  return (
    <div className="mm-shell">
      <header className="mm-topbar">
        <div className="mm-brand">
          <svg
            viewBox="0 0 32 32"
            className="mm-brand-mark"
            aria-hidden="true"
          >
            <circle cx="7" cy="8" r="3.2" />
            <circle cx="25" cy="7" r="2.4" />
            <circle cx="22" cy="25" r="3.2" />
            <circle cx="7" cy="23" r="2.4" />
            <path d="M10 9.3 21.5 7.9M9.4 10.5l11.4 12M23.5 9.2l-1.2 12.5M9.3 21.7l-1.2-11" />
          </svg>
          <div>
            <span className="mm-wordmark">MarketMesh</span>
            <span className="mm-wordmark-sub">open agent exchange</span>
          </div>
        </div>

        <div className="mm-topbar-meta">
          <span className="mm-registry-status" aria-live="polite">
            <span
              className={`mm-health-dot ${
                registryError ? "is-down" : registry.length ? "is-live" : ""
              }`}
              aria-hidden="true"
            />
            {registryLoading && registry.length === 0
              ? "Reading registry"
              : registryError
                ? "Registry offline"
                : `${healthyCount}/${registry.length || 3} sellers live`}
          </span>
          <span className="mm-model-badge">
            <span>Model</span> {model}
          </span>
          <button
            type="button"
            className="mm-button mm-button-outline"
            onClick={handleNewRun}
            disabled={isRunning}
          >
            <RefreshCcw size={13} aria-hidden="true" /> New run
          </button>
        </div>
      </header>

      <StageStepper stage={stage} />

      <main className="mm-workspace">
        <aside className="mm-chat-rail" aria-label="Buyer chat">
          <Chat
            onRunSample={() => void startRun(SAMPLE_BRIEF)}
            isRunning={isRunning}
            isReady={isReady}
          />
          {approvalElement ? (
            <div className="mm-chat-approval">{approvalElement}</div>
          ) : null}
        </aside>

        <div className="mm-deal-room">
          {runError ? (
            <div className="mm-alert" role="alert">
              <CircleAlert size={16} aria-hidden="true" />
              <span>{runError}</span>
              <button type="button" onClick={() => setRunError(null)}>
                Dismiss
              </button>
            </div>
          ) : null}

          {award ? (
            <section className="mm-award-banner" aria-labelledby="award-title">
              <div className="mm-award-copy">
                <p className="mm-kicker">
                  {stage === "rejected" ? "Award rejected" : "Recommended award"}
                </p>
                <h2 id="award-title">
                  {award.winner.seller_name}
                  <span className="mm-award-rule" aria-hidden="true" />
                  <span className="mm-award-price">
                    {money(award.winner.total_cents)}
                  </span>
                </h2>
                <p>{state.award_summary}</p>
              </div>
              <div className="mm-award-facts">
                <div>
                  <span className="mm-kicker">Buyer score</span>
                  <strong>{scoreLabel(award.score)}</strong>
                </div>
                <div>
                  <span className="mm-kicker">Under first quotes</span>
                  <strong>{money(award.savings_cents)}</strong>
                </div>
                <div>
                  <span className="mm-kicker">Human gate</span>
                  <strong className="mm-signal-text">
                    {stage === "rejected" ? "Rejected" : "Approval required"}
                  </strong>
                </div>
              </div>
              <span className="mm-award-stamp">
                <ShieldCheck size={15} aria-hidden="true" />
                {stage === "ordered" ? "Approved & ordered" : "Award dossier"}
              </span>
            </section>
          ) : (
            <section className="mm-deal-intro" aria-labelledby="deal-intro-title">
              <div>
                <p className="mm-kicker">Sourcing desk · {stageLabel(stage)}</p>
                <h2 id="deal-intro-title">
                  Offers, not ads.
                  <br />
                  <em>Decisions, not autopilot.</em>
                </h2>
                <p className="mm-deal-lede">
                  A buyer agent discovers independent sellers over Agent Cards,
                  negotiates structured offers in private A2A tasks, and brings
                  the award back to a human before an order exists.
                </p>
              </div>
              <div className="mm-mandate-docket">
                <span className="mm-kicker">Open mandate</span>
                {mandate ? (
                  <dl>
                    <div>
                      <dt>Item</dt>
                      <dd>
                        {mandate.quantity} × {mandate.product_hint}
                      </dd>
                    </div>
                    <div>
                      <dt>Ceiling</dt>
                      <dd>{money(mandate.max_total_cents ?? 0)}</dd>
                    </div>
                    <div>
                      <dt>Deadline</dt>
                      <dd>{mandate.deadline_days} days</dd>
                    </div>
                    <div>
                      <dt>Warranty</dt>
                      <dd>{mandate.min_warranty_months} months</dd>
                    </div>
                  </dl>
                ) : (
                  <p className="mm-empty">
                    Run the sample brief to open a mandate. The buyer never
                    reveals its ceiling to sellers.
                  </p>
                )}
                <span className="mm-mono-note">
                  <ArrowDownRight size={12} aria-hidden="true" /> Approval gate
                  enforced outside the A2A task
                </span>
              </div>
            </section>
          )}

          {negotiations.length > 0 ? (
            <section className="mm-lanes" aria-labelledby="seller-lanes-title">
              <header className="mm-section-head">
                <div>
                  <p className="mm-kicker">Three independent operators</p>
                  <h2 id="seller-lanes-title">Seller lanes</h2>
                </div>
                <span className="mm-mono-note">
                  {sellers.length || negotiations.length} Agent Cards · private tasks
                </span>
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
          ) : (
            <section className="mm-lanes-empty" aria-label="Seller discovery">
              <div className="mm-pulse-orbit" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <div>
                <p className="mm-kicker">Discovery pending</p>
                <h2>Three sellers, one shared protocol.</h2>
                <p>
                  Northwind Audio, CircuitForge, and Aurora Supply publish Agent
                  Cards into the MarketMesh registry. Their lanes appear here
                  when the buyer opens private A2A tasks.
                </p>
              </div>
            </section>
          )}

          <A2AWire
            events={events}
            sellers={negotiations.map((negotiation) => ({
              seller_id: negotiation.seller_id,
              name: negotiation.seller_name,
            }))}
            sellerFilter={sellerFilter}
            onSellerFilterChange={setSellerFilter}
            stage={stage}
            error={traceError}
          />

          <div className="mm-lower-grid">
            <div className="mm-lower-main">
              <OfferMatrix negotiations={negotiations} award={award} />
              <NegotiationFeed
                negotiations={negotiations}
                trace={state.trace}
              />
            </div>
            <aside className="mm-lower-side" aria-label="Decision and order">
              {approvalElement ? (
                <div className="mm-deal-approval">{approvalElement}</div>
              ) : null}
              <OrderPanel state={state} />
              <RegistryPanel
                sellers={registry}
                loading={registryLoading}
                error={registryError}
                onRefresh={() => void loadRegistry()}
              />
            </aside>
          </div>

          <footer className="mm-footer">
            <span>MarketMesh · A2A 1.x · JSON-RPC + SSE</span>
            <span>
              No payment processing or real fulfillment is performed here.
            </span>
          </footer>
        </div>
      </main>
    </div>
  );
}
