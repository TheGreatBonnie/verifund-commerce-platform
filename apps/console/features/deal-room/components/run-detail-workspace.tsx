import { ArrowDownRight, CircleAlert, ShieldCheck } from "lucide-react";
import { A2AWire } from "./a2a-wire";
import { NegotiationFeed } from "./negotiation-feed";
import { OfferMatrix } from "./offer-matrix";
import { OrderPanel } from "./order-panel";
import { RegistryPanel } from "./registry-panel";
import { SellerLane } from "./seller-lane";
import type { BuyerState, RegistrySeller, TraceEvent } from "@/lib/types";
import { money, scoreLabel, stageLabel } from "@/lib/format";

type RunDetailWorkspaceProps = {
  state: BuyerState;
  runError: string | null;
  onClearRunError: () => void;
  sellerFilter: string;
  onSellerFilterChange: (sellerId: string) => void;
  onViewWire: (sellerId: string) => void;
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

export function RunDetailWorkspace({
  state,
  runError,
  onClearRunError,
  sellerFilter,
  onSellerFilterChange,
  onViewWire,
  events,
  traceError,
  registry,
  registryLoading,
  registryError,
  onRefreshRegistry,
}: RunDetailWorkspaceProps) {
  const award = state.award ?? null;
  const mandate = state.mandate ?? null;
  const negotiations = state.negotiations ?? [];
  const sellers = state.sellers ?? [];
  const stage = state.stage ?? "new";
  return (
    <div className="mm-deal-room mm-run-deal-room">
      {runError || stateError(state.error) ? (
        <div className="mm-alert" role="alert">
          <CircleAlert size={16} aria-hidden="true" />
          <span>{runError ?? stateError(state.error)}</span>
          {runError ? (
            <button type="button" onClick={onClearRunError}>Dismiss</button>
          ) : null}
        </div>
      ) : null}

      {award ? (
        <section className="mm-award-banner" aria-labelledby="run-award-title">
          <div className="mm-award-copy">
            <p className="mm-kicker">
              {stage === "rejected" ? "Award rejected" : "Recommended award"}
            </p>
            <h2 id="run-award-title">
              {award.winner.seller_name}
              <span className="mm-award-rule" aria-hidden="true" />
              <span className="mm-award-price">{money(award.winner.total_cents)}</span>
            </h2>
            <p>{state.award_summary}</p>
          </div>
          <div className="mm-award-facts">
            <div><span className="mm-kicker">Buyer score</span><strong>{scoreLabel(award.score)}</strong></div>
            <div><span className="mm-kicker">Under first quotes</span><strong>{money(award.savings_cents)}</strong></div>
            <div>
              <span className="mm-kicker">Human gate</span>
              <strong className="mm-signal-text">{stage === "rejected" ? "Rejected" : "Approval required"}</strong>
            </div>
          </div>
          <span className="mm-award-stamp">
            <ShieldCheck size={15} aria-hidden="true" />
            {stage === "ordered" ? "Approved & ordered" : "Award dossier"}
          </span>
        </section>
      ) : (
        <section className="mm-deal-intro" aria-labelledby="run-intro-title">
          <div>
            <p className="mm-kicker">Sourcing desk · {stageLabel(stage)}</p>
            <h2 id="run-intro-title">Offers, not ads.<br /><em>Decisions, not autopilot.</em></h2>
            <p className="mm-deal-lede">
              A buyer agent discovers independent sellers over Agent Cards,
              negotiates structured offers in private A2A tasks, and brings the
              award back to a human before an order exists.
            </p>
          </div>
          <div className="mm-mandate-docket">
            <span className="mm-kicker">Open mandate</span>
            {mandate ? (
              <dl>
                <div><dt>Item</dt><dd>{mandate.quantity} × {mandate.product_hint}</dd></div>
                <div><dt>Ceiling</dt><dd>{money(mandate.max_total_cents ?? 0)}</dd></div>
                <div><dt>Deadline</dt><dd>{mandate.deadline_days} days</dd></div>
                <div><dt>Warranty</dt><dd>{mandate.min_warranty_months} months</dd></div>
              </dl>
            ) : (
              <p className="mm-empty">Run a brief to open a mandate. The buyer never reveals its ceiling to sellers.</p>
            )}
            <span className="mm-mono-note">
              <ArrowDownRight size={12} aria-hidden="true" /> Approval gate enforced outside the A2A task
            </span>
          </div>
        </section>
      )}

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
                onViewWire={onViewWire}
              />
            ))}
          </div>
        </section>
      ) : (
        <section className="mm-lanes-empty" aria-label="Seller discovery">
          <div className="mm-pulse-orbit" aria-hidden="true"><span /><span /><span /></div>
          <div>
            <p className="mm-kicker">Discovery pending</p>
            <h2>Three sellers, one shared protocol.</h2>
            <p>Northwind Audio, CircuitForge, and Aurora Supply publish Agent Cards into the MarketMesh registry. Their lanes appear when the buyer opens private A2A tasks.</p>
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
        onSellerFilterChange={onSellerFilterChange}
        stage={stage}
        error={traceError}
      />

      <div className="mm-lower-grid">
        <div className="mm-lower-main">
          <OfferMatrix negotiations={negotiations} award={award} />
          <NegotiationFeed negotiations={negotiations} trace={state.trace} />
        </div>
        <aside className="mm-lower-side" aria-label="Decision and order">
          <OrderPanel state={state} />
          <RegistryPanel
            sellers={registry}
            loading={registryLoading}
            error={registryError}
            onRefresh={onRefreshRegistry}
          />
        </aside>
      </div>

      <footer className="mm-footer">
        <span>MarketMesh · A2A 1.x · JSON-RPC + SSE</span>
        <span>No payment processing or real fulfillment is performed here.</span>
      </footer>
    </div>
  );
}
