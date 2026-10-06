import Link from "next/link";
import { PublicFrame } from "@/components/shell/public-frame";
import { Notice } from "@/components/ui/notice";
import { getSession } from "@/lib/auth/session";

export const dynamic = "force-dynamic";

const REASONS: Record<string, { tone: "info" | "warn" | "error"; text: string }> = {
  expired: { tone: "info", text: "Your session ended. Sign in again to get back to the dashboard." },
  "signed-out": { tone: "info", text: "You're signed out." },
  denied: { tone: "warn", text: "Discord didn't finish the sign-in. Try again, and accept both permissions when asked." },
  scopes: { tone: "warn", text: "The sign-in didn't include your server list, so there's nothing to manage. Try again and keep both boxes ticked." },
  "no-state": { tone: "warn", text: "That sign-in link was stale. Start again from here." },
  "discord-down": { tone: "error", text: "Discord didn't answer while signing you in. Give it a minute and try again." },
};

export default async function LandingPage({ searchParams }: PageProps<"/">) {
  const params = await searchParams;
  const reason = typeof params.reason === "string" ? REASONS[params.reason] : undefined;
  const next = typeof params.next === "string" && params.next.startsWith("/") ? params.next : "/dashboard";
  const session = await getSession();
  const loginHref = `/api/auth/login?next=${encodeURIComponent(next)}`;

  return (
    <PublicFrame signedIn={session !== null}>
      <div className="mx-auto flex max-w-2xl flex-col gap-8">
        {reason ? <Notice tone={reason.tone}>{reason.text}</Notice> : null}
        <div className="flex flex-col gap-4">
          <p className="eyebrow">Superior Spork · dashboard</p>
          <h1 className="text-4xl font-bold sm:text-[3.25rem] sm:leading-[1.05]">
            Manage <span className="text-yellow">Sprok</span> without typing a single slash command.
          </h1>
          <p className="text-lg text-fg-muted">
            Sign in with Discord, pick a server you manage, and tune the bot from your phone or desk. Nothing here does anything the
            commands can&rsquo;t — it&rsquo;s the same bot, with a screen.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {session ? (
            <Link href="/dashboard" className="inline-flex h-11 items-center rounded-[var(--radius-control)] bg-primary px-5 font-medium text-primary-fg hover:bg-primary-hover">
              Open the dashboard
            </Link>
          ) : (
            <a href={loginHref} className="inline-flex h-11 items-center rounded-[var(--radius-control)] bg-primary px-5 font-medium text-primary-fg hover:bg-primary-hover">
              Sign in with Discord
            </a>
          )}
          <Link href="/commands" className="inline-flex h-11 items-center rounded-[var(--radius-control)] border border-border-strong px-5 font-medium text-fg hover:bg-surface-2">
            Browse the commands
          </Link>
        </div>
        <dl className="divide-y divide-border border-y border-border">
          {[
            ["Commands", "Every command, grouped like /help, searchable, with usage you can copy.", "text-blue"],
            ["Anti-brainrot", "Channels, terms, exemptions, mutes and the leaderboard, without the typing.", "text-orange"],
            ["Nothing hidden", "Signing in asks only who you are and which servers you're in. That's it.", "text-aqua"],
          ].map(([title, body, tone]) => (
            <div key={title} className="grid gap-1 py-4 sm:grid-cols-[10rem_1fr] sm:gap-6">
              <dt className={`display font-semibold ${tone}`}>{title}</dt>
              <dd className="text-sm text-fg-muted">{body}</dd>
            </div>
          ))}
        </dl>
      </div>
    </PublicFrame>
  );
}
