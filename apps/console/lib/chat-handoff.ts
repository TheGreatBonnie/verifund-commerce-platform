/**
 * Builds the prompt used when a buyer workspace page hands a transaction off
 * to the chat-first approval flow. The prompt always keeps the human decision
 * explicit: nothing here authorises a release or rejection on its own.
 */
export function buildChatHandoffPrompt(
  transactionId: string | null | undefined,
  intent: string | null | undefined,
): string | null {
  const id = (transactionId ?? "").trim();
  if (!id) return null;

  switch (intent) {
    case "release":
      return [
        `Review transaction ${id} for release.`,
        "Show me the signed agreement and the release decision, and wait for my explicit approval before any funds are released.",
      ].join(" ");
    case "reject":
      return [
        `Review transaction ${id} for rejection.`,
        "Summarise the relevant evidence and prepare a rejection, but wait for my explicit confirmation before anything is submitted.",
      ].join(" ");
    case "review":
    default:
      return `Review transaction ${id}. Summarise its current state, evidence, and next steps.`;
  }
}
