"use client";

import { useEffect, useState } from "react";
import { useUser } from "@clerk/nextjs";
import { approverDisplayName } from "@/lib/clerk-display-name";
import {
  CopilotChat,
  useAgent,
  useHumanInTheLoop,
  useFrontendTool,
  useRenderTool,
} from "@copilotkit/react-core/v2";
import { z } from "zod";
import { ArrowUpRight, Sparkles } from "lucide-react";
import { ApprovalCard } from "@/features/deal-room/components/approval-card";
import { AgreementApprovalCard } from "@/features/agreements/AgreementApprovalCard";
import {
  AgreementReviewCard,
  AgreementReviewLinkFromResult,
  CheckoutCard,
  EvidenceSummaryCard,
  FundingApprovalCard,
  ReceiptCard,
  ReleaseApprovalCard,
  VerifundStatusCard,
  AgreementApprovalHitlCard,
  agreementApprovalArgsSchema,
  agreementReviewLink,
  bilateralReviewStatus,
  fundingApprovalArgsSchema,
  fundingDecision,
  parseVerifundToolResult,
  PayPalCheckoutCard,
  paypalCheckoutArgsSchema,
  releaseApprovalArgsSchema,
  releaseDecision,
  verifundToolsEnabled,
} from "./verifund-tools";
import { fetchRegistry } from "@/lib/api";
import { ProductSearchCards } from "./product-cards";
import { MessageToA2A } from "@/features/deal-room/components/a2a/MessageToA2A";
import { MessageFromA2A } from "@/features/deal-room/components/a2a/MessageFromA2A";

type BuyerState = {
  status?: string;
  task_id?: string;
  stage?: string;
  award?: any;
  mandate?: any;
  order?: any;
  error?: any;
  message?: string;
};

type ChatProps = {
  onRunSample: () => void;
  isRunning: boolean;
  isReady: boolean;
  threadId?: string;
  onBuyerStateUpdate?: (state: BuyerState) => void;
  variant?: "rail" | "embedded";
  verifundMode?: string;
  onVerifundAction?: () => void;
};

const SAMPLE_PROMPT =
  "Buy 12 Nimbus NC-700 ANC headsets for our team. Budget $3,400, delivery within 14 days, 24-month warranty, 30-day returns. Prefer a sustainability-certified seller.";

function sellerName(
  sellerId?: string,
  cardUrl?: string,
  resolvedName?: string | null,
) {
  // Prefer an explicit display name (tool arg or registry lookup) over the
  // legacy slug/port maps; UUID seller ids otherwise leak into the UI.
  if (resolvedName) return resolvedName;
  const names: Record<string, string> = {
    "northwind-audio": "Northwind Audio",
    circuitforge: "CircuitForge",
    "aurora-supply": "Aurora Supply",
    "summit-tech": "Summit Tech Supply",
  };
  if (sellerId && names[sellerId]) return names[sellerId];
  let port = "";
  try {
    port = cardUrl ? new URL(cardUrl).port : "";
  } catch {
    return sellerId ?? "Seller agent";
  }
  const idByPort: Record<string, string> = {
    "9201": "northwind-audio",
    "9202": "circuitforge",
    "9203": "aurora-supply",
    "9204": "summit-tech",
  };
  return names[idByPort[port]] ?? sellerId ?? "Seller agent";
}

function requestSummary(request?: Record<string, unknown>) {
  const payload = (request?.payload ?? request) as
    | Record<string, unknown>
    | undefined;
  if (!payload) return "Seller request";
  if (payload.product_hint) {
    return `RFQ · ${payload.quantity ?? ""} ${payload.product_hint}`.trim();
  }
  if (payload.target_unit_price_cents) {
    return `Counteroffer · $${(Number(payload.target_unit_price_cents) / 100).toFixed(2)} per unit`;
  }
  if (payload.accepted_total_cents) {
    return `Offer acceptance · $${(Number(payload.accepted_total_cents) / 100).toFixed(2)}`;
  }
  if (payload.offer_id)
    return `Order request · offer ${String(payload.offer_id)}`;
  return "Structured seller request";
}

