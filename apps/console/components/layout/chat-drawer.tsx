"use client";

import { useRouter } from "next/navigation";
import { CopilotChat, useAgent } from "@copilotkit/react-core/v2";
import { Sparkles } from "lucide-react";
import { ApprovalCard } from "@/features/deal-room/components/approval-card";
import { useRunState } from "@/features/deal-room/hooks/use-run-state";
import { useApproval } from "@/features/deal-room/hooks/use-approval";
import { Button } from "@/components/ui/button";

const SAMPLE_BRIEF =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

export function ChatDrawer() {
  const router = useRouter();
  const { isReady } = useAgent({ agentId: "a2a_chat", updates: [] });
  const { state, runId } = useRunState();
  const { sendApproval } = useApproval(runId);

  const runSample = () => {
    const threadId = crypto.randomUUID();
    try {
      window.sessionStorage.setItem("marketmesh:pendingBrief", SAMPLE_BRIEF);
    } catch {
      // ignore
    }
    router.push(`/runs/${threadId}`);
  };

  const approvalElement =
    state.status === "approval_required" ? (
      <ApprovalCard
        award={state.award ?? null}
        mandate={state.mandate ?? null}
        message={state.message}
        onApprove={(note) => void sendApproval(true, note)}
        onReject={(note) => void sendApproval(false, note)}
      />
    ) : null;

  return (
    <aside className="mm-chat-drawer-shell" aria-label="Buyer chat">
      <div className="mm-chat-drawer-head">
        <span className="mm-kicker">
          <Sparkles size={12} aria-hidden="true" /> Brief desk
        </span>
        <Button variant="outline" size="sm" onClick={runSample} disabled={!isReady}>
          Run sample brief
        </Button>
      </div>
      {approvalElement ? (
        <div className="mm-chat-approval">{approvalElement}</div>
      ) : null}
      <div className="mm-chat-surface">
        <CopilotChat
          agentId="a2a_chat"
          className="mm-copilot-chat"
          labels={{
            welcomeMessageText:
              "Tell me what your team needs. I’ll find independent sellers, negotiate structured offers, and stop for your approval before any order.",
            chatInputPlaceholder:
              "Describe the purchase, budget, deadline, and warranty…",
            chatDisclaimerText:
              "MarketMesh orchestrator · every order requires a human decision.",
          }}
        />
      </div>
    </aside>
  );
}
