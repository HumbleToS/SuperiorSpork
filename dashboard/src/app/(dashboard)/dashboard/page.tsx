import Link from "next/link";
import { DashboardHeader } from "@/components/shell/header";
import { BotOffline } from "@/components/shell/bot-offline";
import { Notice } from "@/components/ui/notice";
import { EmptyState } from "@/components/ui/empty";
import { Rail } from "@/components/ui/rail";
import { requireSession } from "@/lib/auth/require";
import { guildLists, type AddableGuild } from "@/lib/auth/guilds";
import { BotUnreachableError, getApp } from "@/lib/bot/client";
import type { GuildSummary } from "@/lib/bot/schemas";

export const metadata = { title: "Your servers" };

function inviteFor(inviteUrl: string, guildId: string): string {
  const url = new URL(inviteUrl);
  url.searchParams.set("guild_id", guildId);
  url.searchParams.set("disable_guild_select", "true");
  return url.toString();
}

function GuildIcon({ guild }: { guild: { name: string; icon: string | null } }) {
  return guild.icon ? (
    // eslint-disable-next-line @next/next/no-img-element -- Discord CDN icon
    <img src={guild.icon} alt="" className="size-10 shrink-0 rounded-[var(--radius-control)] border border-border object-cover" />
  ) : (
    <span aria-hidden="true" className="display flex size-10 shrink-0 items-center justify-center rounded-[var(--radius-control)] border border-border bg-surface-3 text-sm text-fg-muted">
      {guild.name.slice(0, 1)}
    </span>
  );
}

export default async function GuildPickerPage() {
  const session = await requireSession("/dashboard");
  let lists: Awaited<ReturnType<typeof guildLists>> | null = null;
  let invite: string | null = null;
  let offline: string | null = null;
  try {
    const [guilds, app] = await Promise.all([guildLists(session), getApp()]);
    lists = guilds;
    invite = app.invite_url;
  } catch (error) {
    if (!(error instanceof BotUnreachableError)) throw error;
    offline = error.message;
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <DashboardHeader session={session} />
      <main id="main" className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-8">
        <div>
          <h1 className="text-2xl">Your servers</h1>
          <p className="mt-1 text-sm text-fg-muted">Servers where you have Manage Server. The bot decides which ones you can open.</p>
        </div>

        {offline ? <BotOffline detail={offline} /> : null}

        {lists ? (
          <>
            <section aria-labelledby="manageable" className="flex flex-col gap-3">
              <h2 id="manageable" className="eyebrow">
                With the bot
              </h2>
              {lists.manageable.length === 0 ? (
                <EmptyState title="The bot isn't in a server you manage yet">Add it to one below and it shows up here.</EmptyState>
              ) : (
                <ul className="grid gap-2 sm:grid-cols-2">
                  {lists.manageable.map((guild: GuildSummary) => (
                    <li key={guild.id}>
                      <Link href={`/g/${guild.id}/commands`} className="card relative flex items-center gap-3 overflow-hidden p-3 pl-4 transition-colors hover:border-border-strong">
                        <Rail color={guild.accent} className="absolute inset-y-0 left-0 w-1.5" />
                        <GuildIcon guild={guild} />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate font-medium">{guild.name}</span>
                          <span className="block text-xs text-fg-faint">{guild.owner ? "Owner" : "Manage Server"}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section aria-labelledby="addable" className="flex flex-col gap-3">
              <h2 id="addable" className="eyebrow">
                Without the bot
              </h2>
              {lists.oauthFailed ? (
                <Notice tone="warn">Discord didn&rsquo;t hand over your server list just now, so this section is empty. Reload in a minute.</Notice>
              ) : lists.addable.length === 0 ? (
                <p className="text-sm text-fg-muted">Every server you manage already has the bot.</p>
              ) : (
                <ul className="grid gap-2 sm:grid-cols-2">
                  {lists.addable.map((guild: AddableGuild) => (
                    <li key={guild.id} className="card relative flex items-center gap-3 overflow-hidden p-3 pl-4">
                      <Rail color={null} className="absolute inset-y-0 left-0 w-1.5" />
                      <GuildIcon guild={guild} />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-medium">{guild.name}</span>
                        <span className="block text-xs text-fg-faint">{guild.owner ? "Owner" : "Manage Server"}</span>
                      </span>
                      {invite ? (
                        <a
                          href={inviteFor(invite, guild.id)}
                          className="inline-flex h-8 shrink-0 items-center rounded-[var(--radius-control)] border border-border-strong px-2.5 text-sm font-medium text-fg hover:bg-surface-2"
                        >
                          Add to server
                        </a>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}
