export function HeatBar({ heat, max = 5, className = "" }: { heat: number; max?: number; className?: string }) {
  const level = Math.max(0, Math.min(heat, max));
  const tone = level >= max ? "bg-danger" : level >= max - 1 ? "bg-warn" : "bg-ok";
  return (
    <span className={`inline-flex items-center gap-2 ${className}`} role="img" aria-label={`Heat ${level} of ${max}`}>
      <span className="flex gap-0.5" aria-hidden="true">
        {Array.from({ length: max }, (_, index) => (
          <span key={index} className={`h-2 w-3.5 rounded-[2px] ${index < level ? tone : "bg-surface-3"}`} />
        ))}
      </span>
      <span className="mono text-xs text-fg-muted">
        {level}/{max}
      </span>
    </span>
  );
}
