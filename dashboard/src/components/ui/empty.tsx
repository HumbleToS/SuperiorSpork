import type { ReactNode } from "react";

export function EmptyState({ title, children, action }: { title: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-[var(--radius-card)] border border-dashed border-border px-6 py-10 text-center">
      <p className="font-medium text-fg">{title}</p>
      {children ? <p className="max-w-prose text-sm text-fg-muted">{children}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}
