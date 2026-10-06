import Link from "next/link";
import type { ReactNode } from "react";
import { Logo, SporkMark } from "./logo";

const LINKS = [
  { href: "/commands", label: "Commands", always: true },
  { href: "/privacy", label: "Privacy", always: false },
  { href: "/terms", label: "Terms", always: false },
];

const CTA = "ml-1 inline-flex h-9 items-center rounded-[var(--radius-control)] bg-primary px-3 font-medium text-primary-fg hover:bg-primary-hover";

export function PublicFrame({ children, signedIn }: { children: ReactNode; signedIn: boolean }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-4 px-4">
          <Logo />
          <nav aria-label="Site" className="flex items-center gap-1 text-sm">
            {LINKS.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className={`rounded-[var(--radius-control)] px-2.5 py-1.5 text-fg-muted hover:bg-surface-2 hover:text-fg ${link.always ? "" : "hidden sm:inline-block"}`}
              >
                {link.label}
              </Link>
            ))}
            {signedIn ? (
              <Link href="/dashboard" className={CTA}>
                Dashboard
              </Link>
            ) : (
              // a plain anchor on purpose: a <Link> would prefetch the route, which redirects to Discord
              <a href="/api/auth/login" className={CTA}>
                Sign in
              </a>
            )}
          </nav>
        </div>
      </header>
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:py-12">
        {children}
      </main>
      <footer className="border-t border-border">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-6 text-sm text-fg-faint">
          <span className="inline-flex items-center gap-2">
            <SporkMark className="size-4 text-orange" />
            sprok is the dashboard for Superior Spork, a Discord bot by umbleh
          </span>
          <span className="flex gap-4">
            <Link href="/privacy" className="hover:text-fg">
              Privacy
            </Link>
            <Link href="/terms" className="hover:text-fg">
              Terms
            </Link>
          </span>
        </div>
      </footer>
    </div>
  );
}
