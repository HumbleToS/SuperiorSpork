import type { ButtonHTMLAttributes, ReactNode } from "react";
import { Spinner } from "./spinner";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-primary-fg hover:bg-primary-hover disabled:hover:bg-primary",
  secondary: "bg-surface text-fg border border-border-strong hover:bg-surface-2",
  ghost: "text-fg-muted hover:text-fg hover:bg-surface-2",
  danger: "bg-surface text-danger border border-danger/40 hover:bg-danger-soft",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-sm gap-2",
};

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  pending?: boolean;
  icon?: ReactNode;
};

export function Button({ variant = "secondary", size = "md", pending = false, icon, className = "", children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      {...rest}
      disabled={disabled || pending}
      aria-busy={pending || undefined}
      className={`inline-flex shrink-0 items-center justify-center rounded-[var(--radius-control)] font-medium transition-[background-color,border-color] duration-150 disabled:cursor-not-allowed disabled:opacity-60 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
    >
      {pending ? <Spinner className="size-4" /> : icon}
      {children}
    </button>
  );
}
