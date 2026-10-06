import type { ReactNode } from "react";
import { TONES } from "@/modules/registry";

export function PageHeader({ title, description, action }: { title: string; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <p className={`eyebrow ${TONES.orange.text}`}>Anti-brainrot</p>
        <h1 className="mt-1 text-2xl">{title}</h1>
        {description ? <p className="mt-1 max-w-prose text-sm text-fg-muted">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
