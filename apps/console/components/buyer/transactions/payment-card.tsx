import { CheckCircle2, CreditCard, ExternalLink, ShieldCheck } from "lucide-react";

import { ChatHandoffLink } from "../shared/chat-handoff-link";
import { BuyerStatusPill, type BuyerStatusTone } from "../shared/buyer-status-pill";
import { formatDate, formatMoney, labelize } from "../shared/format";
import { RawDataDisclosure } from "../shared/raw-data-disclosure";

function statusTone(status: string): BuyerStatusTone {
  if (/captur|paid|complet|sett/i.test(status)) return "signal";
  if (/creat_fail|declin|fail|revers/i.test(status)) return "danger";
  if (/pending|creating|await|review|process/i.test(status)) return "amber";
  return "neutral";
}

function headline(status: string): string {
  if (/captur|paid/i.test(status)) return "Payment captured";
  if (/pending|creating|await/i.test(status)) return "Awaiting capture";
  if (/creat_fail|declin|fail/i.test(status)) return "Payment not completed";
  if (/revers/i.test(status)) return "Payment reversed";
  if (/refund/i.test(status)) return "Payment refunded";
  return "Payment record";
}

function recorded(value: unknown): string {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value);
}

export function BuyerPaymentCard({
  payment,
  transactionId,
  agreedAmountCents,
  currency,
  paymentStatus,
}: {
  payment: Record<string, any> | null | undefined;
  transactionId: string;
  agreedAmountCents?: number | null;
  currency?: string | null;
  paymentStatus?: string | null;
}) {
  const record = payment && typeof payment === "object" ? payment : {};
  const status = String(
    record.status ?? record.capture_status ?? paymentStatus ?? "unknown",
  );
  const normalized = status.toLowerCase();
  const captureAmount =
    typeof record.capture_amount_cents === "number"
      ? record.capture_amount_cents
      : null;
  const agreedCurrency = currency ? String(currency) : null;
  const captureCurrency = String(record.capture_currency ?? agreedCurrency ?? "USD");
  const moneyCurrency = agreedCurrency ?? captureCurrency;
  const amountMismatch =
    captureAmount !== null &&
    agreedAmountCents != null &&
    (captureAmount !== agreedAmountCents ||
      (agreedCurrency !== null && captureCurrency !== agreedCurrency));
  const checkoutUrl = String(record.payer_action_url ?? record.checkout_url ?? "");
  const rawError = record.last_error;
  const errorMessage =
    typeof rawError === "string"
      ? rawError
      : rawError?.message || rawError?.code || "Payment was not completed.";

  return (
    <div className="mm-approval mm-buyer-payment" data-testid="buyer-payment-card">
      <div className="mm-verifund-head">
        <div>
          <p className="mm-kicker">Verifund payment</p>
          <h3>
            <span>{headline(status)}</span>
          </h3>
        </div>
        <BuyerStatusPill
          value={status}
          label={labelize(status)}
          tone={statusTone(normalized)}
        />
      </div>

      <div className="mm-verifund-detail">
        <div>
          <p className="mm-kicker">Payment rail</p>
          <strong>PayPal</strong>
        </div>
        <div>
          <p className="mm-kicker">Order attempt</p>
          <strong>{recorded(record.order_attempt)}</strong>
        </div>
      </div>

      <div className="mm-money" data-testid="buyer-payment-money">
        <p className="mm-money-label">Amount on record</p>
        <div className="mm-money-row">
          <span>Agreed amount</span>
          <strong>{formatMoney(agreedAmountCents, moneyCurrency)}</strong>
        </div>
        <div className="mm-money-row">
          <span>Capture amount</span>
          <strong>
            {captureAmount === null
              ? "Not captured"
              : formatMoney(captureAmount, captureCurrency)}
          </strong>
        </div>
        <div className="mm-money-total">
          <span>Recorded total</span>
          <strong>
            {formatMoney(captureAmount ?? agreedAmountCents, captureCurrency)}{" "}
            <em>{captureCurrency}</em>
          </strong>
        </div>
        {amountMismatch ? (
          <p className="mm-amount-warning" data-testid="buyer-payment-mismatch">
            {agreedAmountCents === captureAmount ? (
              <>
                The agreement is denominated in {moneyCurrency}; the capture is in{" "}
                {captureCurrency}.
              </>
            ) : (
              <>
                The agreed amount is{" "}
                {formatMoney(agreedAmountCents, moneyCurrency)}; the captured
                amount is {formatMoney(captureAmount, captureCurrency)}.
              </>
            )}
          </p>
        ) : null}
      </div>

      <div className="mm-acceptance" data-testid="buyer-payment-references">
        <div className="mm-acceptance-row">
          <span>Provider order ID</span>
          <strong>{recorded(record.provider_order_id)}</strong>
        </div>
        <div className="mm-acceptance-row">
          <span>Capture ID</span>
          <strong>{recorded(record.capture_id)}</strong>
        </div>
        <div className="mm-acceptance-row">
          <span>Capture status</span>
          <strong>{recorded(record.capture_status)}</strong>
        </div>
        <div className="mm-acceptance-row">
          <span>Completed</span>
          <strong>{recorded(formatDate(record.completed_at) || null)}</strong>
        </div>
      </div>

      {normalized === "pending" || normalized === "creating" ? (
        <div className="mm-approval-prompt" data-testid="buyer-payment-pending">
          <p>Payment not yet captured.</p>
          {checkoutUrl ? (
            <a href={checkoutUrl} target="_blank" rel="noopener noreferrer">
              Continue checkout <ExternalLink size={11} aria-hidden="true" />
            </a>
          ) : null}
        </div>
      ) : null}

      {/creat_fail|declin|fail/.test(normalized) ? (
        <p role="alert" data-testid="buyer-payment-error">
          {errorMessage}
        </p>
      ) : null}

      {/captur|paid/.test(normalized) ? (
        <p className="mm-trust-head" data-testid="buyer-payment-captured">
          <CheckCircle2 size={12} aria-hidden="true" />
          Payment captured and recorded against this transaction.
        </p>
      ) : null}

      {/revers|refund/.test(normalized) ? (
        <p role="status" data-testid="buyer-payment-reversal">
          Payment was {normalized.replaceAll("_", " ")}. Review in chat before
          taking action.
        </p>
      ) : null}

      <div className="mm-trust" data-testid="buyer-payment-trust">
        <p className="mm-trust-head">
          <ShieldCheck size={14} aria-hidden="true" />
          <span>
            Payment is processed through PayPal and recorded against this
            transaction. Fulfillment follows the agreed verification conditions.
          </span>
        </p>
      </div>

      <div className="mm-buyer-inline-actions mm-buyer-payment-actions">
        <CreditCard size={12} aria-hidden="true" />
        <ChatHandoffLink transactionId={transactionId} intent="review">
          Review payment in chat
        </ChatHandoffLink>
      </div>

      <RawDataDisclosure label="View raw payment" value={payment ?? {}} />
    </div>
  );
}
