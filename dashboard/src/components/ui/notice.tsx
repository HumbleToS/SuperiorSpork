import type { ReactNode } from "react";

type Tone = "info" | "success" | "warn" | "error";

const TONES: Record<Tone, string> = {
  info: "border-accent/30 bg-accent-soft text-fg",
  success: "border-ok/30 bg-ok-soft text-fg",
  warn: "border-warn/30 bg-warn-soft text-fg",
  error: "border-danger/30 bg-danger-soft text-fg",
};

export function Notice({ tone = "info", title, children, className = "" }: { tone?: Tone; title?: ReactNode; children?: ReactNode; className?: string }) {
  return (
    <div role={tone === "error" ? "alert" : "status"} className={`rounded-[var(--radius-control)] border px-3.5 py-3 text-sm ${TONES[tone]} ${className}`}>
      {title ? <p className="font-medium">{title}</p> : null}
      {children ? <div className={`text-fg-muted ${title ? "mt-1" : ""}`}>{children}</div> : null}
    </div>
  );
}
