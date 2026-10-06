import type { HTMLAttributes, ReactNode } from "react";

export function Card({ className = "", children, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={`card p-4 sm:p-5 ${className}`}>
      {children}
    </div>
  );
}

export function CardHeader({ title, description, action, as: Heading = "h2" }: { title: ReactNode; description?: ReactNode; action?: ReactNode; as?: "h1" | "h2" | "h3" }) {
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <Heading className="text-base font-semibold text-fg">{title}</Heading>
        {description ? <p className="mt-1 text-sm text-fg-muted">{description}</p> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}
