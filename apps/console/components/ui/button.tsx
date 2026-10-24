"use client";

import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/cn";

type Variant = "primary" | "outline" | "ghost" | "danger";
type Size = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  leftIcon?: ReactNode;
}

const variantClass: Record<Variant, string> = {
  primary: "mm-button mm-button-primary",
  outline: "mm-button mm-button-outline",
  ghost: "mm-button mm-button-ghost",
  danger: "mm-button mm-button-danger",
};

const sizeClass: Record<Size, string> = {
  sm: "mm-button-sm",
  md: "",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = "primary", size = "md", loading, leftIcon, children, className, disabled, ...rest }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(variantClass[variant], sizeClass[size], className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...rest}
      >
        {loading ? <Loader2 size={13} className="is-spinning" aria-hidden="true" /> : leftIcon}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
