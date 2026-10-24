import type { Negotiation } from "@/lib/types";
import { money, offerStatus } from "@/lib/format";

type DecisionTrace = {
  type?: string;
  action?: string;
  rationale?: string;
  seller_id?: string | null;
  source?: string;
  fallback_used?: boolean;
};

type NegotiationFeedProps = {
  negotiations: Negotiation[];
  trace?: DecisionTrace[];
};

export function NegotiationFeed({ negotiations, trace = [] }: NegotiationFeedProps) {
  if (negotiations.length === 0) {
    return (
      <section className="mm-panel" aria-labelledby="negotiation-title">
        <header className="mm-panel-head">
          <div>
            <p className="mm-kicker">Buyer ⇄ seller</p>
            <h2 id="negotiation-title">Negotiation ledger</h2>
          </div>
        </header>
        <p className="mm-empty">
          Each seller negotiates in a private A2A task. Rounds appear here as they settle.
        </p>
      </section>
    );
  }

  return (
    <section className="mm-panel mm-feed" aria-labelledby="negotiation-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">Buyer ⇄ seller</p>
          <h2 id="negotiation-title">Negotiation ledger</h2>
        </div>
        <span className="mm-mono-note">private A2A tasks</span>
      </header>

      <div className="mm-feed-list">
        {negotiations.map((negotiation) => {
          const counters = trace.filter(
            (event) =>
              event.action === "counter" &&
              event.seller_id === negotiation.seller_id,
          );
          return (
            <article key={negotiation.seller_id} className="mm-feed-item">
              <header>
                <h3>{negotiation.seller_name}</h3>
                <span className={`mm-status ${negotiation.status === "error" ? "is-error" : ""}`}>
                  {offerStatus(negotiation.status)}
                </span>
              </header>

              <ol className="mm-round-list">
                {negotiation.rounds.map((round, index) => (
                  <li key={`${negotiation.seller_id}-${round.round}`}>
                    <span className="mm-round-tag">R{round.round}</span>
                    <span className="mm-round-price">{money(round.total_cents)}</span>
                    <span className="mm-round-detail">
                      {round.delivery_days}d · {round.warranty_months}mo warranty ·{" "}
                      {round.returns_days}d returns
                    </span>
                    {index < negotiation.rounds.length - 1 ? (
                      <span className="mm-counter-note">
                        Buyer counter → next seller offer
                      </span>
                    ) : null}
                  </li>
                ))}
              </ol>

              {counters.length > 0 ? (
                <p className="mm-rationale">
                  <span>Buyer rationale</span>{" "}
                  {counters.at(-1)?.rationale ??
                    "Deterministic counter target selected within the mandate."}
                </p>
              ) : null}

              {negotiation.error ? (
                <p className="mm-inline-error">{negotiation.error}</p>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}
