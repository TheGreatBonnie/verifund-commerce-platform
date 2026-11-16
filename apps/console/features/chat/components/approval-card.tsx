"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, CircleAlert, LockKeyhole } from "lucide-react";

import type { Award, Mandate, Offer } from "@/lib/types";
import { money, offerExpiry, scoreLabel } from "@/lib/format";

type ApprovalCardProps = {
  award?: Award | null;
  mandate?: Mandate | null;
  message?: string;
  onApprove: (note: string) => Promise<unknown> | void;
  onReject: (note: string) => Promise<unknown> | void;
};

function alternatives(award?: Award | null): Offer[] {
  return award?.alternatives ?? [];
}

export function ApprovalCard({
  award,
  mandate,
  message,
  onApprove,
  onReject,
}: ApprovalCardProps) {
  const noteId = useId();
  const approveRef = useRef<HTMLButtonElement>(null);
  const [note, setNote] = useState("");
  const [pending, setPending] = useState<"approve" | "reject" | null>(null);
  const [expiry, setExpiry] = useState(() => offerExpiry(award?.winner?.valid_until));

  useEffect(() => {
    setExpiry(offerExpiry(award?.winner?.valid_until));
    const timer = window.setInterval(
      () => setExpiry(offerExpiry(award?.winner?.valid_until)),
      30_000,
    );
    return () => window.clearInterval(timer);
  }, [award?.winner?.valid_until]);

  useEffect(() => {
    approveRef.current?.focus();
  }, []);

  if (!award || !award.winner) {
    return (
      <section className="mm-approval mm-approval-empty" aria-live="polite">
        <p className="mm-kicker">Human checkpoint</p>
        <h2>Approval required</h2>
        <p>{message ?? "The buyer agent is preparing an award for your decision."}</p>
      </section>
    );
  }

  const headroom =
    typeof mandate?.max_total_cents === "number"
      ? mandate.max_total_cents - award.winner.total_cents
      : null;

  // The award reaches this card through the orchestrator's tool arguments, so a
  // field can be missing or mangled. Never crash the approval, and never claim
  // checks passed when the proposal did not carry them.
  const mandateChecks = Array.isArray(award.mandate_checks)
    ? award.mandate_checks.filter(
        (check): check is string => typeof check === "string",
      )
    : [];

  const approve = async () => {
    setPending("approve");
    try {
      await onApprove(note.trim());
    } finally {
      setPending(null);
    }
  };

  const reject = async () => {
    setPending("reject");
    try {
      await onReject(note.trim());
    } finally {
      setPending(null);
    }
  };

  return (
    <section className="mm-approval" aria-labelledby="approval-title" aria-live="polite">
      <header className="mm-approval-head">
        <div>
          <p className="mm-kicker">
            <LockKeyhole size={12} aria-hidden="true" /> Human checkpoint
          </p>
          <h2 id="approval-title">Approve this order?</h2>
          <p className="mm-approval-prompt">{message}</p>
        </div>
        <span className="mm-approval-flag">Required</span>
      </header>

      <div className="mm-approval-award">
        <div>
          <span className="mm-kicker">Recommended seller</span>
          <strong>{award.winner.seller_name}</strong>
        </div>
        <div className="mm-approval-total">
          <span className="mm-kicker">Landed total</span>
          <strong>{money(award.winner.total_cents)}</strong>
        </div>
        <div>
          <span className="mm-kicker">Buyer score</span>
          <strong>{scoreLabel(award.score)}</strong>
        </div>
        {headroom !== null ? (
          <div>
            <span className="mm-kicker">Budget headroom</span>
            <strong className={headroom < 0 ? "is-over" : ""}>{money(headroom)}</strong>
          </div>
        ) : null}
      </div>

      <ul className="mm-check-list" aria-label="Mandate checks">
        {mandateChecks.length > 0 ? (
          mandateChecks.map((check) => (
            <li key={check}>
              <Check size={13} aria-hidden="true" /> {check}
            </li>
          ))
        ) : (
          <li>
            Mandate check details were not included in this proposal.
          </li>
        )}
      </ul>

      <p className="mm-expiry-note">
        <CircleAlert size={13} aria-hidden="true" /> {expiry}
      </p>

      {alternatives(award).length > 0 ? (
        <div className="mm-alternatives">
          <table>
            <caption>Runner-up offers</caption>
            <thead>
              <tr>
                <th scope="col">Alternative</th>
                <th scope="col">Total</th>
                <th scope="col">Score</th>
              </tr>
            </thead>
            <tbody>
              {alternatives(award).slice(0, 2).map((offer) => (
                <tr key={offer.offer_id}>
                  <td>{offer.seller_name}</td>
                  <td className="mm-numeric">{money(offer.total_cents)}</td>
                  <td className="mm-numeric">
                    {scoreLabel(award.scores?.[offer.seller_id])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <label className="mm-note-field" htmlFor={noteId}>
        <span>Decision note (optional)</span>
        <textarea
          id={noteId}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          rows={2}
          placeholder="Context retained with the approval receipt"
        />
      </label>

      <div className="mm-approval-actions">
        <button
          ref={approveRef}
          type="button"
          className="mm-button mm-button-signal"
          onClick={approve}
          disabled={pending !== null}
        >
          {pending === "approve" ? "Approving…" : "Approve order"}
        </button>
        <button
          type="button"
          className="mm-button mm-button-outline-danger"
          onClick={reject}
          disabled={pending !== null}
        >
          {pending === "reject" ? "Rejecting…" : "Reject"}
        </button>
      </div>
    </section>
  );
}