function responseSummary(rawResult: string) {
  try {
    const content = rawResult.startsWith("A2A Agent Response: ")
      ? rawResult.slice("A2A Agent Response: ".length)
      : rawResult;
    const result = JSON.parse(content) as {
      error?: string;
      seller_result?: {
        offers?: Array<{ total_cents?: number }>;
        orders?: unknown[];
        order?: unknown;
      };
    };
    if (result.error) return { label: result.error, failed: true };
    const sellerResult = result.seller_result;
    if (!sellerResult) return { label: "Response received", failed: false };
    if (sellerResult.order || sellerResult.orders?.length) {
      return { label: "Order response received", failed: false };
    }
    const offers = sellerResult.offers ?? [];
    if (offers.length === 1 && offers[0].total_cents != null) {
      return {
        label: `Offer received · $${(offers[0].total_cents / 100).toFixed(2)}`,
        failed: false,
      };
    }
    if (offers.length > 1) {
      return { label: `${offers.length} offers received`, failed: false };
    }
    return { label: "Response received", failed: false };
  } catch {
    return { label: "Response received", failed: false };
  }
}

function VerifundA2AExchange({
  status,
  task,
  response,
  children,
}: {
  status?: string;
  task: string;
  response?: string;
  children: any;
}) {
  return (
    <div data-testid="verifund-exchange" className="mm-verifund-exchange">
      <MessageToA2A
        status={status === "executing" ? "executing" : "complete"}
        args={{ agentName: "Verifund", task }}
      />
      {response ? (
        <MessageFromA2A
          status="complete"
          args={{ agentName: "Verifund" }}
          response={response}
        />
      ) : null}
      {children}
    </div>
  );
}

