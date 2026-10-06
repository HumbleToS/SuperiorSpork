import { PageHeader } from "@/components/brainrot/page-header";
import { SettingsForm } from "@/components/brainrot/settings-form";
import { BotOffline } from "@/components/shell/bot-offline";
import { Notice } from "@/components/ui/notice";
import { requireSession } from "@/lib/auth/require";
import { getBrainrotConfig, getBrainrotDefaults, getGuildMeta } from "@/lib/bot/client";
import { load } from "@/lib/bot/load";

export const metadata = { title: "Settings" };

export default async function SettingsPage({ params }: PageProps<"/g/[guildId]/brainrot/settings">) {
  const { guildId } = await params;
  const session = await requireSession(`/g/${guildId}/brainrot/settings`);
  const loaded = await load(() => Promise.all([getBrainrotConfig(guildId, session.userId), getGuildMeta(guildId, session.userId), getBrainrotDefaults()]));
  if (!loaded.ok) return <BotOffline detail={loaded.offline} />;
  const [config, meta, defaults] = loaded.data;
  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Settings" description="Every knob the /brainrot config commands have." />
      {!config.ready ? (
        <Notice tone="warn" title="Something needs attention">
          <ul className="mt-1 flex flex-col gap-0.5">
            {config.problems.map((problem) => (
              <li key={problem}>· {problem}</li>
            ))}
          </ul>
        </Notice>
      ) : null}
      <SettingsForm guildId={guildId} config={config} defaults={defaults} channels={meta.channels} roles={meta.roles} />
    </div>
  );
}
