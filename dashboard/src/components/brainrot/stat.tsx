import type { ReactNode } from "react";
import { formatNumber } from "@/lib/format";

export function Stat({ label, value, hint }: { label: string; value: number | string; hint?: ReactNode }) {
  return (
    <div className="card flex flex-col gap-1 p-4">
      <span className="eyebrow">{label}</span>
      <span className="mono text-2xl font-medium text-purple">{typeof value === "number" ? formatNumber(value) : value}</span>
      {hint ? <span className="text-xs text-fg-muted">{hint}</span> : null}
    </div>
  );
}