export function Chat({
  onRunSample,
  isRunning,
  isReady,
  threadId,
  onBuyerStateUpdate,
  variant = "rail",
  verifundMode,
  onVerifundAction,
}: ChatProps) {
  const { agent } = useAgent({ agentId: "marketmesh_orchestrator" });
  const { user } = useUser();
  const approver = approverDisplayName(user);
  const [registryNames, setRegistryNames] = useState<Map<string, string>>(
    () => new Map(),
  );

  useEffect(() => {
    let cancelled = false;
    fetchRegistry()
      .then((sellers) => {
        if (!cancelled) {
          setRegistryNames(
            new Map(sellers.map((seller) => [seller.seller_id, seller.name])),
          );
        }
      })
      .catch(() => {
        // The slug/port fallback in sellerName still applies without the registry.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useHumanInTheLoop(
    {
      agentId: "marketmesh_orchestrator",
      name: "request_award_approval",
      description:
        "Show the buyer's structured award to the user and wait for an explicit approve or reject decision. Use only after the Buyer returns status approval_required. Pass the award and task ID from that Buyer response without changing them.",
      parameters: z.object({
        task_id: z.string(),
        message: z.string(),
        award: z.record(z.unknown()),
        mandate: z.record(z.unknown()).optional(),
      }),
      render: ({ args, status, respond, result }) => {
        if (status === "inProgress") {
          return (
            <div className="mm-chat-approval-pending" role="status">
              Preparing the award for your review…
            </div>
          );
        }

        if (status === "executing" && respond) {
          return (
            <div className="mm-chat-approval">
              <ApprovalCard
                award={args.award as any}
                mandate={args.mandate as any}
                message={args.message}
                onApprove={(note) =>
                  respond({
                    approved: true,
                    approved_by: approver,
                    note,
                    task_id: args.task_id,
                  })
                }
                onReject={(note) =>
                  respond({
                    approved: false,
                    approved_by: approver,
                    note,
                    task_id: args.task_id,
                  })
                }
              />
            </div>
          );
        }

        if (status === "complete") {
          let decision: { approved?: boolean } | null = null;
          try {
            decision = JSON.parse(result) as { approved?: boolean };
          } catch {
            // Keep the completed approval item visible if the result is malformed.
          }
          return (
            <p className="mm-chat-approval-result" role="status">
              {decision?.approved === true
                ? "Award approved. The Buyer is completing the order."
                : decision?.approved === false
                  ? "Award rejected. No order will be placed."
                  : "Your decision was recorded. The Buyer is continuing."}
            </p>
          );
        }

        return null;
      },
    },
    [],
  );

  const verifundEnabled = verifundToolsEnabled(verifundMode);

  useHumanInTheLoop(
    {
      agentId: "marketmesh_orchestrator",
      name: "request_verifund_funding_approval",
      description:
        "Show the canonical agreement and the Buyer/Seller review status, then wait for an explicit human funding decision.",
      available: verifundEnabled,
      parameters: fundingApprovalArgsSchema,
      render: ({ args, status, respond }) => {
        if (status === "executing" && respond) {
          return (
            <div className="mm-chat-approval">
              <FundingApprovalCard
                args={args as any}
                onApprove={(note) => {
                  respond(
                    fundingDecision(args as any, { approved: true, note }),
                  );
                  onVerifundAction?.();
                }}
                onReject={(note) => {
                  respond(
                    fundingDecision(args as any, { approved: false, note }),
                  );
                  onVerifundAction?.();
                }}
              />
            </div>
          );
        }
        return null;
      },
    },
    [verifundEnabled, onVerifundAction],
  );

  useHumanInTheLoop(
    {
      agentId: "marketmesh_orchestrator",
      name: "request_verifund_paypal_checkout",
      description:
        "Show the embedded PayPal checkout and wait for the buyer to pay, cancel, or fall back to the redirect checkout.",
      available: verifundEnabled && verifundMode === "sandbox",
      parameters: paypalCheckoutArgsSchema,
      render: ({ args, status, respond, result }) => {
        if (status === "executing" && respond) {
          return (
            <div className="mm-chat-approval">
              <PayPalCheckoutCard
                args={args as any}
                respond={respond}
                onVerifundAction={onVerifundAction}
              />
            </div>
          );
        }
        if (status === "complete") {
          const state =
            (result as any)?.state ?? (result as any)?.data?.state ?? "";
          return (
            <p
              className="mm-chat-approval-result"
              data-testid="verifund-checkout-settled"
            >
              Payment result recorded.
              {state ? ` Settlement: ${state}.` : ""}
            </p>
          );
        }
        return null;
      },
    },
    [verifundEnabled, verifundMode, onVerifundAction],
  );

  useHumanInTheLoop(
    {
      agentId: "marketmesh_orchestrator",
      name: "request_verifund_agreement_approval",
      description:
        "Show the canonical agreement and wait for an explicit human buyer approval decision.",
      available: verifundEnabled,
      parameters: agreementApprovalArgsSchema,
      render: ({ args, status, respond }) => {
        if (status === "inProgress") {
          return (
            <div className="mm-chat-approval-pending" role="status">
              Preparing the agreement for your review…
            </div>
          );
        }
        if (status === "executing" && respond) {
          return (
            <div className="mm-chat-approval">
              <AgreementApprovalHitlCard
                args={args as any}
                respond={respond}
                onVerifundAction={onVerifundAction}
              />
            </div>
          );
        }
        if (status === "complete") {
          return (
            <p className="mm-chat-approval-result" role="status">
              Agreement decision recorded. Continuing…
            </p>
          );
        }
        return null;
      },
    },
    [verifundEnabled, onVerifundAction],
  );

  useHumanInTheLoop(
    {
      agentId: "marketmesh_orchestrator",
      name: "request_verifund_release_approval",
      description:
        "Show the evidence/verification summary and wait for an explicit human release decision.",
      available: verifundEnabled,
      parameters: releaseApprovalArgsSchema,
      render: ({ args, status, respond }) => {
        if (status === "executing" && respond) {
          return (
            <div className="mm-chat-approval">
              <ReleaseApprovalCard
                args={args as any}
                onDecision={(decision) => {
                  respond(decision);
                  onVerifundAction?.();
                }}
              />
            </div>
          );
        }
        return null;
      },
    },
    [verifundEnabled, onVerifundAction],
  );

  useRenderTool({
    name: "search_marketplace_products",
    parameters: z.object({
      query: z.string().optional(),
      category: z.string().optional(),
      max_unit_price_cents: z.number().optional(),
      in_stock_only: z.boolean().optional(),
      use_case: z.string().optional(),
      preferences: z.array(z.string()).optional(),
      limit: z.number().optional(),
    }),
    render: ({ status, result }) => (
      <ProductSearchCards status={status} result={result} />
    ),
  });

  useRenderTool({
    name: "verifund_create_agreement",
    parameters: z.object({
      run_id: z.string().optional(),
      award: z.record(z.unknown()).optional(),
    }),
    render: ({ parameters, status, result }) => {
      const parsed = parseVerifundToolResult(result);
      if (status !== "complete" || !parsed) return null;
      const task = `Create agreement for run ${String(
        parameters?.run_id ?? parsed?.data?.run_id ?? "",
      )}`.trim();
      const response = parsed.status
        ? `${parsed.status}${parsed.checkpoint ? ` · ${parsed.checkpoint}` : ""}`
        : undefined;

      let children: any = null;
      if (
        parsed.checkpoint === "buyer_approval_required" &&
        parsed.agreement_review
      ) {
        children = (
          <div className="mm-chat-approval">
            <AgreementReviewLinkFromResult result={parsed} />
          </div>
        );
      } else {
        const agreement = parsed.data?.agreement;
        if (agreement) {
          children = (
            <div className="mm-chat-approval">
              <AgreementReviewCard
                agreement={agreement as any}
                buyerReview={(parsed.data?.buyer_review as any) ?? null}
                sellerDecision={(parsed.data?.seller_decision as any) ?? null}
              />
            </div>
          );
        }
      }
      if (!children) return null;
      return (
        <VerifundA2AExchange status={status} task={task} response={response}>
          {children}
        </VerifundA2AExchange>
      );
    },
  });

  useFrontendTool(
    {
      agentId: "marketmesh_orchestrator",
      name: "show_agreement_review",
      description:
        "Display the canonical agreement review card and its review link. This tool is non-blocking; it never records a decision and never requests funding approval.",
      available: verifundEnabled,
      parameters: z.object({
        agreement: z.record(z.unknown()).optional(),
        review_url: z.string().optional(),
        version: z.number().optional(),
        digest: z.string().optional(),
        seller_decision: z.record(z.unknown()).optional(),
        precheck: z.record(z.unknown()).optional(),
        handle: z
          .object({
            task_id: z.string(),
            context_id: z.string(),
            run_id: z.string(),
          })
          .optional(),
      }),
      handler: async (args) => ({
        status: "displayed",
        review_url: args.review_url ?? null,
        next_action: "wait_for_buyer_approval",
      }),
      render: ({ args, status, result }) => {
        if (status === "inProgress") {
          return (
            <div className="mm-chat-approval">
              <p>Preparing agreement review…</p>
            </div>
          );
        }
        const parsed = {
          ...(parseVerifundToolResult(result) ?? {}),
          ...(args as Record<string, unknown>),
        };
        const link = agreementReviewLink(parsed);
        if (!link) return null;
        return (
          <div className="mm-chat-approval">
            <AgreementApprovalCard {...link} />
          </div>
        );
      },
    },
    [verifundEnabled],
  );

  useRenderTool({
    name: "verifund_status",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ parameters, status, result }) => {
      const parsed = parseVerifundToolResult(result);
      if (status !== "complete" || !parsed) return null;
      const task = `Check Verifund status for run ${String(
        parameters?.run_id ?? parsed?.data?.run_id ?? "",
      )}`.trim();
      const response = parsed.status
        ? `${parsed.status}${parsed.checkpoint ? ` · ${parsed.checkpoint}` : ""}`
        : undefined;
      return (
        <VerifundA2AExchange status={status} task={task} response={response}>
          <VerifundStatusCard
            status={parsed.status}
            checkpoint={parsed.checkpoint}
            state={parsed.state ?? parsed.data?.projection?.state}
            message={parsed.message}
          />
        </VerifundA2AExchange>
      );
    },
  });

  useRenderTool({
    name: "verifund_evidence_review",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ parameters, status, result }) => {
      const parsed = parseVerifundToolResult(result);
      if (status !== "complete" || !parsed) return null;
      const task = `Review evidence for run ${String(
        parameters?.run_id ?? parsed?.data?.run_id ?? "",
      )}`.trim();
      const response = parsed.status
        ? `${parsed.status}${parsed.checkpoint ? ` · ${parsed.checkpoint}` : ""}`
        : undefined;
      return (
        <VerifundA2AExchange status={status} task={task} response={response}>
          <EvidenceSummaryCard
            projection={
              (parsed.data?.projection ?? {
                evidence: parsed.evidence,
                verification: parsed.verification,
              }) as any
            }
          />
        </VerifundA2AExchange>
      );
    },
  });

  useRenderTool({
    name: "verifund_fund",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ parameters, status, result }) => {
      const parsed = parseVerifundToolResult(result);
      if (status !== "complete" || !parsed) return null;
      const url = parsed.checkout_url ?? parsed.data?.checkout_url;
      const task = `Fund transaction for run ${String(
        parameters?.run_id ?? parsed?.data?.run_id ?? "",
      )}`.trim();
      const response = parsed.status
        ? `${parsed.status}${parsed.checkpoint ? ` · ${parsed.checkpoint}` : ""}`
        : undefined;
      const children =
        typeof url === "string" ? (
          <CheckoutCard
            url={url}
            expiresAt={parsed.expires_at ?? parsed.data?.expires_at ?? null}
          />
        ) : (
          <VerifundStatusCard
            status={parsed.status}
            checkpoint={parsed.checkpoint}
            state={parsed.state}
            message={parsed.message}
          />
        );
      return (
        <VerifundA2AExchange status={status} task={task} response={response}>
          {children}
        </VerifundA2AExchange>
      );
    },
  });

  useRenderTool({
    name: "verifund_receipt",
    parameters: z.object({ run_id: z.string().optional() }),
    render: ({ parameters, status, result }) => {
      const parsed = parseVerifundToolResult(result);
      const receipt = parsed?.data?.receipt;
      if (status !== "complete" || !receipt) return null;
      const task = `Get receipt for run ${String(
        parameters?.run_id ?? parsed?.data?.run_id ?? "",
      )}`.trim();
      const response = "Receipt available";
      return (
        <VerifundA2AExchange status={status} task={task} response={response}>
          <ReceiptCard receipt={receipt as any} />
        </VerifundA2AExchange>
      );
    },
  });

  useRenderTool({
    name: "mediate_seller_call",
    parameters: z.object({
      seller_id: z.string().optional(),
      seller_name: z.string().optional(),
      seller_card_url: z.string(),
      seller_request: z.record(z.unknown()).optional(),
    }),
    render: ({ parameters, status, result }) => {
      if (status === "inProgress") return null;
      const agentName = sellerName(
        parameters.seller_id,
        parameters.seller_card_url,
        parameters.seller_name ??
          registryNames.get(parameters.seller_id ?? ""),
      );
      const outgoing = {
        agentName,
        task: requestSummary(parameters.seller_request),
      };
      const summary =
        status === "complete" ? responseSummary(result) : undefined;
      return (
        <div data-testid="mediated-seller-exchange">
          <MessageToA2A
            status={status === "executing" ? "executing" : "complete"}
            args={outgoing}
          />
          {summary ? (
            <MessageFromA2A
              status="complete"
              args={{ agentName }}
              response={summary.label}
              failed={summary.failed}
            />
          ) : null}
        </div>
      );
    },
  });

  // Extract structured JSON from A2A agent responses and pass to parent
  useEffect(() => {
    const extractDataFromMessages = () => {
      for (const message of agent.messages) {
        const msg = message as any;

        if (msg.role === "tool" && typeof msg.content !== "undefined") {
          try {
            const result = msg.content;
            let parsed;

            if (typeof result === "string") {
              let cleanResult = result;
              // Handle A2A response format from middleware
              if (result.startsWith("A2A Agent Response: ")) {
                cleanResult = result.slice("A2A Agent Response: ".length);
              }
              try {
                parsed = JSON.parse(cleanResult);
              } catch {
                continue;
              }
            } else if (typeof result === "object") {
              parsed = result;
            } else {
              continue;
            }

            // Mediation resumes the Buyer internally, so its latest state is
            // nested in the mediation tool result instead of a separate Buyer call.
            const buyerState = parsed.buyer_response ?? parsed;
            if (
              buyerState.status ||
              buyerState.award ||
              buyerState.mandate ||
              buyerState.task_id ||
              buyerState.order
            ) {
              if (onBuyerStateUpdate) {
                onBuyerStateUpdate(buyerState as BuyerState);
              }
            }
          } catch (e) {
            console.error("Failed to extract data from message:", e);
          }
        }
      }
    };

    extractDataFromMessages();
  }, [agent.messages, onBuyerStateUpdate]);

  useFrontendTool({
    name: "send_message_to_a2a_agent",
    description: "Sends a message to an A2A agent",
    available: true,
    parameters: z.object({
      agentName: z
        .string()
        .describe("The name of the A2A agent to send the message to"),
      task: z.string().describe("The message to send to the A2A agent"),
    }),
    render: (actionRenderProps: {
      args?: { agentName?: string; task?: string };
      status?: string;
    }) => (
      <>
        <MessageToA2A {...actionRenderProps} />
        <MessageFromA2A {...actionRenderProps} />
      </>
    ),
  });

  return (
    <div
      className={`mm-chat ${variant === "embedded" ? "mm-chat-embedded" : ""}`}>
      {variant === "rail" ? (
        <>
          <header className="mm-rail-head">
            <div>
              <p className="mm-kicker">Buyer agent · AG-UI</p>
              <h1>Brief desk</h1>
            </div>
            <span className="mm-agent-badge">
              <span className="mm-live-dot is-live" aria-hidden="true" /> Live
            </span>
          </header>

          <div className="mm-sample-brief">
            <div className="mm-sample-top">
              <span className="mm-kicker">
                <Sparkles size={12} aria-hidden="true" /> Demo mandate
              </span>
              <span className="mm-mono-note">consumer electronics</span>
            </div>
            <p>{SAMPLE_PROMPT}</p>
            <button
              type="button"
              className="mm-button mm-button-ink"
              onClick={onRunSample}
              disabled={isRunning || !isReady}>
              {isRunning ? "Agents working…" : "Run sample brief"}
              <ArrowUpRight size={14} aria-hidden="true" />
            </button>
          </div>
        </>
      ) : null}

      <div className="mm-chat-surface">
        <CopilotChat
          agentId="marketmesh_orchestrator"
          threadId={threadId}
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
    </div>
  );
}
