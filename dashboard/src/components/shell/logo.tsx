import Link from "next/link";

/** The spork: bowl, three tines, a handle. Fills with the current text colour. */
export function SporkMark({ className = "size-5" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" className={`shrink-0 ${className}`}>
      <path d="M7.4 3.6 8.4 2.4 9.3 6.4h.9L11 2.2h2l.8 4.2h.9l.9-4 1 1.2c1.4 1.8 1.6 5.2.3 7.4-.8 1.4-2.1 2.1-3.4 2.3v7.2a1.5 1.5 0 0 1-3 0v-7.2c-1.3-.2-2.6-.9-3.4-2.3-1.3-2.2-1.1-5.6.3-7.4Z" />
    </svg>
  );
}

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="display inline-flex items-center gap-1.5 text-[19px] font-bold tracking-tight text-fg">
      <SporkMark className="size-5 text-orange" />
      sprok
    </Link>
  );
}
