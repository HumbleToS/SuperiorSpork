import type { ReactNode } from "react";
import type { Session } from "@/lib/auth/session";
import { Logo } from "./logo";

export function DashboardHeader({ session, switcher }: { session: Session; switcher?: ReactNode }) {
  return (
    <header className="sticky top-0 z-30 border-b border-border bg-canvas">
      <div className="mx-auto flex h-14 w-full max-w-7xl items-center gap-3 px-4">
        <Logo href="/dashboard" />
        <div className="min-w-0 flex-1">{switcher}</div>
        <div className="flex shrink-0 items-center gap-2">
          <span className="hidden items-center gap-2 text-sm text-fg-muted sm:flex">
            {session.avatar ? (
              // eslint-disable-next-line @next/next/no-img-element -- Discord CDN avatar
              <img src={session.avatar} alt="" className="size-6 rounded-full" />
            ) : null}
            <span className="max-w-32 truncate">{session.displayName}</span>
          </span>
          <form action="/api/auth/logout" method="post">
            <button type="submit" className="h-8 rounded-[var(--radius-control)] px-2.5 text-sm text-fg-muted hover:bg-surface-2 hover:text-fg">
              Sign out
            </button>
          </form>
        </div>
      </div>
    </header>
  );
}
