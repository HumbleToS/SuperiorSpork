/**
 * A coloured rail: the dashboard's version of the accent bar on the bot's Discord cards. The colour is an
 * SVG presentation attribute because the CSP forbids inline styles; size and radius come from the class.
 */
export function Rail({ color, className = "" }: { color: string | null | undefined; className?: string }) {
  return (
    <svg viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true" className={`rail shrink-0 ${className}`}>
      <rect width="1" height="1" fill={color ?? "var(--border-strong)"} />
    </svg>
  );
}
