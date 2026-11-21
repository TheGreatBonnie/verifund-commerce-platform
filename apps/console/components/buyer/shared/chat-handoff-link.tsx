import Link from "next/link";
import { type ReactNode } from "react";

import { cn } from "@/lib/cn";

export type ChatHandoffIntent = "review" | "release" | "reject";

export function ChatHandoffLink({
  transactionId,
  intent,
  children,
  className,
}: {
  transactionId: string;
  intent: ChatHandoffIntent;
  children: ReactNode;
  className?: string;
}) {
  const params = new URLSearchParams({ transaction_id: transactionId, intent });
  const text = typeof children === "string" ? children : String(children);
  const ariaLabel = `${text.replace(/&/g, "").replace(/\s+/g, " ").trim()} for ${transactionId}`;

  return (
    <Link
      className={cn("mm-buyer-chat-link", className)}
      href={`/chat?${params.toString()}`}
      aria-label={ariaLabel}
    >
      {children}
    </Link>
  );
}
