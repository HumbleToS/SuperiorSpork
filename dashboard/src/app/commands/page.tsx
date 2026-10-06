import type { Metadata } from "next";
import { PublicFrame } from "@/components/shell/public-frame";
import { CommandsReference } from "@/components/commands/reference";
import { CommandsUnavailable } from "@/components/commands/unavailable";
import { Notice } from "@/components/ui/notice";
import { getSession } from "@/lib/auth/session";
import { getCommandsCached } from "@/lib/bot/commands-cache";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Commands",
  description: "Every Sprok command with usage, examples, and the permissions each one needs — generated from the bot itself.",
  alternates: { canonical: "/commands" },
};

export default async function CommandsPage() {
  const [session, cached] = await Promise.all([getSession(), getCommandsCached()]);
  return (
    <PublicFrame signedIn={session !== null}>
      <div className="flex flex-col gap-6">
        <div className="flex flex-col gap-2">
          <p className="eyebrow text-blue">Superior Spork</p>
          <h1 className="text-3xl sm:text-4xl">Commands</h1>
          <p className="max-w-prose text-fg-muted">
            Everything the bot can do, grouped the way <code className="text-fg">/help</code> groups it. Badges show what a command needs;
            the bot only shows you commands you can actually run.
          </p>
        </div>
        {cached?.stale ? <Notice tone="warn">The bot isn&rsquo;t answering right now, so this is the last copy it gave us.</Notice> : null}
        {cached ? <CommandsReference index={cached.index} /> : <CommandsUnavailable />}
      </div>
    </PublicFrame>
  );
}
