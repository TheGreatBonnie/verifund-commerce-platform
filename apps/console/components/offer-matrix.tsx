import type { Award, Negotiation } from "@/lib/types";
import { money, scoreLabel, unitPrice } from "@/lib/format";

type OfferMatrixProps = {
  negotiations: Negotiation[];
  award?: Award | null;
};

export function OfferMatrix({ negotiations, award }: OfferMatrixProps) {
  const rows = [...negotiations].sort((a, b) => {
    if (a.seller_id === award?.winner.seller_id) return -1;
    if (b.seller_id === award?.winner.seller_id) return 1;
    return (a.seller_name ?? "").localeCompare(b.seller_name ?? "");
  });

  return (
    <section className="mm-panel mm-matrix" aria-labelledby="offer-matrix-title">
      <header className="mm-panel-head">
        <div>
          <p className="mm-kicker">Structured offers</p>
          <h2 id="offer-matrix-title">Offer matrix</h2>
        </div>
        <span className="mm-mono-note">USD · landed total</span>
      </header>

      {rows.length === 0 ? (
        <p className="mm-empty">Offers will land here after the RFQ reaches the sellers.</p>
      ) : (
        <div className="mm-table-scroll">
          <table>
            <caption className="sr-only">
              Seller offers with total price, unit price, delivery, warranty,
              returns, sustainability, and deterministic score.
            </caption>
            <thead>
              <tr>
                <th scope="col">Seller</th>
                <th scope="col">Total</th>
                <th scope="col">Unit</th>
                <th scope="col">Lead time</th>
                <th scope="col">Warranty</th>
                <th scope="col">Returns</th>
                <th scope="col">Green</th>
                <th scope="col">Score</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((negotiation) => {
                const offer = negotiation.final_offer ?? negotiation.rounds.at(-1);
                if (!offer) return null;
                const winner = award?.winner.seller_id === negotiation.seller_id;
                return (
                  <tr key={negotiation.seller_id} data-winner={winner}>
                    <th scope="row">
                      <span className="mm-matrix-seller">
                        {winner ? (
                          <span className="mm-winner-dot" aria-label="Winner" />
                        ) : null}
                        {negotiation.seller_name}
                      </span>
                    </th>
                    <td className="mm-numeric">{money(offer.total_cents)}</td>
                    <td className="mm-numeric">{money(unitPrice(offer))}</td>
                    <td>{offer.delivery_days} days</td>
                    <td>{offer.warranty_months} mo</td>
                    <td>{offer.returns_days} days</td>
                    <td>{offer.terms.sustainability_certified ? "Yes" : "No"}</td>
                    <td className="mm-numeric">
                      {scoreLabel(award?.scores?.[negotiation.seller_id])}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
