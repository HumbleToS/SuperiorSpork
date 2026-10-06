import type { ReactNode } from "react";

type Tone = "neutral" | "ok" | "warn" | "danger" | "info" | "orange" | "purple" | "aqua";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-fg-muted border-border",
  ok: "bg-ok-soft text-ok border-ok/30",
  warn: "bg-warn-soft text-warn border-warn/30",
  danger: "bg-danger-soft text-danger border-danger/30",
  info: "bg-blue-soft text-blue border-blue/30",
  orange: "bg-orange-soft text-orange border-orange/30",
  purple: "bg-purple-soft text-purple border-purple/30",
  aqua: "bg-aqua-soft text-aqua border-aqua/30",
};

export function Badge({ tone = "neutral", children, className = "", title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-[3px] border px-1.5 py-0.5 text-[11px] font-medium leading-4 whitespace-nowrap ${TONES[tone]} ${className}`}
    >
      {children}
    </span>
  );
}
