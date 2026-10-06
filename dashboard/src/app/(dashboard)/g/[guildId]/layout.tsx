import { notFound } from "next/navigation";
import { DashboardHeader } from "@/components/shell/header";
import { ServerSwitcher } from "@/components/shell/server-switcher";
import { Sidebar } from "@/components/shell/sidebar";
import { BotOffline } from "@/components/shell/bot-offline";
import { requireSession } from "@/lib/auth/require";
import { BotUnreachableError, getGuilds } from "@/lib/bot/client";
import type { GuildSummary } from "@/lib/bot/schemas";

/**
 * The frame for one server: the bot confirms the signed-in user manages it (its list is the truth),
 * then the switcher and the registry-driven sidebar wrap every module page.
 */
export default async function GuildLayout({ children, params }: LayoutProps<"/g/[guildId]">) {
  const { guildId } = await params;
  const session = await requireSession(`/g/${guildId}/commands`);
  if (!/^\d{15,22}$/.test(guildId)) notFound();

  let guilds: GuildSummary[] = [];
  let offline: string | null = null;
  try {
    guilds = await getGuilds(session.userId);
  } catch (error) {
    if (!(error instanceof BotUnreachableError)) throw error;
    offline = error.message;
  }
  const guild = guilds.find((candidate) => candidate.id === guildId);
  if (!offline && !guild) notFound();

  return (
    <div className="flex min-h-dvh flex-col">
      <DashboardHeader session={session} switcher={<ServerSwitcher guilds={guilds} currentId={guild?.id ?? null} />} />
      <div className="mx-auto flex w-full max-w-7xl flex-1 flex-col gap-4 px-4 py-2 lg:flex-row lg:gap-8 lg:py-8">
        {guild ? <Sidebar guildId={guild.id} /> : null}
        <main id="main" className="min-w-0 flex-1 py-2 lg:py-0">
          {offline ? <BotOffline detail={offline} /> : children}
        </main>
      </div>
    </div>
  );
}
