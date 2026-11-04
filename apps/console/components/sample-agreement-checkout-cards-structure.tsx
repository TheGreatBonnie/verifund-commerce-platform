"use client";

import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowLeft,
  BadgeCheck,
  Check,
  CheckCheck,
  CheckCircle2,
  ChevronDown,
  Clock3,
  FileCheck2,
  Info,
  LockKeyhole,
  MoreHorizontal,
  Paperclip,
  Send,
  Settings2,
  ShieldCheck,
  Truck,
  WalletCards,
  X,
} from "lucide-react";

type Stage = "agreement" | "checkout" | "paid";
type Message = {
  id: number;
  from: "buyer" | "agent";
  text: string;
  time: string;
};

const initialMessages: Message[] = [
  {
    id: 1,
    from: "buyer",
    text: "Find me a reliable refurbished laptop under $1,500.",
    time: "10:24 AM",
  },
  {
    id: 2,
    from: "agent",
    text: "I found an offer from NovaTech that matches your requirements. The seller has accepted the final terms. Please review the agreement below.",
    time: "10:25 AM",
  },
];

function StatusPill({
  children,
  tone = "green",
}: {
  children: React.ReactNode;
  tone?: "green" | "amber" | "blue" | "slate";
}) {
  const styles = {
    green: "bg-emerald-50 text-emerald-700 border-emerald-100",
    amber: "bg-amber-50 text-amber-700 border-amber-100",
    blue: "bg-blue-50 text-blue-700 border-blue-100",
    slate: "bg-slate-100 text-slate-600 border-slate-200",
  };
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-semibold ${styles[tone]}`}>
      {children}
    </span>
  );
}

function ProductSummary() {
  return (
    <div className="flex gap-4">
      <div className="flex h-28 w-32 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-gradient-to-br from-slate-100 to-blue-100">
        <div className="relative h-[76px] w-[105px] rounded-lg border-[5px] border-slate-700 bg-slate-800 p-1 shadow-lg">
          <div className="h-full rounded-sm bg-gradient-to-br from-sky-400 via-blue-600 to-indigo-900" />
          <div className="absolute -bottom-3 left-[-8px] h-2 w-[115px] rounded-b-xl bg-slate-400" />
        </div>
      </div>
      <div className="min-w-0 flex-1">
        <h3 className="font-bold leading-snug text-slate-900">
          Refurbished AI-Development Laptop
        </h3>
        <p className="mt-1 flex items-center gap-1.5 text-sm text-slate-600">
          NovaTech <BadgeCheck size={15} className="fill-blue-600 text-white" />
        </p>
        <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-600">
          <span className="rounded-md bg-slate-100 px-2 py-1">32 GB RAM</span>
          <span className="rounded-md bg-slate-100 px-2 py-1">1 TB SSD</span>
          <span className="rounded-md bg-slate-100 px-2 py-1">Refurbished</span>
        </div>
        <p className="mt-2 text-sm text-slate-600">
          Quantity: <strong className="text-slate-900">1</strong>
        </p>
      </div>
    </div>
  );
}

function MoneyRows({ checkout = false }: { checkout?: boolean }) {
  return (
    <div className="space-y-2.5 text-sm">
      <div className="flex justify-between gap-4">
        <span className="text-slate-500">Product price</span>
        <span className="font-medium">$1,370.00</span>
      </div>
      <div className="flex justify-between gap-4">
        <span className="text-slate-500">Tracked shipping</span>
        <span className="font-medium">$30.00</span>
      </div>
      <div className="flex justify-between gap-4">
        <span className="text-slate-500">Taxes</span>
        <span className="font-medium">
          {checkout ? "Included in demo total" : "Included in demo total"}
        </span>
      </div>
      <div className="border-t border-slate-200 pt-3">
        <div className="flex items-end justify-between gap-3">
          <span className="font-bold text-slate-900">Total payable</span>
          <span className="text-2xl font-extrabold tracking-tight text-blue-800">
            $1,400.00 <span className="text-xs font-semibold">USD</span>
          </span>
        </div>
      </div>
    </div>
  );
}

function AgreementCard({
  onApprove,
  approved,
}: {
  onApprove: () => void;
  approved: boolean;
}) {
  return (
    <section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-[0_8px_28px_rgba(15,23,42,0.06)]">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-blue-50 p-2.5 text-blue-700">
            <FileCheck2 size={23} />
          </div>
          <div>
            <p className="text-sm font-extrabold tracking-wide text-slate-900">
              VERIFUND AGREEMENT
            </p>
            <p className="mt-1 text-xs text-slate-500">
              VF-2048 <span className="mx-1.5">·</span> Version v1{" "}
              <span className="mx-1.5">·</span> Expires in 30 min
            </p>
          </div>
        </div>
        <StatusPill tone={approved ? "green" : "amber"}>
          {approved ? <CheckCircle2 size={14} /> : <Clock3 size={14} />}
          {approved ? "Approved" : "Awaiting your approval"}
        </StatusPill>
      </div>

      <div className="space-y-4 p-5">
        <ProductSummary />
        <div className="rounded-xl bg-slate-50 p-4">
          <p className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500">
            Agreed commercial terms
          </p>
          <MoneyRows />
        </div>

        <div>
          <h4 className="mb-2 flex items-center gap-2 text-sm font-bold text-slate-900">
            <ShieldCheck size={17} className="text-blue-600" /> Seller
            obligations
          </h4>
          <div className="grid gap-2 sm:grid-cols-2">
            {[
              "Match the agreed product specifications",
              "Provide tracked shipping",
              "Maintain a 90-day warranty",
              "Submit shipping evidence",
            ].map((item) => (
              <p
                key={item}
                className="flex items-start gap-2 text-xs text-slate-600">
                <CheckCircle2
                  size={15}
                  className="mt-0.5 shrink-0 text-emerald-600"
                />
                {item}
              </p>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-4">
          <h4 className="mb-3 flex items-center gap-2 text-sm font-bold text-slate-900">
            <Clock3 size={17} className="text-blue-700" /> Inspection and
            verification
          </h4>
          <div className="grid gap-3 sm:grid-cols-[150px_1fr]">
            <div>
              <p className="text-xs text-slate-500">Inspection window</p>
              <p className="mt-1 text-sm font-bold text-slate-900">
                48 hours after delivery
              </p>
            </div>
            <div>
              <p className="text-xs text-slate-500">Verification checklist</p>
              <ul className="mt-1 space-y-1 text-xs text-slate-700">
                <li>• Product matches specifications</li>
                <li>• Tracking confirms delivery</li>
                <li>• Product condition matches agreement</li>
              </ul>
            </div>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-xl border border-slate-200 p-3">
            <h4 className="mb-2 text-sm font-bold">Returns and disputes</h4>
            <p className="text-xs leading-5 text-slate-600">
              90-day warranty. Defects must be reported during the agreed
              inspection process. Disputes follow Verifund review rules.
            </p>
            <button className="mt-2 inline-flex items-center gap-1 text-xs font-semibold text-blue-700">
              View full terms <ChevronDown size={13} />
            </button>
          </div>
          <div className="rounded-xl border border-slate-200 p-3">
            <h4 className="mb-2 text-sm font-bold">Agreement acceptance</h4>
            <div className="space-y-2 text-xs">
              <div className="flex justify-between gap-2">
                <span className="text-slate-500">Seller Agent</span>
                <span className="font-semibold text-emerald-700">
                  Accepted v1
                </span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-slate-500">Buyer</span>
                <span
                  className={`font-semibold ${approved ? "text-emerald-700" : "text-amber-700"}`}>
                  {approved ? "Approved v1" : "Awaiting approval"}
                </span>
              </div>
              <div className="flex justify-between gap-2">
                <span className="text-slate-500">Verifund</span>
                <span className="font-semibold text-emerald-700">
                  Validated
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2.5 text-[11px] text-slate-500">
          <span>
            <LockKeyhole size={12} className="mr-1 inline" /> Agreement digest:{" "}
            <strong className="text-slate-700">7f3a9e8d...9f1e</strong>
          </span>
          <span>Created Oct 24, 2026 · v1</span>
        </div>

        <button
          onClick={onApprove}
          disabled={approved}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-4 py-3.5 text-sm font-bold text-white shadow-sm transition hover:bg-blue-700 disabled:cursor-default disabled:bg-emerald-600">
          {approved ? (
            <>
              <CheckCircle2 size={18} /> Agreement approved
            </>
          ) : (
            <>
              <ShieldCheck size={18} /> Review and approve agreement
            </>
          )}
        </button>
        <p className="text-center text-[11px] text-slate-500">
          Approval applies only to agreement VF-2048, version v1.
        </p>
      </div>
    </section>
  );
}

function CheckoutCard({ onPay, paid }: { onPay: () => void; paid: boolean }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-blue-100 bg-white shadow-[0_8px_28px_rgba(15,23,42,0.06)]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="rounded-xl bg-blue-50 p-2.5 text-blue-700">
            <WalletCards size={23} />
          </div>
          <div>
            <p className="text-base font-extrabold text-slate-900">
              Secure checkout
            </p>
            <p className="text-xs text-slate-500">
              Payment for agreement VF-2048 · v1
            </p>
          </div>
        </div>
        <StatusPill tone={paid ? "green" : "blue"}>
          <LockKeyhole size={13} />
          {paid ? "Payment confirmed (demo)" : "Secure payment"}
        </StatusPill>
      </div>
      <div className="space-y-4 p-5">
        <ProductSummary />
        <div className="rounded-xl border border-slate-200 p-4">
          <p className="mb-3 text-xs font-bold uppercase tracking-wider text-slate-500">
            Order summary
          </p>
          <MoneyRows checkout />
        </div>
        <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
          <div className="flex gap-3">
            <ShieldCheck className="mt-0.5 shrink-0 text-blue-700" size={23} />
            <div>
              <p className="text-sm font-bold text-blue-900">
                Your transaction is managed by Verifund
              </p>
              <p className="mt-1 text-xs leading-5 text-slate-600">
                Payment is processed through PayPal and recorded against your
                approved agreement. Fulfillment is evaluated against the agreed
                verification conditions.
              </p>
            </div>
          </div>
          <div className="mt-3 grid grid-cols-3 gap-2 border-t border-blue-200 pt-3 text-center text-[11px] font-medium text-slate-600">
            <span className="flex flex-col items-center gap-1">
              <Truck size={17} className="text-blue-700" />
              Tracked delivery
            </span>
            <span className="flex flex-col items-center gap-1">
              <Clock3 size={17} className="text-blue-700" />
              48-hour inspection
            </span>
            <span className="flex flex-col items-center gap-1">
              <ShieldCheck size={17} className="text-blue-700" />
              Verification rules
            </span>
          </div>
        </div>
        <div className="rounded-xl border border-slate-200 p-4">
          <div className="mb-3 flex items-center justify-between">
            <p className="text-sm font-bold text-slate-900">Payment method</p>
            <span className="text-xs font-semibold text-slate-500">
              Powered by <span className="text-blue-700">PayPal</span>
            </span>
          </div>
          <button
            onClick={onPay}
            disabled={paid}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-[#ffc439] px-4 py-3.5 text-lg font-extrabold text-[#003087] transition hover:brightness-95 disabled:opacity-70">
            {paid ? (
              <>
                <CheckCircle2 size={20} /> Demo payment completed
              </>
            ) : (
              <>
                <span className="text-2xl italic">P</span> PayPal{" "}
                <span className="ml-1 text-sm font-semibold">Continue</span>
              </>
            )}
          </button>
          <p className="mt-2 text-center text-xs text-slate-500">
            Demo interaction only — no real payment is taken.
          </p>
        </div>
        <p className="flex items-start gap-2 text-[11px] leading-5 text-slate-500">
          <Info size={14} className="mt-0.5 shrink-0" /> By continuing, you
          authorize payment for the transaction described in the approved
          Verifund agreement.
        </p>
      </div>
    </section>
  );
}

export default function ChatDemo() {
  const [stage, setStage] = useState<Stage>("agreement");
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [draft, setDraft] = useState("");
  const [showDetails, setShowDetails] = useState(false);

  const agentReply = useMemo(
    () =>
      stage === "agreement"
        ? "Please review the final agreement. Once you approve this exact version, I can prepare secure checkout."
        : stage === "checkout"
          ? "Your agreement is approved. Complete the payment below. I will confirm it after the payment provider reports the result."
          : "The demo payment has been marked as completed in this interface. In a real integration, Verifund would confirm the capture server-side.",
    [stage],
  );

  function approveAgreement() {
    setStage("checkout");
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        from: "buyer",
        text: "I approve agreement VF-2048, version v1.",
        time: "10:26 AM",
      },
      {
        id: Date.now() + 1,
        from: "agent",
        text: "Thank you. The agreement is approved. Here is your secure PayPal checkout card.",
        time: "10:26 AM",
      },
    ]);
  }
  function completeDemoPayment() {
    setStage("paid");
    setMessages((prev) => [
      ...prev,
      {
        id: Date.now(),
        from: "buyer",
        text: "Please proceed with the payment.",
        time: "10:28 AM",
      },
      {
        id: Date.now() + 1,
        from: "agent",
        text: "Demo payment completed. A real application must verify the PayPal capture on the server before confirming payment.",
        time: "10:29 AM",
      },
    ]);
  }
  function sendMessage() {
    const value = draft.trim();
    if (!value) return;
    setMessages((prev) => [
      ...prev,
      { id: Date.now(), from: "buyer", text: value, time: "Now" },
    ]);
    setDraft("");
  }

  return (
    <main className="min-h-screen px-3 py-5 sm:px-6 sm:py-8">
      <div className="mx-auto flex min-h-[calc(100vh-4rem)] max-w-5xl flex-col overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-[0_20px_60px_rgba(15,23,42,0.08)]">
        <header className="flex items-center justify-between border-b border-slate-200 px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-600 text-white shadow-sm">
              <ShieldCheck size={26} />
            </div>
            <div>
              <p className="text-lg font-extrabold tracking-tight text-slate-900">
                Verifund
              </p>
              <p className="text-[11px] font-medium text-slate-500">
                AGENTIC COMMERCE
              </p>
            </div>
            <div className="mx-2 hidden h-9 w-px bg-slate-200 sm:block" />
            <div className="hidden sm:block">
              <p className="text-sm font-bold text-slate-900">Shopping Agent</p>
              <p className="flex items-center gap-1.5 text-xs text-emerald-600">
                <span className="h-2 w-2 rounded-full bg-emerald-500" /> Online
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setShowDetails((v) => !v)}
              aria-label="Conversation information"
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100">
              <Info size={19} />
            </button>
            <button
              aria-label="Settings"
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100">
              <Settings2 size={19} />
            </button>
            <button
              aria-label="More options"
              className="rounded-lg p-2 text-slate-500 hover:bg-slate-100">
              <MoreHorizontal size={19} />
            </button>
          </div>
        </header>

        {showDetails && (
          <div className="border-b border-blue-100 bg-blue-50 px-5 py-3 text-xs text-blue-900">
            Demo transaction VF-2048 · Mock product, seller, agreement, and
            payment data. No external services are connected.
          </div>
        )}

        <div className="flex-1 space-y-5 bg-[#fbfcff] px-3 py-5 sm:px-6 sm:py-7">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.from === "buyer" ? "justify-end" : "justify-start"}`}>
              {message.from === "agent" && (
                <div className="mr-2 mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white">
                  <ShieldCheck size={19} />
                </div>
              )}
              <div
                className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm leading-6 sm:max-w-[75%] ${message.from === "buyer" ? "rounded-tr-md bg-blue-600 text-white" : "rounded-tl-md border border-slate-100 bg-white text-slate-700 shadow-sm"}`}>
                {message.text}
                <div
                  className={`mt-1 flex items-center justify-end gap-1 text-[10px] ${message.from === "buyer" ? "text-blue-100" : "text-slate-400"}`}>
                  {message.time}
                  {message.from === "buyer" && <CheckCheck size={13} />}
                </div>
              </div>
              {message.from === "buyer" && (
                <div className="ml-2 mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-100 text-xs font-bold text-amber-800">
                  B
                </div>
              )}
            </div>
          ))}

          <div className="ml-0 sm:ml-10">
            {stage === "agreement" && (
              <AgreementCard onApprove={approveAgreement} approved={false} />
            )}
            {(stage === "checkout" || stage === "paid") && (
              <CheckoutCard
                onPay={completeDemoPayment}
                paid={stage === "paid"}
              />
            )}
          </div>

          {stage === "paid" && (
            <div className="ml-10 flex items-start gap-2 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-800">
              <CheckCircle2 size={16} className="mt-0.5 shrink-0" />
              <p>
                <strong>Demo state: payment completed.</strong> This is only a
                UI simulation; it does not represent a PayPal transaction or a
                verified funds-received event.
              </p>
            </div>
          )}
        </div>

        <div className="border-t border-slate-200 bg-white p-3 sm:p-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              sendMessage();
            }}
            className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Attach file"
              className="hidden rounded-xl border border-slate-200 p-3 text-slate-500 hover:bg-slate-50 sm:block">
              <Paperclip size={19} />
            </button>
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Message your shopping agent..."
              className="h-12 min-w-0 flex-1 rounded-xl border border-slate-200 bg-slate-50 px-4 text-sm outline-none transition placeholder:text-slate-400 focus:border-blue-400 focus:bg-white focus:ring-4 focus:ring-blue-50"
            />
            <button
              type="submit"
              aria-label="Send message"
              className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white transition hover:bg-blue-700">
              <Send size={19} />
            </button>
          </form>
          <p className="mt-2 hidden text-center text-[10px] text-slate-400 sm:block">
            Verifund assistant · Review transaction details before authorizing
            payment
          </p>
        </div>
      </div>
    </main>
  );
}
