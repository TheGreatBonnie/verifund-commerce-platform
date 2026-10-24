import { type ReactNode } from "react";
import { cn } from "@/lib/cn";

type Tone = "neutral" | "signal" | "error" | "amber";

export interface StatusProps {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}

const toneClass: Record<Tone, string> = {
  neutral: "",
  signal: "is-signal",
  error: "is-error",
  amber: "is-amber",
};

export function Status({ tone = "neutral", children, className }: StatusProps) {
  return <span className={cn("mm-status", toneClass[tone], className)}>{children}</span>;
}
