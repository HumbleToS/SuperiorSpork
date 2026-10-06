import Link from "next/link";
import { ActionRow } from "@/components/brainrot/action-row";
import { EnableToggle } from "@/components/brainrot/enable-toggle";
import { HealthPanel } from "@/components/brainrot/health";
import { PageHeader } from "@/components/brainrot/page-header";
import { Stat } from "@/components/brainrot/stat";
import { BotOffline } from "@/components/shell/bot-offline";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { requireSession } from "@/lib/auth/require";
import { getActions, getApp, getBrainrotConfig, getBrainrotSummary, getGuildMeta } from "@/lib/bot/client";
import { load } from "@/lib/bot/load";

export const metadata = { title: "Anti-brainrot" };

export default async function OverviewPage({ params }: PageProps<"/g/[guildId]/brainrot">) {
  const { guildId } = await params;
  const session = await requireSession(`/g/${guildId}/brainrot`);
  const loaded = await load(async () => {
    const [config, meta, summary, recent, app] = await Promise.all([
      getBrainrotConfig(guildId, session.userId),
      getGuildMeta(guildId, session.userId),
      getBrainrotSummary(guildId, session.userId),
      getActions(guildId, session.userId, 1, {}, 5),
      getApp().catch(() => null),
    ]);
    return { config, meta, summary, recent, app };
  });
  if (!loaded.ok) return <BotOffline detail={loaded.offline} />;
  const { config, meta, summary, recent, app } = loaded.data;
  const base = `/g/${guildId}/brainrot`;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Overview" description={`${meta.name} · ${summary.watched_channels} watched channel${summary.watched_channels === 1 ? "" : "s"}, ${config.counts.terms} active terms.`} />

      <Card>
        <EnableToggle guildId={guildId} enabled={config.enabled} ready={config.ready} />
      </Card>

      <Card>
        <CardHeader title="Permission health" description="The same checks /brainrot enable runs." />
        <HealthPanel readiness={{ ready: config.ready, problems: config.problems }} permissions={meta.me.permissions} inviteUrl={app?.invite_url ?? null} guildId={guildId} />
      </Card>

      <section aria-labelledby="heat" className="flex flex-col gap-3">
        <h2 id="heat" className="text-base font-semibold">
          Heat right now
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <Stat label="Hot members" value={summary.hot_users} hint="heat above zero" />
          <Stat label="Muted now" value={summary.muted_now} />
          <Stat label="Repeat list" value={summary.on_repeat_list} hint="7 days after a mute" />
          <Stat label="Actions today" value={summary.actions_24h} />
          <Stat label="Lifetime offenses" value={summary.lifetime_offenses} />
        </div>
      </section>

      <Card className="p-0">
        <div className="px-4 pt-4 sm:px-5 sm:pt-5">
          <CardHeader
            title="Latest activity"
            action={
              <Link href={`${base}/activity`} className="text-sm text-accent underline-offset-4 hover:underline">
                All activity
              </Link>
            }
          />
        </div>
        {recent.items.length === 0 ? (
          <div className="px-4 pb-4 sm:px-5 sm:pb-5">
            <EmptyState title="Nothing yet">Warnings, mutes, pardons, and settings changes show up here.</EmptyState>
          </div>
        ) : (
          <ul className="divide-y divide-border border-t border-border">
            {recent.items.map((action) => (
              <ActionRow key={action.id} action={action} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
