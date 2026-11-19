/**
 * Frontend tools registered with `useHumanInTheLoop` for the orchestrator.
 *
 * A HITL tool call is the boundary of an agent run: the agent emits the tool
 * call and waits for the user's answer, which arrives as a new run. Keeping
 * the original run open across that wait holds the Intelligence thread lock
 * and makes the follow-up run fail with `agent_thread_locked` (409).
 *
 * `MarketMeshA2AMiddlewareAgent` uses this set to end a run as soon as one of
 * these tool calls is emitted. Keep it in sync with the `name` fields of the
 * `useHumanInTheLoop` registrations in `features/chat/chat.tsx`.
 */
export const FRONTEND_HITL_TOOL_NAMES: ReadonlySet<string> = new Set([
  "request_award_approval",
  "request_verifund_funding_approval",
  "request_verifund_paypal_checkout",
  "request_verifund_agreement_approval",
  "request_verifund_release_approval",
  "request_sourcing_mandate",
]);
